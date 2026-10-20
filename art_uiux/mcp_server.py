"""Art UI/UX Pro Max 的 MCP 服务端（stdio）。

暴露 11 个工具，全部复用本项目已在 CLI 里验证过的实现：
分类体系、资源注册表、访问探测、入库学习、案例分析、检索、
视觉方向、设计系统、审计、多尺寸矩阵、背景方案。

约定：任何「未验证」的结论都在返回值里带 warnings，不靠调用方自觉。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mcp.types as types                                    # noqa: E402
from mcp.server import Server                                # noqa: E402
from mcp.server.stdio import stdio_server                    # noqa: E402

from art_uiux.case_analyzer import analyze_html, units_from_case      # noqa: E402
from art_uiux.checker import probe                                     # noqa: E402
from art_uiux.design_workflow import (                                  # noqa: E402
    audit_html, build_design_system, propose_directions, retrieve,
    route_task, tokens_to_css,
)
from art_uiux.extract import build_unit, classify, fetch_html, sectionize  # noqa: E402
from art_uiux.registry import Registry                                  # noqa: E402
from art_uiux.tasks_special import generate_backgrounds, responsive_matrix  # noqa: E402
from art_uiux.taxonomy import describe_taxonomy                          # noqa: E402

SERVER_NAME = "dsh-art-uiux-pro-max"
_registry = Registry(ROOT)
_runtime = None


def runtime():
    """懒加载引擎运行时，避免 MCP 握手阶段就打开数据库。"""

    global _runtime
    if _runtime is None:
        engine = ROOT / "dsh_autonomous_learning"
        if str(engine) not in sys.path:
            sys.path.insert(0, str(engine))
        from dsh_autonomous_learning.config import load_config
        from dsh_autonomous_learning.core.orchestrator import build_runtime

        cfg = load_config(home=engine, overrides={"security": {"allow_network": True}})
        _runtime = build_runtime(cfg)
    return _runtime


def ok(data: Any, warnings: List[str] | None = None) -> str:
    return json.dumps({"success": True, "data": data, "warnings": warnings or []}, ensure_ascii=False)


def err(message: str, kind: str = "ToolError") -> str:
    return json.dumps({"success": False, "error": {"type": kind, "message": message}}, ensure_ascii=False)


server = Server(SERVER_NAME)


@server.list_tools()
async def list_tools() -> List[types.Tool]:
    def spec(name: str, desc: str, props: Dict[str, Any], required: List[str] | None = None) -> types.Tool:
        return types.Tool(
            name=name, description=desc,
            inputSchema={"type": "object", "properties": props, "required": required or []},
        )

    return [
        spec("art_taxonomy", "返回 12 个主分类及其 12 项元数据、16 个提取字段。", {}),
        spec("art_registry_list", "列出资源注册表（种子+真实状态合并）。",
             {"category": {"type": "string"}, "type": {"type": "string"},
              "access_status": {"type": "string"}, "limit": {"type": "integer"}}),
        spec("art_registry_check", "对资源做真实访问探测（robots 前置），写入 access_status。",
             {"resource_id": {"type": "string", "description": "留空则检查全部"}}),
        spec("art_learn", "抓取并提取知识入库；写入 learn_status 与真实片段数。",
             {"resource_id": {"type": "string"}, "max_units": {"type": "integer"}}),
        spec("art_case_analyze", "Design Case Analyzer：分析真实页面，产出事实/推断分离的案例知识。",
             {"resource_id": {"type": "string"}, "max_units": {"type": "integer"}}),
        spec("art_search", "混合检索（向量+BM25+RRF+分类亲和度），可选交叉编码器精排；返回来源、等级与告警。",
             {"query": {"type": "string"}, "categories": {"type": "array", "items": {"type": "string"}},
              "top_k": {"type": "integer"},
              "rerank": {"type": "string", "enum": ["rules", "ce"],
                         "description": "rules=规则重排（默认，约 200ms）；ce=交叉编码器精排（更准，本机约 2s）"}},
             ["query"]),
        spec("art_route_task", "识别 UI 设计需求属于哪种任务类型，并给出相关分类。",
             {"text": {"type": "string"}}, ["text"]),
        spec("art_directions", "给出有实质区别的视觉方向（拒绝默认玻璃拟态/深色/蓝紫渐变）。",
             {"task_type": {"type": "string"}, "count": {"type": "integer"}}),
        spec("art_design_system", "产出 Design Tokens 与 CSS，并对关键配色做对比度实算。",
             {"direction": {"type": "string"}}),
        spec("art_audit", "对给定 HTML/CSS 做 10 项设计审计；不能测的标 unmeasured。",
             {"html": {"type": "string"}, "direction": {"type": "string"}}, ["html"]),
        spec("art_responsive", "输出多断点布局矩阵（静态推断，不冒充真机渲染）。",
             {"html": {"type": "string"}}, ["html"]),
        spec("art_backgrounds", "给出三种机制不同的背景方案并实测文字对比度。",
             {"text_color": {"type": "string"}}),
        spec("art_stats", "知识库与注册表的真实统计。", {}),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[types.TextContent]:
    try:
        if name == "art_taxonomy":
            return [types.TextContent(type="text", text=ok(describe_taxonomy()))]

        if name == "art_registry_list":
            items = _registry.view()
            if arguments.get("category"):
                items = [i for i in items if i["primary_category"] == arguments["category"]]
            if arguments.get("type"):
                items = [i for i in items if i["resource_type"] == arguments["type"]]
            if arguments.get("access_status"):
                items = [i for i in items if i["access_status"] == arguments["access_status"]]
            limit = int(arguments.get("limit") or 50)
            return [types.TextContent(type="text", text=ok({
                "total": len(items), "resources": items[:limit], "stats": _registry.stats()}))]

        if name == "art_registry_check":
            rid = arguments.get("resource_id") or ""
            items = [_registry.get(rid)] if rid else _registry.view()
            if rid and not items[0]:
                return [types.TextContent(type="text", text=err("未知 resource_id: %s" % rid))]
            results = []
            for item in items:
                r = probe(item["url"])
                _registry.record_check(item["resource_id"], access_status=r.access_status,
                                       http_status=r.http_status, final_url=r.final_url,
                                       content_type=r.content_type, bytes_read=r.bytes_read,
                                       robots_allowed=r.robots_allowed, error=r.error)
                results.append({"resource_id": item["resource_id"], "status": r.access_status,
                                "http": r.http_status, "robots": r.robots_allowed})
            return [types.TextContent(type="text", text=ok({"checked": len(results), "results": results}))]

        if name == "art_learn":
            rid = arguments.get("resource_id")
            if not rid:
                return [types.TextContent(type="text", text=err("必须指定 resource_id"))]
            res = _registry.get(rid)
            if not res:
                return [types.TextContent(type="text", text=err("未知 resource_id: %s" % rid))]
            html, final_url, status = fetch_html(res["url"])
            sections = sectionize(html)
            units = []
            for section in sections[: int(arguments.get("max_units") or 8)]:
                cat, score, matched = classify(section.text, heading=section.heading)
                unit = build_unit(section, resource=res, category=cat, score=score, matched=matched)
                if unit["ready_to_ingest"]:
                    units.append(unit)
            _registry.record_learning(rid, learn_status="partial", chunks=len(units),
                                      notes="MCP art_learn: %d 个候选单元" % len(units))
            return [types.TextContent(type="text", text=ok({
                "resource_id": rid, "sections": len(sections), "units": len(units),
                "units_preview": [{k: u[k] for k in ("category", "level", "heading")} for u in units[:5]],
            }, warnings=["art_learn 只做提取预览；正式入库请走 scripts/ingest.py，避免重复计数"]))]

        if name == "art_case_analyze":
            rid = arguments.get("resource_id")
            res = _registry.get(rid) if rid else None
            if not res:
                return [types.TextContent(type="text", text=err("未知 resource_id"))]
            html, final_url, _ = fetch_html(res["url"])
            ca = analyze_html(html, url=res["url"], product=res["name"], platform=res["platform"])
            units = units_from_case(ca, resource=res)[: int(arguments.get("max_units") or 20)]
            return [types.TextContent(type="text", text=ok({
                "case": ca.product, "tech_stack": ca.tech_stack,
                "sections": {k: len(v) for k, v in ca.sections.items()},
                "units": len(units), "metrics": ca.metrics,
            }, warnings=["案例结论基于静态 HTML；视觉判断与可用性结论未测"]))]

        if name == "art_search":
            cats = arguments.get("categories") or []
            if not cats:
                _, cats, _ = route_task(arguments["query"])
            from art_uiux.retrieval import search as art_search

            found = art_search(runtime(), arguments["query"], top_k=int(arguments.get("top_k") or 5),
                               categories=cats or None, bilingual=True,
                               rerank=(arguments.get("rerank") or "rules"))
            warnings = []
            if found["unverified"]:
                warnings.append("命中结果全部 unverified，不得当作既定事实")
            if not found["evidence_sufficient"]:
                warnings.append(found["answer_if_empty"])
            return [types.TextContent(type="text", text=ok(found, warnings))]

        if name == "art_route_task":
            task_type, cats, basis = route_task(arguments["text"])
            return [types.TextContent(type="text", text=ok({"task_type": task_type, "categories": cats, "basis": basis}))]

        if name == "art_directions":
            dirs = propose_directions(arguments.get("task_type") or "web_page",
                                      count=int(arguments.get("count") or 3))
            return [types.TextContent(type="text", text=ok({"directions": dirs}))]

        if name == "art_design_system":
            ds = build_design_system(arguments.get("direction") or "swiss_grid")
            return [types.TextContent(type="text",
                                      text=ok({"tokens": ds["tokens"], "css": tokens_to_css(ds),
                                               "contrast": ds["contrast"], "verified": ds["verified"]},
                                              [ds["note"]]))]

        if name == "art_audit":
            ds = build_design_system(arguments.get("direction") or "swiss_grid")
            result = audit_html(arguments["html"], tokens=ds["tokens"])
            return [types.TextContent(type="text", text=ok(result, [result["note"]]))]

        if name == "art_responsive":
            result = responsive_matrix(arguments["html"])
            return [types.TextContent(type="text", text=ok(result, [result["note"]]))]

        if name == "art_backgrounds":
            bgs = generate_backgrounds(text_color=arguments.get("text_color") or "#e6e9ee")
            return [types.TextContent(type="text", text=ok({"backgrounds": bgs}))]

        if name == "art_stats":
            st = _registry.stats()
            try:
                store = runtime().store.stats()
            except Exception as exc:  # noqa: BLE001
                store = {"error": str(exc)}
            return [types.TextContent(type="text", text=ok({"registry": st, "knowledge": store}))]

        return [types.TextContent(type="text", text=err("未知工具: %s" % name, "UnknownTool"))]
    except Exception as exc:  # noqa: BLE001
        return [types.TextContent(type="text", text=err("%s: %s" % (type(exc).__name__, exc)))]


async def _main() -> None:
    async with stdio_server() as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_main())
