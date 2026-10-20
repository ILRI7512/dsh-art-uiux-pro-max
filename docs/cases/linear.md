# Design Case: Linear 产品站

- URL: https://linear.app/
- 抓取时间: 2026-10-20T01:28:01Z
- 平台: web
- 技术栈指纹: next.js, react, styled-components

## Case Summary

## Visual Language
- [fact, 置信 1.00] 整体风格判断（如极简/拟物/高对比）依赖视觉主观判断，需人工或视觉模型复核，本工具不下结论

## Layout Analysis
- [fact, 置信 0.80] 检出技术栈指纹: next.js, react, styled-components
- [fact, 置信 0.80] 响应式断点 19 个；容器最大宽度档位: 640px×10, 1280px×4, 1024px×3, 250px×3
- [fact, 置信 0.75] 间距取值高频档位: 8px×46, 6px×9, 12px×5, 4px×5, 11px×4, 0px×2, 40px×1
- [fact, 置信 1.00] 信息重心判断需要真实渲染截图，本工具未做渲染，因此不给结论

## Color Analysis
- [fact, 置信 0.90] 页面出现频次最高的色值: #e2e4e7×429, #e4e5e9×150, #f79ce0×147, #55cdff×89, #9c9da1×74, #08090a×69, #fff×48, #2e2e32×42
- [fact, 置信 0.70] 文本中出现 42 种不同色值（含主题变量与第三方样式）

## Background Analysis
- [fact, 置信 0.85] 渐变出现 4 次、阴影规则 0 条
- [fact, 置信 0.80] 渐变类型分布: linear-gradient×4
- [inference, 置信 0.45] 疑似包含噪点/纹理层（噪声函数或内嵌位图）

## Typography Analysis
- [fact, 置信 0.85] 字体族: var(--font-monospace)×62
- [fact, 置信 0.85] 字号档位: 0.6em×58, 0.9em×58, 16px×2

## Component Analysis
- [fact, 置信 0.80] 圆角档位: 50%×7

## Interaction Analysis
- [fact, 置信 0.80] 过渡/动画声明 302 条，示例: grid-dot-0-0-upDown 2800ms steps(1, end) infinite; grid-dot-0-0-upDown 2800ms steps(1, end) infinite; grid-dot-0-1-upDown 2800ms steps(1, end) infinite; grid-dot-0-1-upDown 2800ms steps(1, end) infinite; grid-dot-0-2-upDown 2800ms steps(1, end) infinite; grid-dot-0-2-upDown 2800ms steps(1, end) infinite; grid-dot-0-3-upDown 2800ms steps(1, end) infinite; grid-dot-0-3-upDown 2800ms steps(1, end) infinite
- [inference, 置信 0.40] 未检出 prefers-reduced-motion 适配（可能在其他样式表）

## Accessibility Analysis
- [fact, 置信 0.85] aria 属性 228 个、role 149 个；img 38 张，其中带 alt 38 张（100%）
- [fact, 置信 1.00] 对比度、焦点顺序、屏幕阅读器表现需要真实渲染与工具检测，本工具未测
- [inference, 置信 0.50] 疑似存在跳转到主内容的 skip link

## Reusable Design Patterns
- 可迁移规则（仅基于事实）：
  - 检出技术栈指纹: next.js, react, styled-components
  - 响应式断点 19 个；容器最大宽度档位: 640px×10, 1280px×4, 1024px×3, 250px×3
  - 间距取值高频档位: 8px×46, 6px×9, 12px×5, 4px×5, 11px×4, 0px×2, 40px×1
  - 信息重心判断需要真实渲染截图，本工具未做渲染，因此不给结论
  - 页面出现频次最高的色值: #e2e4e7×429, #e4e5e9×150, #f79ce0×147, #55cdff×89, #9c9da1×74, #08090a×69, #fff×48, #2e2e32×42
  - 文本中出现 42 种不同色值（含主题变量与第三方样式）
  - 渐变出现 4 次、阴影规则 0 条
  - 渐变类型分布: linear-gradient×4

## Anti-Patterns
- 未检出可判定的反模式；需结合渲染与审计工具复核

## Source and License
- 来源: https://linear.app/
- 许可证说明: 站点内容版权归 Linear；仅归纳公开可访问页面的设计特征
- 版权归原站点所有；本文件仅归纳公开可访问页面的技术特征

## 与现有知识的潜在冲突（未覆盖，仅登记）
- design_system|%：https://ui.shadcn.com/ → 25.0 vs https://linear.app/ → 50.0
- design_system|%：https://ui.shadcn.com/ → 75.0 vs https://linear.app/ → 50.0
- design_system|%：https://ui.shadcn.com/ → 100.0 vs https://linear.app/ → 50.0
- web_ui|px：https://linear.app/ → 640.0 vs https://linear.app/ → 1280.0
- web_ui|px：https://linear.app/ → 640.0 vs https://linear.app/ → 1024.0
- web_ui|px：https://linear.app/ → 640.0 vs https://linear.app/ → 250.0
- web_ui|px：https://linear.app/ → 640.0 vs https://linear.app/ → 8.0
- web_ui|px：https://linear.app/ → 640.0 vs https://linear.app/ → 6.0
- web_ui|px：https://linear.app/ → 640.0 vs https://linear.app/ → 12.0
- web_ui|px：https://linear.app/ → 640.0 vs https://linear.app/ → 4.0
- web_ui|px：https://linear.app/ → 640.0 vs https://linear.app/ → 11.0
- web_ui|px：https://linear.app/ → 640.0 vs https://linear.app/ → 0.0
- web_ui|px：https://linear.app/ → 640.0 vs https://linear.app/ → 40.0
- web_ui|px：https://linear.app/ → 1280.0 vs https://linear.app/ → 640.0
- web_ui|px：https://linear.app/ → 1280.0 vs https://linear.app/ → 1024.0
- web_ui|px：https://linear.app/ → 1280.0 vs https://linear.app/ → 250.0
- web_ui|px：https://linear.app/ → 1280.0 vs https://linear.app/ → 8.0
- web_ui|px：https://linear.app/ → 1280.0 vs https://linear.app/ → 6.0
- web_ui|px：https://linear.app/ → 1280.0 vs https://linear.app/ → 12.0
- web_ui|px：https://linear.app/ → 1280.0 vs https://linear.app/ → 4.0

## 能力边界
- 本分析基于静态 HTML/CSS 文本，未做真实渲染、未采集用户行为数据。
- 视觉美观、可用性、性能、转化率之间没有因果关系，此处不做任何此类推断。