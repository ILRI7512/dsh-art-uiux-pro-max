#!/usr/bin/env python3
"""跑一次完整的七步设计工作流，产出可检查的交付物。

用法：
    python3 scripts/design_task.py --task "做一个金融行情终端首页" --direction industrial_dense
    python3 scripts/design_task.py --task "Compose 写一个 Android 首页" --direction swiss_grid
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dsh_autonomous_learning"))

from dsh_autonomous_learning.config import load_config                          # noqa: E402
from dsh_autonomous_learning.core.orchestrator import build_runtime             # noqa: E402

from art_uiux.design_workflow import (                                          # noqa: E402
    TASK_TYPES, audit_html, build_design_system, check_palette, feedback_unit,
    propose_directions, retrieve, route_task, tokens_to_css,
)

OUT_DIR = ROOT / "docs" / "tasks"


def prototype_html(task_type: str, ds: dict) -> str:
    c = ds["tokens"]["color"]
    if task_type == "fintech_terminal":
        body = """
<main class="terminal">
  <header class="terminal__bar">
    <h1>EURUSD · 行情终端</h1>
    <span class="pill">已连接</span>
  </header>
  <section class="grid">
    <article class="card"><h2>EURUSD</h2><p class="num">1.0842</p><p class="delta up">+0.32%</p></article>
    <article class="card"><h2>XAUUSD</h2><p class="num">2412.10</p><p class="delta down">−0.18%</p></article>
    <article class="card"><h2>持仓</h2><p class="num">3</p><p class="delta">浮动 +128.40</p></article>
  </section>
  <section class="card table">
    <table><thead><tr><th>品种</th><th>方向</th><th>手数</th><th>盈亏</th></tr></thead>
    <tbody><tr><td>EURUSD</td><td>多</td><td>0.50</td><td class="up">+62.10</td></tr>
    <tr><td>XAUUSD</td><td>空</td><td>0.20</td><td class="down">−18.40</td></tr></tbody></table>
  </section>
</main>"""
    else:
        body = """
<main class="page">
  <h1>Design with intent</h1>
  <p class="lede">A layout built from measured tokens rather than decoration.</p>
  <section class="grid">
    <article class="card"><h2>Hierarchy</h2><p>Three type steps, one accent.</p></article>
    <article class="card"><h2>Rhythm</h2><p>8px spacing scale.</p></article>
  </section>
</main>"""

    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s prototype</title>
<style>
%s
body{margin:0;background:%s;color:%s;font-family:Inter,system-ui,sans-serif}
h1{font-size:56px;line-height:1.1;margin:0 0 12px}
h2{font-size:20px;margin:0 0 8px}
p{font-size:16px;color:%s}
.card{background:%s;border-radius:12px;padding:24px;box-shadow:0 1px 2px rgba(0,0,0,.06)}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));padding:24px}
.terminal__bar{display:flex;justify-content:space-between;align-items:center;padding:16px 24px;border-bottom:1px solid rgba(255,255,255,.08)}
.num{font-size:28px}
.up{color:%s}.down{color:%s}
.pill{border:1px solid rgba(255,255,255,.2);border-radius:999px;padding:4px 10px;font-size:12px}
table{width:100%%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid rgba(255,255,255,.06)}
.card:hover{box-shadow:0 8px 24px rgba(0,0,0,.10)}
.card:focus-visible{outline:2px solid %s;outline-offset:2px}
.card:disabled{opacity:.5}
.card:active{transform:translateY(1px)}
</style></head><body>%s</body></html>""" % (
        task_type, tokens_to_css(ds), c["bg"], c["fg"], c["muted"], c["surface"], c["accent"], c["positive"], c["negative"], body)


