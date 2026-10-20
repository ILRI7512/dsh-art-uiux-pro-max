#!/usr/bin/env python3
"""跑「三种背景」与「多尺寸布局」两项专项任务，产出报告与代码。"""
from __future__ import annotations
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from art_uiux.tasks_special import generate_backgrounds, responsive_matrix
from art_uiux.design_workflow import build_design_system, tokens_to_css

OUT = ROOT / "docs" / "tasks"

def main() -> int:
    ds = build_design_system("industrial_dense")
    bgs = generate_backgrounds(text_color=ds["tokens"]["color"]["fg"])
    proto = (OUT / "fintech_terminal.html")
    html = proto.read_text(encoding="utf-8") if proto.exists() else ""
    matrix = responsive_matrix(html)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "backgrounds.json").write_text(json.dumps({"backgrounds": bgs}, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "backgrounds.css").write_text("\n\n".join("%s\n%s" % (b["name"], b["css_block"]) for b in bgs), encoding="utf-8")
    md = ["# 三种背景方案（实测对比度）", ""]
    for b in bgs:
        c = b["contrast"]
        md += ["## %s" % b["name"], "", b["idea"], "", "```css", b["css_block"], "```", "",
               "- 对比度（正文 #%s 对最坏背景 %s）：**%.2f:1** → AA %s" % (c["fg"].lstrip("#"), c["bg"], c["ratio"], "通过" if c["AA_normal"] else "不通过"),
               "- 性能代价：%s（%s）" % (b["perf"], b["cost"]),
               "- 结论：%s" % b["note"], ""]
    (OUT / "backgrounds.md").write_text("\n".join(md), encoding="utf-8")

    md2 = ["# 多尺寸布局矩阵", "", "> 静态推断，未做真实设备渲染。", "",
           "| 视口 | 结论 | 依据 |", "| --- | --- | --- |"]
    for r in matrix["rows"]:
        md2.append("| %dpx | %s | %s |" % (r["width"], r["status"], r["detail"]))
    s = matrix["signals"]
    md2 += ["", "## 信号", "",
            "- 固定宽: %s" % (s["fixed_widths"] or "无"),
            "- max-width: %s" % (s["max_widths"] or "无"),
            "- 媒体查询: %d 处" % s["media_queries"],
            "- 触控目标: %s（<44px: %s）" % (s["tap_targets"] or "无", s["tap_targets_below_44"] or "无"),
            "- 小于 12px 字号: %s" % (s["fonts_below_12px"] or "无"),
            "", "> %s" % matrix["note"]]
    (OUT / "responsive.md").write_text("\n".join(md2), encoding="utf-8")
    (OUT / "responsive.json").write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")

    print("背景:")
    for b in bgs:
        print("  %-14s %.2f:1  cost=%s" % (b["key"], b["contrast"]["ratio"], b["cost"]))
    print("多尺寸:", matrix["counts"], "| 断点", matrix["breakpoints"])
    print("触控目标 <44px:", matrix["signals"]["tap_targets_below_44"] or "无")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
