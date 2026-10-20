# Design Case: Finviz 行情与筛选器

- URL: https://finviz.com/
- 抓取时间: 2026-10-20T01:53:02Z
- 平台: web
- 技术栈指纹: react, styled-components

## Case Summary

## Visual Language
- [fact, 置信 1.00] 整体风格判断（如极简/拟物/高对比）依赖视觉主观判断，需人工或视觉模型复核，本工具不下结论

## Layout Analysis
- [fact, 置信 0.80] 检出技术栈指纹: react, styled-components
- [fact, 置信 0.80] 响应式断点 0 个；容器最大宽度档位: 1px×6
- [fact, 置信 0.75] 间距取值高频档位: 4px×19, 2px×12, 20px×2, 278px×1, 8px×1, 115px×1
- [fact, 置信 1.00] 信息重心判断需要真实渲染截图，本工具未做渲染，因此不给结论

## Color Analysis
- [fact, 置信 0.90] 页面出现频次最高的色值: #f0f3fa×38, #398192×2
- [fact, 置信 0.70] 文本中出现 2 种不同色值（含主题变量与第三方样式）

## Background Analysis

## Typography Analysis

## Component Analysis

## Interaction Analysis
- [inference, 置信 0.40] 未检出 prefers-reduced-motion 适配（可能在其他样式表）

## Accessibility Analysis
- [fact, 置信 0.85] aria 属性 4 个、role 0 个；img 53 张，其中带 alt 53 张（100%）
- [fact, 置信 1.00] 对比度、焦点顺序、屏幕阅读器表现需要真实渲染与工具检测，本工具未测

## Reusable Design Patterns
- 可迁移规则（仅基于事实）：
  - 检出技术栈指纹: react, styled-components
  - 响应式断点 0 个；容器最大宽度档位: 1px×6
  - 间距取值高频档位: 4px×19, 2px×12, 20px×2, 278px×1, 8px×1, 115px×1
  - 信息重心判断需要真实渲染截图，本工具未做渲染，因此不给结论
  - 页面出现频次最高的色值: #f0f3fa×38, #398192×2
  - 文本中出现 2 种不同色值（含主题变量与第三方样式）
  - aria 属性 4 个、role 0 个；img 53 张，其中带 alt 53 张（100%）
  - 对比度、焦点顺序、屏幕阅读器表现需要真实渲染与工具检测，本工具未测

## Anti-Patterns
- 未检出可判定的反模式；需结合渲染与审计工具复核

## Source and License
- 来源: https://finviz.com/
- 许可证说明: 站点内容版权归 Finviz；仅归纳公开页面的设计特征
- 版权归原站点所有；本文件仅归纳公开可访问页面的技术特征

## 与现有知识的潜在冲突（未覆盖，仅登记）
- web_ui|px：https://mui.com/material-ui/ → 6.0 vs https://finviz.com/ → 1.0
- web_ui|px：https://mui.com/material-ui/ → 6.0 vs https://finviz.com/ → 4.0
- web_ui|px：https://mui.com/material-ui/ → 6.0 vs https://finviz.com/ → 2.0
- web_ui|px：https://mui.com/material-ui/ → 6.0 vs https://finviz.com/ → 20.0
- web_ui|px：https://mui.com/material-ui/ → 6.0 vs https://finviz.com/ → 278.0
- web_ui|px：https://mui.com/material-ui/ → 6.0 vs https://finviz.com/ → 8.0
- web_ui|px：https://mui.com/material-ui/ → 6.0 vs https://finviz.com/ → 115.0
- web_ui|px：https://finviz.com/ → 1.0 vs https://finviz.com/ → 4.0
- web_ui|px：https://finviz.com/ → 1.0 vs https://finviz.com/ → 2.0
- web_ui|px：https://finviz.com/ → 1.0 vs https://finviz.com/ → 20.0
- web_ui|px：https://finviz.com/ → 1.0 vs https://finviz.com/ → 278.0
- web_ui|px：https://finviz.com/ → 1.0 vs https://finviz.com/ → 8.0
- web_ui|px：https://finviz.com/ → 1.0 vs https://finviz.com/ → 115.0
- web_ui|px：https://finviz.com/ → 4.0 vs https://finviz.com/ → 1.0
- web_ui|px：https://finviz.com/ → 4.0 vs https://finviz.com/ → 2.0
- web_ui|px：https://finviz.com/ → 4.0 vs https://finviz.com/ → 20.0
- web_ui|px：https://finviz.com/ → 4.0 vs https://finviz.com/ → 278.0
- web_ui|px：https://finviz.com/ → 4.0 vs https://finviz.com/ → 8.0
- web_ui|px：https://finviz.com/ → 4.0 vs https://finviz.com/ → 115.0
- web_ui|px：https://finviz.com/ → 2.0 vs https://finviz.com/ → 1.0

## 能力边界
- 本分析基于静态 HTML/CSS 文本，未做真实渲染、未采集用户行为数据。
- 视觉美观、可用性、性能、转化率之间没有因果关系，此处不做任何此类推断。