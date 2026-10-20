# 组件实践任务报告

方向: industrial_dense | 生成: 2026-10-20T02:13:39Z

| # | 任务 | 页面 | 审计 | 契约测试 |
| --- | --- | --- | --- | --- |
| 1 | 使用基础组件构建登录页 | login.html | {'unmeasured': 1, 'pass': 7, 'warn': 2} | 6/6 |
| 2 | 使用导航组件构建完整首页 | home.html | {'unmeasured': 1, 'pass': 7, 'warn': 2} | 6/6 |
| 3 | 使用卡片与表格构建金融仪表盘 | dashboard.html | {'unmeasured': 1, 'pass': 7, 'warn': 2} | 7/7 |
| 4 | 使用表单组件构建设置页面 | settings.html | {'unmeasured': 1, 'pass': 7, 'warn': 2} | 6/6 |
| 5 | 使用弹窗和提示组件实现完整交互 | dialog.html | {'unmeasured': 1, 'pass': 7, 'warn': 2} | 6/6 |
| 6 | 对同一组件实现两种不同视觉风格 | dual_style.html | {'unmeasured': 1, 'pass': 7, 'warn': 2} | 6/6 |
| 7 | 创建统一主题和 Design Tokens | tokens.css | —— | 对比度 7 对，失败 1 |
| 8 | 在不同屏幕尺寸下检查布局 | 全部页面 | —— | {'pass': 6, 'warn': 0, 'fail': 0} |
| 9 | 运行可访问性检查 | 6 页 | 失败页 0 | —— |
| 10 | 编写组件测试 | tests/test_practice_pages.py | —— | 37 项断言，覆盖 6 页 |

> 契约测试测的是标记契约（label/aria/focus/触控/表头），不是视觉渲染。
> 未做真实浏览器渲染，视觉回归与运行时交互仍未验证。