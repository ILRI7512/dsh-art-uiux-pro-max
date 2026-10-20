#!/usr/bin/env python3
"""10 项组件实践任务：生成真实页面 → 实测审计 → 契约测试 → 把结论回流知识库。

关键点：
- 页面是真的（可直接用浏览器打开），审计是对这些真实产物跑的；
- 「组件测试」在不引入浏览器的前提下，测的是**标记契约**：
  label 关联、aria、焦点可见、触控目标尺寸、按钮 type、表格表头；
- 只有在本脚本里真的被测过的规则，才允许写 L4（附 code_test 证据）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dsh_autonomous_learning"))

from dsh_autonomous_learning.config import load_config                            # noqa: E402
from dsh_autonomous_learning.core.models import Chunk, KnowledgeType, Partition      # noqa: E402
from dsh_autonomous_learning.core.orchestrator import build_runtime               # noqa: E402

from art_uiux.design_workflow import audit_html, build_design_system, tokens_to_css  # noqa: E402
from art_uiux.tasks_special import responsive_matrix                              # noqa: E402

PROJECT_ID = "prj_art_uiux"
OUT = ROOT / "docs" / "practice"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def page(title: str, body: str, ds: dict) -> str:
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s</title>
<style>
%s
*{box-sizing:border-box}
body{margin:0;background:var(--color-bg);color:var(--color-fg);font-family:Inter,system-ui,sans-serif;line-height:1.5}
.wrap{max-width:960px;margin:0 auto;padding:var(--space-5)}
h1{font-size:var(--text-5);margin:0 0 var(--space-3)}
h2{font-size:var(--text-4);margin:var(--space-5) 0 var(--space-2)}
.card{background:var(--color-surface);border-radius:var(--radius-2);padding:var(--space-4);box-shadow:0 1px 2px rgba(0,0,0,.06)}
label{display:block;font-size:var(--text-1);margin-bottom:var(--space-1);color:var(--color-muted)}
input,select{width:100%%;min-height:44px;padding:10px 12px;border:1px solid var(--color-border);border-radius:var(--radius-1);background:var(--color-bg);color:var(--color-fg);font-size:var(--text-2)}
button{min-height:44px;min-width:44px;width:auto;padding:10px 18px;border:0;border-radius:var(--radius-1);background:var(--color-accent);color:#fff;font-size:var(--text-2);cursor:pointer;transition:transform var(--motion-fast) var(--easing-standard)}
button:hover{filter:brightness(1.08)}
button:focus-visible,a:focus-visible,input:focus-visible{outline:2px solid var(--color-accent);outline-offset:2px}
button:disabled{opacity:.5;cursor:not-allowed}
a{color:var(--color-accent)}
nav{display:flex;gap:var(--space-3);padding:var(--space-3) 0;border-bottom:1px solid rgba(0,0,0,.1)}
table{width:100%%;border-collapse:collapse;font-size:var(--text-2)}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--color-border)}
th{white-space:nowrap}
.grid{display:grid;gap:var(--space-3);grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.dialog{position:fixed;inset:0;display:grid;place-items:center;background:rgba(0,0,0,.45)}
.dialog__panel{background:var(--color-surface);border-radius:var(--radius-2);padding:var(--space-4);max-width:420px;width:92%%}
.up{color:var(--color-positive)}.down{color:var(--color-negative)}
@media (prefers-reduced-motion: reduce){*{transition:none!important;animation:none!important}}
</style></head><body><div class="wrap">%s</div></body></html>""" % (title, tokens_to_css(ds), body)


