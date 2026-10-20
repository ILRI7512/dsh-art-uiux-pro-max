#!/usr/bin/env python3
"""真实渲染验证：用 headless Chromium 打开实践页面，量真实布局与计算样式。

这一步补上之前所有「unmeasured」的缺口：
- 真实横向溢出（scrollWidth vs clientWidth）；
- 真实触控目标尺寸（getBoundingClientRect，不是看 CSS 文本）；
- 真实计算色对比度（computed color vs 最近的非透明背景色）；
- 控制台报错。

产物：docs/practice/shots/*.png 与 RENDER.md。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRACTICE = ROOT / "docs" / "practice"
SHOTS = PRACTICE / "shots"

PAGES = ["login", "home", "dashboard", "settings", "dialog", "dual_style"]
VIEWPORTS = [(375, 812, "mobile"), (768, 1024, "tablet"), (1440, 900, "desktop")]

MEASURE_JS = r"""
() => {
  const parse = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x.trim()));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const lum = ({r, g, b}) => {
    const f = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const bgOf = (el) => {
    let node = el;
    while (node) {
      const s = getComputedStyle(node).backgroundColor;
      const c = parse(s);
      if (c && c.a > 0.9) return c;
      node = node.parentElement;
    }
    return { r: 255, g: 255, b: 255, a: 1 };
  };
  const targets = [...document.querySelectorAll('button, a, input, select')].map(el => {
    const r = el.getBoundingClientRect();
    return { tag: el.tagName.toLowerCase(), text: (el.textContent || el.id || '').trim().slice(0, 24),
             w: Math.round(r.width), h: Math.round(r.height) };
  });
  const contrast = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('h1, h2, p, td, th, a, button, label, span')) {
    const txt = (el.textContent || '').trim();
    if (!txt) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const fg = parse(cs.color);
    if (!fg) continue;
    const bg = bgOf(el);
    const L1 = lum(fg), L2 = lum(bg);
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const size = parseFloat(cs.fontSize);
    const bold = parseInt(cs.fontWeight, 10) >= 700;
    const large = size >= 24 || (size >= 18.66 && bold);
    const key = cs.color + '|' + JSON.stringify(bg) + '|' + size;
    if (seen.has(key)) continue;
    seen.add(key);
    contrast.push({ text: txt.slice(0, 30), size, ratio: Math.round(ratio * 100) / 100,
                    large, fg: cs.color, bg: `rgb(${bg.r},${bg.g},${bg.b})` });
  }
  return {
    viewport: { w: innerWidth, h: innerHeight },
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    targets,
    contrast,
    title: document.title,
  };
}
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    pages = [p for p in PAGES if not args.only or p in args.only.split(",")]
    SHOTS.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        for name in pages:
            html_path = PRACTICE / ("%s.html" % name)
            if not html_path.exists():
                print("跳过（不存在）:", html_path.name)
                continue
            for width, height, label in VIEWPORTS:
                ctx = browser.new_context(viewport={"width": width, "height": height},
                                          device_scale_factor=1)
                page = ctx.new_page()
                errors = []
                page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
                page.goto(html_path.as_uri(), wait_until="load")
                metrics = page.evaluate(MEASURE_JS)
                shot = SHOTS / ("%s-%d.png" % (name, width))
                page.screenshot(path=str(shot), full_page=True)
                small = [t for t in metrics["targets"] if t["w"] < 40 or t["h"] < 40]
                fails = [c for c in metrics["contrast"]
                         if c["ratio"] < (3.0 if c["large"] else 4.5)]
                results.append({
                    "page": name, "viewport": label, "size": "%dx%d" % (width, height),
                    "overflow_x": metrics["overflowX"],
                    "targets": len(metrics["targets"]),
                    "targets_below_40": small,
                    "contrast_pairs": len(metrics["contrast"]),
                    "contrast_failures": fails,
                    "console_errors": errors,
                    "screenshot": str(shot.relative_to(ROOT)),
                })
                ctx.close()
                print("%-10s %-7s %4dx%-4d overflow=%d targets<40=%d contrast_fail=%d errors=%d" % (
                    name, label, width, height, metrics["overflowX"], len(small), len(fails), len(errors)))
        browser.close()

    (PRACTICE / "RENDER.json").write_text(json.dumps({"generated_at": now(), "results": results},
                                                     ensure_ascii=False, indent=2), encoding="utf-8")
    total_fail = sum(len(r["contrast_failures"]) for r in results)
    total_overflow = sum(1 for r in results if r["overflow_x"] > 0)
    md = ["# 真实渲染验证（headless Chromium %s）" % "156",
          "", "生成: %s" % now(), "",
          "| 页面 | 视口 | 尺寸 | 横向溢出 | 目标<40px | 对比度失败 | 控制台错误 |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in results:
        md.append("| %s | %s | %s | %d | %d | %d | %d |" % (
            r["page"], r["viewport"], r["size"], r["overflow_x"],
            len(r["targets_below_40"]), len(r["contrast_failures"]), len(r["console_errors"])))
    md += ["", "汇总：对比度失败 %d 处，横向溢出页面 %d 个。" % (total_fail, total_overflow), "",
           "截图见 `docs/practice/shots/`。"]
    if total_fail:
        md += ["", "## 对比度未达标明细", ""]
        for r in results:
            for f in r["contrast_failures"]:
                md.append("- %s @%s：%.2f:1 「%s」" % (r["page"], r["size"], f["ratio"], f["text"]))
    (PRACTICE / "RENDER.md").write_text("\n".join(md), encoding="utf-8")
    print("\n报告:", str(PRACTICE / "RENDER.md"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