def compose_snippet(ds: dict) -> str:
    c = ds["tokens"]["color"]
    return """// 由 DSH Art UI/UX Pro Max 生成的设计 token（Compose 侧）
// 说明：这是骨架示例，未接入具体工程的导航与状态管理。

private val ArtColors = lightColorScheme(
    primary = Color(0xFF%s),
    background = Color(0xFF%s),
    onBackground = Color(0xFF%s),
    surface = Color(0xFF%s),
)

@Composable
fun ArtHomeScreen(modifier: Modifier = Modifier) {
    Scaffold(topBar = { TopAppBar(title = { Text("首页") }) }) { padding ->
        LazyColumn(
            modifier = modifier.padding(padding).fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item { Text("今日概览", style = MaterialTheme.typography.headlineSmall) }
            items(3) { index ->
                Card(shape = RoundedCornerShape(12.dp)) {
                    Column(Modifier.padding(16.dp)) {
                        Text("指标 " + (index + 1), style = MaterialTheme.typography.titleMedium)
                        Text("数值占位", style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
        }
    }
}
""" % (c["accent"].lstrip("#"), c["bg"].lstrip("#"), c["fg"].lstrip("#"), c["surface"].lstrip("#"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--direction", default="")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    task_type, categories, basis = route_task(args.task)
    print("① 任务类型:", task_type, "|", TASK_TYPES[task_type]["label"], "|", basis)
    print("   相关分类:", ", ".join(categories))

    cfg = load_config(home=ROOT / "dsh_autonomous_learning")
    rt = build_runtime(cfg)
    try:
        found = retrieve(rt, query=args.task, categories=categories, top_k=args.top)
        print("② 检索命中:", found["count"], "| 等级分布:", found["level_spread"],
              "| 全部未核验:", found["unverified"])
        for hit in found["hits"][:3]:
            print("   -", (hit.get("title") or "")[:50], "|", hit.get("level"),
                  "|", (hit.get("source") or {}).get("url"))
    finally:
        rt.close()

    dirs = propose_directions(task_type, count=3)
    print("③ 候选方向:", [d["name"] for d in dirs])
    chosen_key = args.direction or dirs[0]["key"]
    chosen = next(d for d in dirs if d["key"] == chosen_key) if any(d["key"] == chosen_key for d in dirs) else dirs[0]

    ds = build_design_system(chosen["key"])
    failing = ds["failing_pairs"]
    print("④ 设计系统: 对比度实算 %d 对，未达标 %d 对" % (len(ds["contrast"]), len(failing)))
    for item in ds["contrast"]:
        if item.get("measured"):
            print("   %-14s %s on %s = %.2f:1  AA=%s" % (
                item["pair"], item["fg"], item["bg"], item["ratio"], item["AA_normal"]))

    if task_type == "android_native":
        code = compose_snippet(ds)
        audit = {"items": [], "counts": {"unmeasured": 10}, "measured_items": 0,
                 "note": "Android 代码未经真实构建与渲染，审计项全部 unmeasured"}
    else:
        html = prototype_html(task_type, ds)
        code = html
        audit = audit_html(html, tokens=ds["tokens"])

    print("⑥ 审计:", audit["counts"], "| 可实测项:", audit["measured_items"])
    for item in audit["items"]:
        print("   [%-10s] %-24s %s" % (item["status"], item["item"], item["detail"][:70]))

    fb = feedback_unit(decision="方向 %s 的 token 基线" % chosen["name"],
                       evidence="对比度实算见报告；尚未经过真实用户或生产验证",
                       scope="project", category=categories[0])
    print("⑦ 反馈单元:", fb["scope"], fb["partition"], fb["level"])

    if not args.no_write:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        stem = task_type
        (OUT_DIR / ("%s.ds.json" % stem)).write_text(
            json.dumps({"task": args.task, "task_type": task_type, "direction": chosen,
                        "design_system": ds, "audit": audit, "feedback": fb},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        ext = "kt" if task_type == "android_native" else "html"
        (OUT_DIR / ("%s.%s" % (stem, ext))).write_text(code, encoding="utf-8")
        md = ["# 设计任务: %s" % args.task, "",
              "- 任务类型: %s（%s）" % (task_type, TASK_TYPES[task_type]["label"]),
              "- 判定依据: %s" % basis, "- 相关分类: %s" % ", ".join(categories),
              "- 采用方向: %s" % chosen["name"], ""]
        md += ["## ① 方向说明", ""]
        for k, label in (("idea", "设计理念"), ("style", "视觉风格"), ("color", "色彩体系"),
                         ("type", "排版体系"), ("layout", "布局方式"), ("background", "背景方案"),
                         ("interaction", "交互特点"), ("fits", "适用场景"), ("drawbacks", "潜在缺点")):
            md.append("- %s: %s" % (label, chosen.get(k, "")))
        md += ["", "## ② 检索到的知识（%d 条）" % found["count"]]
        for hit in found["hits"]:
            md.append("- [%s] %s → %s" % (hit.get("level"), (hit.get("title") or "")[:60],
                                          (hit.get("source") or {}).get("url")))
        md += ["", "## ③ Design Tokens", "```css", tokens_to_css(ds), "```"]
        md += ["", "## ④ 对比度实测", "", "| 组合 | 前景 | 背景 | 比值 | AA 正文 | AAA |", "| --- | --- | --- | --- | --- | --- |"]
        for item in ds["contrast"]:
            if item.get("measured"):
                md.append("| %s | %s | %s | %.2f:1 | %s | %s |" % (
                    item["pair"], item["fg"], item["bg"], item["ratio"],
                    "通过" if item["AA_normal"] else "不通过",
                    "通过" if item["AAA_normal"] else "不通过"))
        md += ["", "## ⑤ 审计结果", ""]
        for item in audit["items"]:
            md.append("- **%s** — %s：%s" % (item["item"], item["status"], item["detail"]))
        md += ["", "> 注意：`unmeasured` 不等于通过；本任务未做真实设备渲染与用户测试。"]
        (OUT_DIR / ("%s.md" % stem)).write_text("\n".join(md), encoding="utf-8")
        print("产出:", str(OUT_DIR / ("%s.md" % stem)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