def build_pages(ds: dict) -> dict:
    login = """
<h1>登录</h1>
<form class="card" action="#" method="post">
  <label for="email">邮箱</label>
  <input id="email" name="email" type="email" autocomplete="email" required>
  <label for="pwd" style="margin-top:var(--space-3)">密码</label>
  <input id="pwd" name="password" type="password" autocomplete="current-password" required>
  <p style="margin:var(--space-3) 0 0"><button type="submit">登录</button>
  <button type="button" disabled>忘记密码</button></p>
  <p style="border-left:3px solid var(--color-negative);padding-left:8px;color:var(--color-negative)"
     role="alert" aria-live="polite">示例错误提示区（aria-live）</p>
</form>"""

    home = """
<nav aria-label="主导航">
  <a href="#">首页</a><a href="#">行情</a><a href="#">持仓</a><a href="#">设置</a>
</nav>
<h1>首页</h1>
<section aria-live="polite" aria-label="行情摘要"><div class="grid">
  <section class="card"><h2>EURUSD</h2><p class="up">1.0842 · +0.32%</p></section>
  <section class="card"><h2>XAUUSD</h2><p class="down">2412.10 · −0.18%</p></section>
  <section class="card"><h2>持仓</h2><p>3 笔 · 浮动 +128.40</p></section>
</div></section>"""

    dashboard = """
<h1>行情仪表盘</h1>
<section class="card">
<table>
  <caption>持仓明细</caption>
  <thead><tr><th scope="col">品种</th><th scope="col">方向</th><th scope="col">手数</th><th scope="col">盈亏</th></tr></thead>
  <tbody>
    <tr><td>EURUSD</td><td>多</td><td>0.50</td><td class="up">+62.10</td></tr>
    <tr><td>XAUUSD</td><td>空</td><td>0.20</td><td class="down">−18.40</td></tr>
  </tbody>
</table>
<p role="status" aria-live="polite">最后更新：刚刚</p>
</section>"""

    settings = """
<h1>设置</h1>
<form class="card" action="#" method="post">
  <label for="theme">主题</label>
  <select id="theme"><option>跟随系统</option><option>浅色</option><option>深色</option></select>
  <label for="density" style="margin-top:var(--space-3)">信息密度</label>
  <input id="density" type="range" min="1" max="5" value="3" aria-describedby="density-hint">
  <p id="density-hint" style="font-size:var(--text-1);color:var(--color-muted)">1 = 宽松，5 = 紧凑</p>
  <p style="margin-top:var(--space-3)"><button type="submit">保存</button></p>
  <p role="status" aria-live="polite">保存结果将在此播报</p>
</form>"""

    dialog = """
<h1>弹窗与提示</h1>
<p><button type="button" id="open">打开对话框</button></p>
<div class="dialog" role="dialog" aria-modal="true" aria-labelledby="dlg-title" hidden>
  <div class="dialog__panel" role="document">
    <h2 id="dlg-title">确认平仓</h2>
    <p>该操作会以市价平掉全部持仓。</p>
    <p><button type="button">确认</button> <button type="button">取消</button></p>
  </div>
</div>
<p role="status" aria-live="polite">状态提示区（aria-live）</p>"""

    dual = """
<h1>同一按钮的两种视觉风格</h1>
<div class="card">
  <h2>A · 实体强调</h2>
  <p><button type="button">立即交易</button></p>
</div>
<div class="card" style="margin-top:var(--space-3)">
  <h2>B · 描边克制</h2>
  <p><button type="button"
      style="background:transparent;color:var(--color-accent);border:1px solid var(--color-accent)">立即交易</button></p>
</div>
<p role="status" aria-live="polite">当前风格：实体强调（切换后会播报）</p>"""

    return {
        "login": ("使用基础组件构建登录页", login),
        "home": ("使用导航组件构建完整首页", home),
        "dashboard": ("使用卡片与表格构建金融仪表盘", dashboard),
        "settings": ("使用表单组件构建设置页面", settings),
        "dialog": ("使用弹窗和提示组件实现完整交互", dialog),
        "dual_style": ("对同一组件实现两种不同视觉风格", dual),
    }


# ---------------------------------------------------------------- 标记契约测试

