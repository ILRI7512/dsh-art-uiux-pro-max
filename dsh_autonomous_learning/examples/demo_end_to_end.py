"""端到端演示：目标 → 规划 → 发现/读取 → 提取 → 入库 → 检索 → 冲突 → 核验 → 报告。

运行（在项目根目录）：

    python examples/demo_end_to_end.py

演示使用 examples/corpus 下的两份量化笔记（含相互矛盾的夏普比率），
所有产物写入项目下的 data/ 目录，可重复执行（资料按内容指纹去重）。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from dsh_autonomous_learning.config import load_config  # noqa: E402
from dsh_autonomous_learning.core.orchestrator import build_runtime  # noqa: E402
from dsh_autonomous_learning.storage.metadata_store import ChunkFilter  # noqa: E402
from dsh_autonomous_learning.tools import build_registry  # noqa: E402


def line(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def main() -> int:
    config = load_config(
        home=ROOT,
        overrides={
            "paths": {"corpus_dir": str(ROOT / "data" / "corpus")},
            "security": {"allowed_roots": [str(ROOT)]},
            "learning": {"default_mode": "auto", "max_tasks_per_run": 20},
        },
    )
    config.paths.ensure()
    corpus_dir = Path(config.paths.corpus_dir)
    corpus_dir.mkdir(parents=True, exist_ok=True)
    for src in (ROOT / "examples" / "corpus").glob("*.md"):
        shutil.copy2(src, corpus_dir / src.name)

    runtime = build_runtime(config, mode="auto")
    registry, orchestrator, scheduler = build_registry(runtime)
    try:
        line("1) 创建学习项目")
        project = orchestrator.create_project(
            goal="学习外汇量化交易基础，区分理论结论、实证结果与待验证假设",
            title="演示：外汇量化交易",
            domain="quant",
            depth="working",
            allowed_sources=[str(p) for p in sorted(corpus_dir.glob("*.md"))],
        )
        project_id = project["project"]["project_id"]
        print(json.dumps({"project_id": project_id, "partitions": project["project"]["partitions"]}, ensure_ascii=False))

        line("2) 生成学习计划")
        plan = orchestrator.plan(project_id)
        print(f"任务数: {plan['task_count']}")
        for task in plan["tasks"][:6]:
            print(f"  - [{task['kind']}] {task['title']}（依赖 {len(task['depends_on'])} 个）")

        line("3) 执行一轮学习（有界）")
        result = orchestrator.run_round(project_id, max_tasks=14)
        print(
            json.dumps(
                {
                    "tasks_executed": len(result["tasks_executed"]),
                    "new_knowledge": result["new_knowledge"],
                    "stop_reason": result["stop_reason"],
                    "budget": result["budget"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        line("4) 知识库概况")
        print(json.dumps(runtime.store.stats(), ensure_ascii=False, indent=2)[:1200])

        line("5) 语义 + 关键词混合检索：滑点")
        found = runtime.store.search("滑点对回测收益的影响", ChunkFilter(project_id=project_id), top_k=3)
        for item in found["results"]:
            print(
                f"- {item['chunk_id'][:18]} score={item['score']} 类型={item['knowledge_type']} "
                f"状态={item['status']} 来源={item['source']['title'] or item['source']['url']}"
            )
            print(f"  {item['summary'][:100]}")
            if item["warnings"]:
                print(f"  ⚠ {item['warnings'][0]}")

        line("6) 冲突检测（同一主题下数值矛盾）")
        scanned = runtime.conflicts.scan(project_id)
        print(f"扫描 {scanned['scanned']} 条，发现冲突 {len(scanned['findings'])} 组，登记 {scanned['recorded']} 组")
        for conflict in runtime.metadata.list_conflicts(project_id=project_id)[:3]:
            print(f"- [{conflict['status']}] {conflict['kind']}: {conflict['detail']}")

        line("7) 核验一条知识（有证据才允许升级）")
        pending = runtime.metadata.list_chunks(
            ChunkFilter(project_id=project_id, statuses=["pending_verification"]), limit=1
        )
        if pending:
            chunk = pending[0]
            outcome = runtime.verifier.verify(chunk["chunk_id"])
            print(
                json.dumps(
                    {
                        "chunk_id": outcome["chunk_id"],
                        "method": outcome["method"],
                        "result": outcome["result"],
                        "status_before": outcome["status_before"],
                        "status_after": outcome["status_after"],
                        "confidence": outcome["confidence"],
                        "reasons": outcome["reasons"][:3],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )

        line("8) 学习评估")
        evaluation = runtime.evaluator.evaluate(project_id)
        print(
            json.dumps(
                {
                    "metrics": evaluation["metrics"],
                    "goal_met": evaluation["goal_met"],
                    "remaining": evaluation["remaining"][:5],
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        line("9) 生成报告")
        report = runtime.reporter.generate(project_id, evaluation=evaluation)
        print(f"Markdown: {report['report_path']}")
        print(f"JSON    : {report['json_path']}")

        line("10) 知识库体检")
        audit = registry.call("audit_knowledge_base", {"project_id": project_id, "fix": True})
        data = audit["data"]
        print(
            json.dumps(
                {
                    "chunks": data["chunks"],
                    "index_ok": data["index_integrity"]["ok"],
                    "missing_source": data["missing_source"],
                    "unverified": data["unverified"],
                    "new_conflicts": data["new_conflicts"],
                    "issues": data["issues"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("\n演示结束。数据位于 data/，可用 CLI 继续：")
        print(f"  python -m dsh_autonomous_learning.main run --project {project_id}")
        return 0
    finally:
        runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
