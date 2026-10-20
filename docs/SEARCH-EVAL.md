> **历史报告（Python 时代）**：本文件记录迁移前的实现与实测数据。Python 代码已移除，
> 文中的 `python3 scripts/...` 命令与 `art_uiux/` 路径不再可用；可复现的当前实现见
> [README](../README.md) 与 [MIGRATION-TS](MIGRATION-TS.md)。指标不自动继承到 TS 运行时。

> **已被 `docs/EVAL-REPORT.md` 取代。** 本文件是最早的粗测（只按分类命中计数、无 qrels），
> 保留仅作过程记录，不作为结论依据。

# 语义检索评测

查询数 12 | hit@1 **6/12 (50%)** | hit@3 **6/12 (50%)** | 来源回带 12/12

| 查询 | 期望分类 | 实际 top3 | hit@1 | hit@3 |
| --- | --- | --- | --- | --- |
| text contrast ratio requirement for body copy | color_system | color_system, color_system, ui_quality | ✓ | ✓ |
| touch target minimum size accessibility | ui_quality | uiux_principles, web_ui, android_ui | ✗ | ✗ |
| gradient background performance cost | background_design | background_design, background_design, background_design | ✓ | ✓ |
| design tokens theme customization | design_system | design_system, design_system, design_system | ✓ | ✓ |
| android compose adaptive window size class | android_ui | android_ui, android_ui, android_ui | ✓ | ✓ |
| css grid responsive breakpoints | web_ui | web_ui, web_ui, web_ui | ✓ | ✓ |
| animation duration easing reduced motion | motion_interaction | design_system, color_system, ui_quality | ✗ | ✗ |
| financial dashboard kpi density | financial_dashboard | ui_quality, design_system, ui_quality | ✗ | ✗ |
| game hud skill bar layout | game_ui | game_ui, web_ui, web_ui | ✓ | ✓ |
| svg icon grid stroke rules | visual_assets | web_ui, ui_quality, color_system | ✗ | ✗ |
| visual hierarchy whitespace composition | visual_aesthetics | financial_dashboard, financial_dashboard, color_system | ✗ | ✗ |
| usability heuristic cognitive load | uiux_principles | ui_quality, color_system, color_system | ✗ | ✗ |

> 说明：embedder 是离线特征哈希（512 维），不是神经向量模型；
> 该指标反映的是**当前检索链路**的能力，接入 embedding 服务后需重测。