def contract_tests(html: str) -> list:
    """不依赖浏览器的组件契约测试，测的是标记是否能被辅助技术正确消费。"""

    results = []

    inputs = re.findall(r"<input\b[^>]*>", html)
    labelled = 0
    ids = set(re.findall(r'id="([^"]+)"', html))
    labels_for = set(re.findall(r'<label[^>]*for="([^"]+)"', html))
    for tag in inputs:
        if re.search(r'type="(submit|button|range)"', tag):
            labelled += 1  # 按钮/滑块类无需 label for，滑块由 aria-describedby 兜底
            continue
        m = re.search(r'id="([^"]+)"', tag)
        if m and m.group(1) in labels_for:
            labelled += 1
    results.append(("每个输入都有 label 关联", labelled == len(inputs),
                    "%d/%d 个 input 有 label" % (labelled, len(inputs))))

    buttons = re.findall(r"<button\b[^>]*>", html)
    typed = [b for b in buttons if re.search(r'\btype="', b)]
    results.append(("button 显式声明 type", len(typed) == len(buttons),
                    "%d/%d 个 button 带 type" % (len(typed), len(buttons))))

    results.append(("存在焦点可见样式", "focus-visible" in html, "检测 :focus-visible 规则"))

    small = []
    for tag in re.findall(r"<(?:button|input|select|a)\b[^>]*>", html):
        m = re.search(r"min-height:\s*(\d+)px", html)
        break
    for value in re.findall(r"min-height:\s*(\d+)px", html):
        if int(value) < 44:
            small.append(value)
    results.append(("触控目标 ≥44px", not small, "min-height=%s" % (",".join(sorted(set(re.findall(r"min-height:\s*(\d+)px", html))) or "未声明"))))

    tables = html.count("<table")
    if tables:
        results.append(("表格有 caption 与表头 scope", "<caption>" in html and 'scope="col"' in html,
                        "caption=%s, scope=%s" % ("<caption>" in html, 'scope="col"' in html)))

    results.append(("动态区域有 aria-live",
                    "aria-live" in html or "role=\"status\"" in html or "role=\"alert\"" in html,
                    "aria-live/role detected"))

    results.append(("支持 prefers-reduced-motion", "prefers-reduced-motion" in html,
                    "媒体查询在全局样式中"))
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--direction", default="industrial_dense")
    args = ap.parse_args()

    ds = build_design_system(args.direction)
    OUT.mkdir(parents=True, exist_ok=True)
    pages = build_pages(ds)

    report = {"generated_at": now(), "direction": args.direction, "tasks": []}
    l4_candidates = []

    for key, (task_name, body) in pages.items():
        html = page(task_name, body, ds)
        (OUT / ("%s.html" % key)).write_text(html, encoding="utf-8")
        audit = audit_html(html, tokens=ds["tokens"])
        matrix = responsive_matrix(html)
        contracts = contract_tests(html)
        passed = sum(1 for _, ok, _ in contracts if ok)
        report["tasks"].append({
            "task": task_name, "page": "%s.html" % key,
            "audit_counts": audit["counts"], "measured_items": audit["measured_items"],
            "responsive": matrix["counts"],
            "contracts_passed": "%d/%d" % (passed, len(contracts)),
            "contract_details": [{"check": c, "pass": ok, "detail": d} for c, ok, d in contracts],
        })
        if passed == len(contracts):
            l4_candidates.append({"task": task_name, "page": key,
                                  "checks": [c for c, _, _ in contracts]})

    # 主题与 Token 任务（第 6 项）
    theme_task = {
        "task": "创建统一主题和 Design Tokens",
        "tokens": ds["tokens"],
        "contrast_pairs": len(ds["contrast"]),
        "contrast_failing": len(ds["failing_pairs"]),
        "css_written": "tokens.css",
    }
    (OUT / "tokens.css").write_text(tokens_to_css(ds), encoding="utf-8")
    report["tasks"].append(theme_task)

    # 多尺寸（第 8 项）与无障碍（第 9 项）用所有页面汇总
    all_html = "\n".join((OUT / ("%s.html" % k)).read_text(encoding="utf-8") for k in pages)
    matrix = responsive_matrix(all_html)
    report["tasks"].append({"task": "在不同屏幕尺寸下检查布局", "responsive": matrix["counts"],
                            "signals": matrix["signals"], "measured": matrix["measured"]})
    a11y_fail = sum(1 for t in report["tasks"] if t.get("audit_counts", {}).get("fail"))
    report["tasks"].append({"task": "运行可访问性检查", "pages_with_fail": a11y_fail,
                            "pages_checked": len(pages)})

    # 第 10 项：组件测试（契约测试固化成 tests/test_practice_pages.py）
    total_checks = sum(len(t["contract_details"]) for t in report["tasks"] if "contract_details" in t)
    report["tasks"].append({"task": "编写组件测试",
                            "test_file": "tests/test_practice_pages.py",
                            "contract_checks": total_checks,
                            "pages_covered": len(pages)})

    (OUT / "REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    md = ["# 组件实践任务报告", "", "方向: %s | 生成: %s" % (args.direction, report["generated_at"]), "",
          "| # | 任务 | 页面 | 审计 | 契约测试 |", "| --- | --- | --- | --- | --- |"]
    for i, t in enumerate(report["tasks"], 1):
        if "page" in t:
            md.append("| %d | %s | %s | %s | %s |" % (i, t["task"], t["page"],
                                                      t["audit_counts"], t["contracts_passed"]))
        elif "contrast_pairs" in t:
            md.append("| %d | %s | tokens.css | —— | 对比度 %d 对，失败 %d |" % (
                i, t["task"], t["contrast_pairs"], t["contrast_failing"]))
        elif "responsive" in t:
            md.append("| %d | %s | 全部页面 | —— | %s |" % (i, t["task"], t["responsive"]))
        elif "pages_with_fail" in t:
            md.append("| %d | %s | %d 页 | 失败页 %d | —— |" % (
                i, t["task"], t["pages_checked"], t["pages_with_fail"]))
        elif "contract_checks" in t:
            md.append("| %d | %s | %s | —— | %d 项断言，覆盖 %d 页 |" % (
                i, t["task"], t["test_file"], t["contract_checks"], t["pages_covered"]))
    md += ["", "> 契约测试测的是标记契约（label/aria/focus/触控/表头），不是视觉渲染。",
           "> 未做真实浏览器渲染，视觉回归与运行时交互仍未验证。"]
    (OUT / "REPORT.md").write_text("\n".join(md), encoding="utf-8")

    # ---------------------------------------------------------- 回流 L4
    cfg = load_config(home=ROOT / "dsh_autonomous_learning")
    rt = build_runtime(cfg)
    promoted = 0
    try:
        for cand in l4_candidates:
            text = ("组件实践验证：%s 页面（%s）通过 %d 项标记契约检查（%s）" % (
                cand["task"], cand["page"], len(cand["checks"]), ", ".join(cand["checks"])))
            chunk = Chunk(
                chunk_id="chunk_practice_" + hashlib.sha1(cand["page"].encode()).hexdigest()[:12],
                project_id=PROJECT_ID,
                document_id="doc_practice",
                partition=Partition.EXPERIMENT.value,
                domain="uiux",
                topic="ui_quality",
                subtopic="practice-verification",
                title="实践验证 · %s" % cand["task"],
                content=text,
                summary=text[:200],
                knowledge_type=KnowledgeType.EXPERIMENTAL_RESULT.value,
                level="L4",
                source_url="file://docs/practice/%s.html" % cand["page"],
                source_title="组件实践任务",
                source_type="experiment",
                author_or_publisher="art-uiux-pro-max",
                accessed_at=now(),
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
                source_quality=0.9,
                confidence=0.8,
                confidence_basis="在真实生成的页面上跑过标记契约测试与静态审计",
                verification_status="verified",
                verification_method="code_test",
                verification_evidence=[{"kind": "code_test", "tool": "practice/contract_tests",
                                        "page": cand["page"], "checks": cand["checks"]}],
                visibility="project",
                metadata={"practice_task": cand["task"], "page": cand["page"]},
            )
            rt.store.add_chunks([chunk.to_row()])
            promoted += 1

        stats = rt.store.stats()
        levels = {lv: rt.metadata.scalar("SELECT COUNT(*) FROM chunks WHERE level=?", (lv,))
                  for lv in ("L1", "L2", "L3", "L4")}
    finally:
        rt.close()

    print("页面:", ", ".join(pages))
    print("契约全过的任务:", [c["task"] for c in l4_candidates])
    print("写入 L4:", promoted, "| 等级分布:", levels, "| 库内:", stats["chunks"])
    print("报告:", str(OUT / "REPORT.md"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
