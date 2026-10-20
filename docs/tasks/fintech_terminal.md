# 设计任务: 审计现有行情页面的视觉与无障碍问题

- 任务类型: fintech_terminal（金融终端）
- 判定依据: 命中关键词 ['行情']
- 相关分类: financial_dashboard, color_system, ui_quality
- 采用方向: Industrial Dense（工业高密度）

## ① 方向说明

- 设计理念: 为高频操作优化，牺牲呼吸感换信息密度与确定性
- 视觉风格: 深灰/蓝灰中性底，细边框分区
- 色彩体系: 低饱和中性色阶 + 状态语义色（涨/跌/警告）
- 排版体系: 系统无衬线，等宽数字用于数值列
- 布局方式: 多栏密集布局，固定表头，紧凑行高
- 背景方案: 无渐变，允许极细分割线
- 交互特点: 即时反馈优先，动效短（≤100ms），避免大位移
- 适用场景: 交易终端、监控台、后台管理系统
- 潜在缺点: 视觉疲劳风险高，长时使用需要降对比选项

## ② 检索到的知识（3 条）
- [L2] Vercel 产品站 · Color Analysis → https://vercel.com/
- [L2] Linear 产品站 · Color Analysis → https://linear.app/
- [L2] Stripe 产品站 · Color Analysis → https://stripe.com/

## ③ Design Tokens
```css
:root {
  --color-bg: #14171c;
  --color-fg: #e6e9ee;
  --color-muted: #9aa3af;
  --color-accent: #4c9aff;
  --color-surface: #1c2027;
  --color-positive: #4ade80;
  --color-negative: #f87171;
  --color-warning: #fbbf24;
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
| 正文/背景 | #e6e9ee | #14171c | 14.76:1 | 通过 | 通过 |
| 次要文字/背景 | #9aa3af | #14171c | 7.04:1 | 通过 | 通过 |
| 强调色/背景 | #4c9aff | #14171c | 6.31:1 | 通过 | 不通过 |
| 正文/卡片面 | #e6e9ee | #1c2027 | 13.42:1 | 通过 | 通过 |
| 涨/正向 | #4ade80 | #14171c | 10.31:1 | 通过 | 通过 |
| 跌/负向 | #f87171 | #14171c | 6.49:1 | 通过 | 不通过 |

## ⑤ 审计结果

- **visual_hierarchy** — pass：字号档位 6 档：12px, 14px, 16px, 20px, 28px, 56px
- **decoration** — pass：阴影 2 处、渐变 0 处
- **consistency** — pass：色值 8 个、字体族 1 种
- **component_language** — pass：圆角档位 2 档: 12, 999
- **background_readability** — pass：正文对比度最低 7.04:1
- **responsive_overflow** — pass：未发现明显固定宽溢出
- **interaction_states** — pass：关键交互状态齐全
- **accessibility** — warn：无 aria 标注（可能缺语义角色）；img alt 覆盖 100%（0/0），aria 属性 0 个
- **motion_performance** — pass：过渡时长 未声明；触发布局动画 0 处
- **design_drift** — pass：非 token 色值 0 个

> 注意：`unmeasured` 不等于通过；本任务未做真实设备渲染与用户测试。