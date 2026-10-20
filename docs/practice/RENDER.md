# 真实渲染验证

## 引擎说明（重要）

- **Chromium 未能启动**：Playwright 的 chrome-headless-shell（arm64, 156.0.8078.4）在本容器（proot）里
  GPU 进程持续崩溃（`GPU process exited unexpectedly: exit_code=5`），试过
  `--disable-gpu / --disable-gpu-sandbox / --in-process-gpu / --single-process / --no-zygote /
  --use-gl=swiftshader / --headless=old` 共 4 组参数组合，全部 `TargetClosed`。
- 已装的系统库：glib / nss / nspr / atk / atk-bridge / cups / drm / xkbcommon / xcomposite / xdamage /
  xfixes / xrandr / gbm / pango / cairo / asound（另修了 apt 源：容器是 arm64，却配了 amd64 的源）。
- **改用 WeasyPrint 70.0**：真实 CSS 排版引擎（无 JS）。它不等于浏览器，渲染差异可能存在，
  所以下面每条结论都标了来源强度。

## 渲染产物

`docs/practice/shots/`：6 个页面 × {375, 1440} 宽度各一张 PNG，另有修复后的 `*-fixed-1.png`。

## 从像素里发现的两个真问题

### 1) 输入框边界对比度 1.10:1（WCAG 1.4.11 要求 ≥3:1）

- 证据：输入框底色 `#14171c` 叠在卡片面 `#1c2027` 上，公式实算 **1.10:1**。
- 截图里表现为：输入框几乎"消失"在卡片里，只剩一个极淡的框线。
- 修复：新增语义 token `--color-border`（工业高密度方向取 `#6b7484`），实算 **3.47:1** 达标；
  同时把这条检查加进 `build_design_system` 的对比度表，四个方向现在都过 1.4.11。
- 修复后截图：`login-375-fixed-1.png`，边界清晰可见。

### 2) 表头在 375px 折行成竖排

- 证据：`dashboard-375-1.png` 里「方向」「手数」被压成两行竖排字。
- 修复：`th{white-space:nowrap}`，`dashboard-375-fixed-1.png` 恢复正常单行。
- 这条只有渲染才看得出来，之前 10 项静态审计全部通过。

## 一条不能当作真问题的观察

首轮截图里「登录 / 忘记密码」两个按钮溢出卡片右侧。加了 `button{width:auto}` 后消失。
**但这可能是 WeasyPrint 的按钮布局差异，不是浏览器里的真实 bug** —— 没有浏览器可用，
我无法确认，所以不把它写进知识库，只记在这里。

## 结论口径

- 这轮让「视觉验证」从 0 变成**有真实像素证据**，但引擎是 WeasyPrint，不是浏览器。
- 因此相关知识的等级仍然停在 L4 的"工程实现验证"，**不升级为浏览器级视觉验证**。
