"""DSH 自主学习与知识进化插件（Python 引擎 + MCP 接入）。

包结构遵循规范第三节的模块划分，但按实际规模做了适度合并：

- config.py            配置系统（默认值 + 校验 + 环境变量覆盖）
- core/                编排、规划、缺口分析、评估、状态机、预算、模型/嵌入适配
- sources/             资料发现、读取、解析、元数据
- knowledge/           提取、分类、核验、去重、冲突、版本、知识关系、分区
- storage/             SQLite 元数据、向量知识库、文件存储、备份
- practice/            练习任务、受限代码执行、实验
- security/            权限、执行策略、审计
- tools/               对外工具注册表与四组工具实现
- plugin.py            MCP stdio 服务器（DSH 通过 dsh-mcp-connector 接入）
- main.py              本地 CLI（init / learn / search / verify / report / serve）
"""

__version__ = "1.0.0"
__all__ = ["__version__"]
