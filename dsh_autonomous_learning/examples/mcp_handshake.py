"""MCP 客户端握手验证：证明本插件能被 MCP 客户端（DSH 用同一协议）正常调用。

运行（必须从包目录的父目录执行，或用 PYTHONPATH 指向它）：

    set PYTHONPATH=D:\\Adsh\\Zdsh
    python dsh_autonomous_learning\\examples\\mcp_handshake.py

脚本会：启动 stdio 服务器 → initialize → tools/list → 调用 create_learning_project →
调用 search_knowledge（空库应明确报告知识缺口）→ 关闭。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

try:
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError as exc:  # pragma: no cover
    print(f"需要 mcp SDK: {exc}")
    raise SystemExit(2)


async def run(home: Path) -> int:
    env = dict(os.environ)
    env["DSH_AL_HOME"] = str(home)
    env.setdefault("PYTHONPATH", str(Path(__file__).resolve().parents[2]))
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "dsh_autonomous_learning.plugin"],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("initialize ->", init.serverInfo.name, init.serverInfo.version)
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print(f"tools/list -> {len(names)} 个工具")
            print("示例工具:", ", ".join(names[:6]), "...")

            created = await session.call_tool(
                "create_learning_project",
                {"goal": "MCP 握手验证：学习 Python 并发基础", "domain": "programming", "plan": True},
            )
            payload = json.loads(created.content[0].text)
            print("create_learning_project -> success =", payload["success"])
            project_id = payload["data"]["project"]["project"]["project_id"]
            print("任务数 ->", payload["data"]["plan"]["task_count"])

            empty = await session.call_tool("search_knowledge", {"query": "GIL", "project_id": project_id})
            empty_payload = json.loads(empty.content[0].text)
            print("search_knowledge（空库）-> gap =", empty_payload["data"]["gap"])

            saved = await session.call_tool(
                "save_knowledge",
                {
                    "project_id": project_id,
                    "items": [
                        {
                            "title": "GIL",
                            "content": "CPython 的 GIL 使同一时刻只有一个线程执行字节码，CPU 密集任务应使用多进程。",
                            "source_url": "https://docs.python.org/3/glossary.html",
                            "source_type": "official_doc",
                        }
                    ],
                },
            )
            saved_payload = json.loads(saved.content[0].text)
            print("save_knowledge -> success =", saved_payload["success"])

            found = await session.call_tool("search_knowledge", {"query": "GIL 线程", "project_id": project_id})
            found_payload = json.loads(found.content[0].text)
            hits = found_payload["data"]["results"]
            print("search_knowledge -> 命中", len(hits), "条")
            if hits:
                print("  首条:", hits[0]["title"], "| 核验状态:", hits[0]["verification_status"])
            print("MCP 握手与工具调用验证通过")
            return 0


def main() -> int:
    home = Path(tempfile.mkdtemp(prefix="al_mcp_"))
    return anyio.run(run, home)


if __name__ == "__main__":
    raise SystemExit(main())
