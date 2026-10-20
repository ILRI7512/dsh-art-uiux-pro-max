"""MCP stdio 服务器 —— DSH 接入入口。

为什么用 MCP：
DSH 的 profile 已安装 ``dsh-mcp-connector``，支持以 stdio 方式接入外部 MCP Server。
这条路径不需要构建 Cordis/npm 插件，也不会碰 DSH 内核文件，符合"不修改其他插件、
不假设未知协议"的要求。工具在 DSH 中会以 ``mcp__<serverName>__<tool>`` 出现。

运行方式（由 MCP 连接器/客户端启动）::

    python -m dsh_autonomous_learning.plugin

本文件只做三件事：加载配置 → 组装 runtime/registry → 暴露 tools 与 call_tool。
所有业务逻辑都在 tools/ 与 core/ 中，便于单元测试。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import anyio
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .config import load_config
from .core.orchestrator import build_runtime
from .tools import build_registry

SERVER_NAME = "dsh-autonomous-learning"


def _log(message: str) -> None:
    # stdout 被 MCP 协议占用，日志只能写 stderr
    print(f"[{SERVER_NAME}] {message}", file=sys.stderr, flush=True)


class LearningServer:
    def __init__(self, mode: Optional[str] = None) -> None:
        home = os.environ.get("DSH_AL_HOME")
        overrides: Dict[str, Any] = {}
        if mode:
            overrides["learning"] = {"default_mode": mode}
        self.config = load_config(overrides=overrides, home=Path(home) if home else None)
        self.runtime = build_runtime(self.config, mode=mode)
        self.registry, self.orchestrator, self.scheduler = build_registry(self.runtime)
        self.server = Server(SERVER_NAME)
        self._register_handlers()

    # ------------------------------------------------------------------ #
    def _register_handlers(self) -> None:
        @self.server.list_tools()
        async def list_tools() -> List[types.Tool]:
            return [
                types.Tool(
                    name=spec["name"],
                    description=spec["description"],
                    inputSchema=spec["input_schema"],
                )
                for spec in self.registry.list_specs()
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Optional[Dict[str, Any]]) -> List[types.TextContent]:
            result = await anyio.to_thread.run_sync(
                lambda: self.registry.call(name, arguments or {})
            )
            return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

    # ------------------------------------------------------------------ #
    async def run(self) -> None:
        _log(
            f"启动：mode={self.runtime.permissions.mode} "
            f"tools={len(self.registry.names())} data={self.config.paths.data_dir}"
        )
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )


def main(argv: Optional[List[str]] = None) -> int:
    mode = None
    args = list(sys.argv[1:] if argv is None else argv)
    if "--mode" in args:
        index = args.index("--mode")
        if index + 1 < len(args):
            mode = args[index + 1]
    try:
        server = LearningServer(mode=mode)
    except Exception as exc:  # noqa: BLE001
        _log(f"初始化失败: {exc}")
        return 1
    try:
        anyio.run(server.run)
    except KeyboardInterrupt:  # pragma: no cover
        return 0
    finally:
        server.runtime.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
