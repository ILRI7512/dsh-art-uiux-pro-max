"""本地 CLI。

用途：不经过 MCP 也能直接使用与验证引擎（测试、演示、排障）。

    python -m dsh_autonomous_learning.main init
    python -m dsh_autonomous_learning.main project-create --goal "学习外汇量化交易" --domain quant
    python -m dsh_autonomous_learning.main plan --project prj_xxx
    python -m dsh_autonomous_learning.main ingest --project prj_xxx --path data/corpus/demo.md
    python -m dsh_autonomous_learning.main run --project prj_xxx --max-tasks 8
    python -m dsh_autonomous_learning.main search --query "滑点" --project prj_xxx
    python -m dsh_autonomous_learning.main verify --chunk chunk_xxx
    python -m dsh_autonomous_learning.main report --project prj_xxx
    python -m dsh_autonomous_learning.main audit --project prj_xxx
    python -m dsh_autonomous_learning.main tools list
    python -m dsh_autonomous_learning.main tools call search_knowledge '{"query":"风险"}'
    python -m dsh_autonomous_learning.main serve
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import load_config
from .core.models import utcnow_iso
from .core.orchestrator import build_runtime
from .tools import build_registry


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _build(args: argparse.Namespace):
    home = Path(args.home) if getattr(args, "home", None) else None
    overrides: Dict[str, Any] = {}
    if getattr(args, "mode", None):
        overrides.setdefault("learning", {})["default_mode"] = args.mode
    if getattr(args, "data_dir", None):
        overrides.setdefault("paths", {})["data_dir"] = args.data_dir
    config = load_config(
        path=getattr(args, "config", None), overrides=overrides or None, home=home
    )
    runtime = build_runtime(config)
    registry, orchestrator, scheduler = build_registry(runtime)
    return config, runtime, registry, orchestrator, scheduler


# --------------------------------------------------------------------------- #
def cmd_init(args: argparse.Namespace) -> int:
    config = load_config(home=Path(args.home) if args.home else None)
    config.paths.ensure()
    target = Path(config.paths.home) / "config.json"
    if target.exists() and not args.force:
        print(f"配置已存在: {target}（使用 --force 覆盖）")
    else:
        config.save(target)
        print(f"已写入配置: {target}")
    corpus = Path(config.paths.corpus_dir)
    corpus.mkdir(parents=True, exist_ok=True)
    print(_json({"data_dir": config.paths.data_dir, "db": config.paths.db_path, "corpus": str(corpus)}))
    return 0


def cmd_project_create(args: argparse.Namespace) -> int:
    _, runtime, _, orch, _ = _build(args)
    try:
        project = orch.create_project(
            goal=args.goal,
            title=args.title or "",
            domain=args.domain,
            depth=args.depth,
            mode=args.mode,
            allowed_sources=args.source or [],
        )
        data = {"project": project}
        if args.plan:
            data["plan"] = orch.plan(project["project"]["project_id"], use_model=args.use_model)
        print(_json(data))
    finally:
        runtime.close()
    return 0


def cmd_project_list(args: argparse.Namespace) -> int:
    _, runtime, _, orch, _ = _build(args)
    try:
        print(_json(orch.list_projects(args.status)))
    finally:
        runtime.close()
    return 0


def cmd_project_show(args: argparse.Namespace) -> int:
    _, runtime, _, orch, _ = _build(args)
    try:
        print(_json(orch.get_project(args.project)))
    finally:
        runtime.close()
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    _, runtime, _, orch, _ = _build(args)
    try:
        print(_json(orch.plan(args.project, use_model=args.use_model)))
    finally:
        runtime.close()
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    _, runtime, _, orch, _ = _build(args)
    try:
        print(_json(orch.run_round(args.project, max_tasks=args.max_tasks, use_model=args.use_model)))
    finally:
        runtime.close()
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    _, runtime, _, orch, _ = _build(args)
    try:
        location = args.path or args.url
        read = runtime.reader.read(location, project_id=args.project)
        if not read.ok:
            print(f"读取失败: {read.error}", file=sys.stderr)
            return 2
        saved = orch.ingest_document(args.project, read, topic=args.topic or "")
        project = runtime.metadata.get_project(args.project)
        extraction = runtime.extractor.extract(
            project=project,
            document={
                **saved,
                "text": read.text,
                "title": read.title,
                "source_type": read.source_type,
                "quality": (read.metadata or {}).get("quality", 0.5),
                "publisher": (read.metadata or {}).get("publisher", ""),
                "location": read.location,
                "published_at": (read.metadata or {}).get("published_at", ""),
                "content_hash": read.content_hash,
            },
            topic=args.topic or "",
            use_model=args.use_model,
        )
        persisted = runtime.store.add_chunks(extraction["drafts"]) if extraction["drafts"] else None
        print(
            _json(
                {
                    "document": saved,
                    "extraction": extraction["stats"],
                    "warnings": extraction["warnings"],
                    "persisted": persisted,
                }
            )
        )
    finally:
        runtime.close()
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    _, runtime, registry, _, _ = _build(args)
    try:
        payload: Dict[str, Any] = {"query": args.query, "top_k": args.top_k}
        if args.project:
            payload["project_id"] = args.project
        if args.partition:
            payload["partitions"] = args.partition
        print(_json(registry.call("search_knowledge", payload)))
    finally:
        runtime.close()
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    _, runtime, _, _, _ = _build(args)
    try:
        variables = json.loads(args.variables) if args.variables else None
        print(
            _json(
                runtime.verifier.verify(
                    args.chunk,
                    expression=args.expression,
                    variables=variables,
                    expected=args.expected,
                )
            )
        )
    finally:
        runtime.close()
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    _, runtime, _, orch, _ = _build(args)
    try:
        result = runtime.reporter.generate(args.project, evaluation=runtime.evaluator.evaluate(args.project))
        print(_json({"report_path": result["report_path"], "json_path": result["json_path"]}))
        if args.print:
            print(result["markdown"])
    finally:
        runtime.close()
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    _, runtime, registry, _, _ = _build(args)
    try:
        payload: Dict[str, Any] = {"fix": args.fix}
        if args.project:
            payload["project_id"] = args.project
        print(_json(registry.call("audit_knowledge_base", payload)))
    finally:
        runtime.close()
    return 0


def cmd_tools(args: argparse.Namespace) -> int:
    _, runtime, registry, _, _ = _build(args)
    try:
        if args.action == "list":
            print(_json(registry.list_specs(args.group)))
        else:
            arguments = json.loads(args.arguments or "{}")
            print(_json(registry.call(args.tool_name, arguments)))
    finally:
        runtime.close()
    return 0


def cmd_confirmations(args: argparse.Namespace) -> int:
    """用户侧批准入口：DSH 审批 UI 之外的备用通道（CLI）。

    智能体没有调用这里的工具，因此不存在"模型自己批准自己"的路径。
    """

    _, runtime, _, _, _ = _build(args)
    try:
        if args.action == "list":
            print(_json({"pending": runtime.permissions.pending_confirmations()}))
            return 0
        if args.action == "approve":
            ok = runtime.permissions.approve(args.token)
            print(_json({"approved": ok, "token": args.token}))
            return 0 if ok else 2
        if args.action == "reject":
            ok = runtime.permissions.reject(args.token, args.note or "")
            print(_json({"rejected": ok, "token": args.token}))
            return 0 if ok else 2
        raise ValueError(f"未知操作: {args.action}")
    finally:
        runtime.close()


def cmd_export_tool_risks(args: argparse.Namespace) -> int:
    """导出工具风险清单，供 DSH 宿主审批插件决定哪些调用需要 ask。"""

    _, runtime, registry, _, _ = _build(args)
    try:
        target = Path(args.out) if args.out else Path(runtime.config.paths.home) / "tool_risks.json"
        tools = {}
        for spec in registry.list_specs():
            tools[spec["name"]] = {
                "risk": spec["risk"],
                "requires_confirmation": bool(spec.get("requires_confirmation")),
                "side_effects": spec.get("side_effects", "none"),
                "description": spec["description"],
            }
        payload = {
            "generated_at": utcnow_iso(),
            "prefix": "mcp__autolearn__",
            "tools": tools,
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(_json({"path": str(target), "tools": len(tools)}))
    finally:
        runtime.close()


def cmd_serve(args: argparse.Namespace) -> int:
    from .plugin import main as plugin_main

    return plugin_main(["--mode", args.mode] if args.mode else [])


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dsh-autonomous-learning", description="DSH 自主学习插件 CLI")
    parser.add_argument("--home", help="插件数据根目录（默认包目录，可用 DSH_AL_HOME）")
    parser.add_argument("--config", help="配置文件路径（JSON/YAML）")
    parser.add_argument("--data-dir", help="覆盖数据目录")
    parser.add_argument("--mode", choices=["assisted", "auto", "lab"], help="自主等级")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="初始化目录与配置")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("project-create", help="创建学习项目")
    p.add_argument("--goal", required=True)
    p.add_argument("--title", default="")
    p.add_argument("--domain", default="general", choices=["general", "uiux", "finance", "quant", "programming", "project", "experiment"])
    p.add_argument("--depth", default="working", choices=["overview", "working", "deep"])
    p.add_argument("--source", action="append", help="允许的数据源（可多次）")
    p.add_argument("--plan", action="store_true", help="立即生成计划")
    p.add_argument("--use-model", action="store_true")
    p.set_defaults(func=cmd_project_create)

    p = sub.add_parser("project-list", help="列出项目")
    p.add_argument("--status", default=None)
    p.set_defaults(func=cmd_project_list)

    p = sub.add_parser("project-show", help="查看项目")
    p.add_argument("--project", required=True)
    p.set_defaults(func=cmd_project_show)

    p = sub.add_parser("plan", help="生成学习计划")
    p.add_argument("--project", required=True)
    p.add_argument("--use-model", action="store_true")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("run", help="执行一轮学习")
    p.add_argument("--project", required=True)
    p.add_argument("--max-tasks", type=int, default=None)
    p.add_argument("--use-model", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("ingest", help="导入并提取一份资料")
    p.add_argument("--project", required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--path")
    group.add_argument("--url")
    p.add_argument("--topic", default="")
    p.add_argument("--use-model", action="store_true")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("search", help="检索知识")
    p.add_argument("--query", required=True)
    p.add_argument("--project", default=None)
    p.add_argument("--partition", action="append")
    p.add_argument("--top-k", type=int, default=8)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("verify", help="核验知识")
    p.add_argument("--chunk", required=True)
    p.add_argument("--expression", default=None)
    p.add_argument("--variables", default=None, help="JSON 对象")
    p.add_argument("--expected", type=float, default=None)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("report", help="生成学习报告")
    p.add_argument("--project", required=True)
    p.add_argument("--print", action="store_true")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("audit", help="知识库体检")
    p.add_argument("--project", default=None)
    p.add_argument("--fix", action="store_true")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("tools", help="工具列表/调用")
    p.add_argument("action", choices=["list", "call"])
    p.add_argument("tool_name", nargs="?")
    p.add_argument("arguments", nargs="?")
    p.add_argument("--group", default=None)
    p.set_defaults(func=cmd_tools)

    p = sub.add_parser("confirmations", help="用户侧确认：列出/批准/拒绝待确认操作")
    p.add_argument("action", choices=["list", "approve", "reject"])
    p.add_argument("token", nargs="?", default="")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_confirmations)

    p = sub.add_parser("export-tool-risks", help="导出工具风险清单（供宿主审批插件使用）")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_export_tool_risks)

    p = sub.add_parser("serve", help="以 MCP stdio 服务器运行")
    p.set_defaults(func=cmd_serve)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        import traceback

        print(f"命令失败: {exc}", file=sys.stderr)
        if "--debug" in sys.argv or True:
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
