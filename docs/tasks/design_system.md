# 设计任务: 建立一套可复用的设计 Token 系统

- 任务类型: design_system（设计系统）
- 判定依据: 命中关键词 ['token']
- 相关分类: design_system, color_system, ui_quality
- 采用方向: Editorial Light（编辑部留白）

## ① 方向说明

- 设计理念: 以阅读节奏为第一优先级，靠留白与字号对比建立秩序
- 视觉风格: 纸感浅底、低饱和、强排版层级
- 色彩体系: 暖白底 + 近黑字 + 单一强调色（饱和度中等）
- 排版体系: 衬线大标题 + 无衬线正文，字号跨度 3 档以上
- 布局方式: 单栏窄容器，长段落，弱化卡片边界
- 背景方案: 纯色或极轻纸纹，无渐变
- 交互特点: 轻微淡入与下划线反馈，时长 120–180ms
- 适用场景: 内容型站点、品牌官网、长文阅读
- 潜在缺点: 信息密度低，不适合高频操作台

## ② 检索到的知识（4 条）
- [L2] Vercel 产品站 · Color Analysis → https://vercel.com/
- [L2] Linear 产品站 · Color Analysis → https://linear.app/
- [L2] Stripe 产品站 · Color Analysis → https://stripe.com/
- [L1] Start building your app now → https://www.radix-ui.com/

## ③ Design Tokens
```css
:root {
  --color-bg: #faf8f4;
  --color-fg: #15130f;
  --color-muted: #6b6459;
  --color-accent: #8a4b2a;
  --color-surface: #ffffff;
  --color-positive: #1c6b3a;
  --color-negative: #a32118;
  --color-warning: #8a5a00;
  --text-0: 12px;
  --text-1: 14px;
  --text-2: 16px;
  --text-3: 20px;
  --text-4: 28px;
  --text-5: 40px;
  --text-6: 56px;
  --space-0: 4px;
  --space-1: 8px;
  --space-2: 12px;
  --space-3: 16px;
  --space-4: 24px;
  --space-5: 32px;
  --space-6: 48px;
  --space-7: 64px;
  --radius-0: 0px;
  --radius-1: 4px;
  --radius-2: 8px;
  --radius-3: 12px;
  --radius-4: 16px;
  --motion-fast: 120ms;
  --motion-base: 180ms;
  --easing-standard: cubic-bezier(.2,.8,.2,1);
}
```

## ④ 对比度实测

| 组合 | 前景 | 背景 | 比值 | AA 正文 | AAA |
| --- | --- | --- | --- | --- | --- |
| 正文/背景 | #15130f | #faf8f4 | 17.49:1 | 通过 | 通过 |
| 次要文字/背景 | #6b6459 | #faf8f4 | 5.51:1 | 通过 | 不通过 |
| 强调色/背景 | #8a4b2a | #faf8f4 | 6.34:1 | 通过 | 不通过 |
| 正文/卡片面 | #15130f | #ffffff | 18.55:1 | 通过 | 通过 |
| 涨/正向 | #1c6b3a | #faf8f4 | 6.16:1 | 通过 | 不通过 |
| 跌/负向 | #a32118 | #faf8f4 | 7.10:1 | 通过 | 通过 |

## ⑤ 审计结果

- **visual_hierarchy** — pass：字号档位 6 档：12px, 14px, 16px, 20px, 28px, 56px
- **decoration** — pass：阴影 2 处、渐变 0 处
- **consistency** — pass：色值 8 个、字体族 1 种
- **component_language** — pass：圆角档位 2 档: 12, 999
- **background_readability** — pass：正文对比度最低 5.51:1
- **responsive_overflow** — pass：未发现明显固定宽溢出
- **interaction_states** — pass：关键交互状态齐全
- **accessibility** — warn：无 aria 标注（可能缺语义角色）；img alt 覆盖 100%（0/0），aria 属性 0 个
- **motion_performance** — pass：过渡时长 未声明；触发布局动画 0 处
- **design_drift** — pass：非 token 色值 0 个

> 注意：`unmeasured` 不等于通过；本任务未做真实设备渲染与用户测试。