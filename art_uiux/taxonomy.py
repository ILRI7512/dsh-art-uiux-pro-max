"""Art UI/UX Pro Max —— 12 个知识主分类（唯一主分类制）。

与引擎（dsh_autonomous_learning）的关系：
- 引擎的 ``Chunk.partition`` 是**逻辑分区**（general/uiux/finance/...），本项目只写 ``uiux_knowledge`` 与 ``pending_knowledge``；
- 引擎的 ``Chunk.topic`` 是单值字段，本项目把它当**唯一主分类**使用，值域严格限定为本文件的 12 个 key；
- 辅助标签写 ``Chunk.metadata["secondary_categories"]``，允许 0..N 个，但必须与主分类不同。

每个分类都带 12 项元数据：id / 中文名 / 英文名 / 描述 / 包含范围 / 排除范围 /
二级分类 / 检索关键词 / 典型知识类型 / 关联分类 / 入库条件 / 质量要求。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence


@dataclass(frozen=True)
class Category:
    key: str                      # 分类 ID
    label: str                    # 中文名称
    label_en: str                 # 英文名称
    description: str              # 分类描述
    include_scope: Sequence[str]  # 包含范围
    exclude_scope: Sequence[str]  # 排除范围（应归到别处的内容）
    subcategories: Sequence[str]  # 二级分类
    keywords: Sequence[str]       # 推荐检索关键词
    knowledge_types: Sequence[str]  # 典型知识类型（引擎 KnowledgeType 值）
    related: Sequence[str]        # 关联分类
    ingest_conditions: Sequence[str]  # 入库条件
    quality_requirements: Sequence[str]  # 质量要求


CATEGORIES: Dict[str, Category] = {
    "android_ui": Category(
        key="android_ui", label="Android 原生 UI", label_en="Android Native UI",
        description="Jetpack Compose / View 体系的界面构建、布局、主题与平台规范",
        include_scope=["Compose 组合与状态", "Modifier 与布局约束", "窗口尺寸类与自适应",
                       "边到边与系统栏", "Material 3 在 Android 的实现"],
        exclude_scope=["Web 端 MUI 的用法（→ design_system）", "跨平台通用构图（→ visual_aesthetics）"],
        subcategories=["layout", "theme", "adaptive", "system_bars", "components"],
        keywords=("compose", "jetpack", "android", "modifier", "window size class",
                  "edge-to-edge", "scaffold", "remember"),
        knowledge_types=("procedure", "best_practice", "code_example", "principle"),
        related=("design_system", "motion_interaction", "ui_quality"),
        ingest_conditions=["来源为官方文档或可核验的开源仓库",
                           "包含可执行的实现方式（API/组件/参数）",
                           "平台归属明确为 Android"],
        quality_requirements=["L2 起必须有适用场景",
                              "涉及 API 时标注版本或依赖来源",
                              "代码片段需注明来自官方示例还是社区"],
    ),
    "web_ui": Category(
        key="web_ui", label="Web UI", label_en="Web UI",
        description="网页端界面结构、栅格、响应式与浏览器渲染相关的界面实现",
        include_scope=["CSS 布局（grid/flex）", "响应式断点与容器查询", "页面骨架与区块组织",
                       "浏览器渲染相关的界面表现"],
        exclude_scope=["设计 token 体系（→ design_system）", "纯构图美学（→ visual_aesthetics）"],
        subcategories=["layout", "responsive", "css", "page_structure"],
        keywords=("css", "grid", "flex", "responsive", "media query", "container query",
                  "viewport", "html", "layout shift"),
        knowledge_types=("procedure", "code_example", "best_practice"),
        related=("design_system", "ui_quality", "motion_interaction"),
        ingest_conditions=["有可复现的 CSS/HTML 依据", "标注浏览器或规范前提"],
        quality_requirements=["不得只给结论不给实现", "涉及兼容性时说明目标浏览器"],
    ),
    "uiux_principles": Category(
        key="uiux_principles", label="UI/UX 原则", label_en="UI/UX Principles",
        description="可用性启发式、认知负荷、信息架构与交互设计原则",
        include_scope=["启发式评估", "认知负荷与决策成本", "信息架构与导航",
                       "用户操作路径与反馈原则"],
        exclude_scope=["具体视觉手法（→ visual_aesthetics）", "单平台组件 API（→ 对应平台分类）"],
        subcategories=["usability", "cognitive_load", "information_architecture", "feedback"],
        keywords=("heuristic", "usability", "fitts", "hicks", "jakob", "cognitive load",
                  "信息架构", "可用性", "心智模型"),
        knowledge_types=("principle", "concept", "best_practice"),
        related=("ui_quality", "visual_aesthetics"),
        ingest_conditions=["有明确出处（研究/规范/权威机构）", "能区分实证结论与作者观点"],
        quality_requirements=["观点类必须标注为 opinion", "不得把个案推广成普适定律"],
    ),
    "visual_aesthetics": Category(
        key="visual_aesthetics", label="视觉审美与构图", label_en="Visual Aesthetics",
        description="构图、比例、视觉层级、审美判断与风格谱系",
        include_scope=["构图与视觉重心", "留白与节奏", "比例与对齐", "风格谱系与趋势"],
        exclude_scope=["可测量的对比度阈值（→ ui_quality）", "色值体系（→ color_system）"],
        subcategories=["composition", "hierarchy", "spacing", "style_genre"],
        keywords=("composition", "hierarchy", "balance", "whitespace", "rhythm",
                  "构图", "留白", "层级", "对齐"),
        knowledge_types=("principle", "opinion", "case_study"),
        related=("color_system", "background_design", "design_system"),
        ingest_conditions=["区分可测量属性与审美判断", "来源可追溯"],
        quality_requirements=["主观审美不得标记为 L3 以上", "案例类必须附来源链接"],
    ),
    "color_system": Category(
        key="color_system", label="色彩系统", label_en="Color System",
        description="调色板生成、语义色、对比度与暗色模式",
        include_scope=["调色板与色调映射", "语义色命名", "暗色模式策略", "对比度与色差"],
        exclude_scope=["纯视觉效果描述（→ visual_aesthetics）"],
        subcategories=["palette", "semantic_color", "dark_mode", "contrast"],
        keywords=("palette", "tonal", "semantic color", "contrast ratio", "dark mode",
                  "hsl", "oklch", "配色", "对比度"),
        knowledge_types=("definition", "formula", "best_practice"),
        related=("ui_quality", "design_system", "visual_aesthetics"),
        ingest_conditions=["给出具体色值或换算公式", "说明适用背景与场景"],
        quality_requirements=["对比度类必须可复算", "不得凭观感给可访问性结论"],
    ),
    "background_design": Category(
        key="background_design", label="背景 / 渐变 / 光影 / 纹理", label_en="Background & Atmosphere",
        description="渐变、噪点、光晕、程序化背景与材质表现",
        include_scope=["渐变构造", "噪点与纹理", "光晕与景深", "程序化着色器背景"],
        exclude_scope=["文字对比度判据（→ ui_quality）"],
        subcategories=["gradient", "noise_texture", "glow_depth", "procedural"],
        keywords=("gradient", "noise", "glow", "texture", "shader", "blur", "mesh",
                  "渐变", "噪点", "光晕", "纹理"),
        knowledge_types=("procedure", "code_example", "best_practice"),
        related=("color_system", "visual_aesthetics", "motion_interaction"),
        ingest_conditions=["给出实现方式（CSS/GLSL/参数）", "说明性能或设备前提"],
        quality_requirements=["涉及 GPU/模糊时标注性能代价", "不得把素材当自有资产"],
    ),
    "design_system": Category(
        key="design_system", label="组件库与设计系统", label_en="Design System",
        description="token 体系、组件 API 契约、主题扩展与设计-代码映射",
        include_scope=["Design Tokens", "组件 API 与状态", "主题与变体", "设计-代码一致性"],
        exclude_scope=["单页面视觉风格（→ visual_aesthetics）"],
        subcategories=["tokens", "components", "theming", "governance"],
        keywords=("token", "theme", "component", "variant", "design system", "primitive",
                  "组件", "主题", "变量"),
        knowledge_types=("best_practice", "procedure", "code_example", "principle"),
        related=("android_ui", "web_ui", "color_system"),
        ingest_conditions=["有源码或规范文档支撑", "能说明适用范围与版本"],
        quality_requirements=["必须注明库/版本", "不得把单项目约定写成通用标准"],
    ),
    "motion_interaction": Category(
        key="motion_interaction", label="动画与交互", label_en="Motion & Interaction",
        description="过渡、微交互、缓动曲线、手势与动效性能",
        include_scope=["过渡与状态动画", "缓动与时长", "手势与反馈", "动效性能"],
        exclude_scope=["静态排版规则（→ visual_aesthetics）"],
        subcategories=["transition", "easing", "gesture", "micro_interaction", "perf"],
        keywords=("animation", "transition", "easing", "spring", "gesture", "reduced motion",
                  "动效", "缓动", "手势"),
        knowledge_types=("procedure", "best_practice", "code_example"),
        related=("android_ui", "web_ui", "ui_quality"),
        ingest_conditions=["给时长/曲线等可执行参数", "说明触发条件"],
        quality_requirements=["必须考虑 reduced-motion", "涉及性能的主张需标注依据"],
    ),
    "financial_dashboard": Category(
        key="financial_dashboard", label="金融终端 UI", label_en="Financial Dashboard UI",
        description="行情/指标/持仓类高密度界面的信息层级、语义色与实时性表现",
        include_scope=["KPI 与数值层级", "行情/图表呈现", "涨跌语义色", "高密度表格与实时刷新"],
        exclude_scope=["通用表单组件（→ design_system）"],
        subcategories=["kpi", "charts", "semantic_numbers", "dense_tables", "realtime"],
        keywords=("dashboard", "kpi", "candlestick", "order book", "ticker", "sparkline",
                  "仪表盘", "行情", "持仓"),
        knowledge_types=("best_practice", "procedure", "case_study"),
        related=("design_system", "color_system", "ui_quality"),
        ingest_conditions=["有真实产品或公开案例支撑", "标注数据密度前提"],
        quality_requirements=["不得伪造收益/转化数据", "实时性主张需说明刷新机制"],
    ),
    "game_ui": Category(
        key="game_ui", label="游戏 UI", label_en="Game UI",
        description="HUD、技能栏、关卡界面与游戏化交互的视觉与信息设计",
        include_scope=["HUD 信息布局", "状态与资源指示", "菜单与背包", "游戏化反馈"],
        exclude_scope=["业务流程后台（→ web_ui）"],
        subcategories=["hud", "inventory", "menus", "feedback"],
        keywords=("hud", "inventory", "skill bar", "game ui", "overlay", "cooldown",
                  "游戏", "技能栏", "背包"),
        knowledge_types=("best_practice", "case_study", "principle"),
        related=("motion_interaction", "visual_aesthetics"),
        ingest_conditions=["有可核验的游戏或公开案例", "说明平台与分辨率前提"],
        quality_requirements=["区分主机/移动端约束", "不得把美术风格当可用性结论"],
    ),
    "visual_assets": Category(
        key="visual_assets", label="视觉素材与矢量", label_en="Visual Assets",
        description="图标、插画、SVG/滤镜等素材与规范的工程化使用",
        include_scope=["SVG 与滤镜", "图标体系", "插画使用规范", "素材工程化（体积/清晰度）"],
        exclude_scope=["页面构图（→ visual_aesthetics）"],
        subcategories=["svg", "icons", "illustration", "filters", "optimization"],
        keywords=("svg", "icon", "illustration", "filter", "viewbox", "optimize",
                  "图标", "插画", "素材"),
        knowledge_types=("definition", "procedure", "code_example"),
        related=("background_design", "design_system"),
        ingest_conditions=["附许可证信息", "给出可复用的技术做法"],
        quality_requirements=["必须记录来源与许可", "不得直接收录他人素材本体"],
    ),
    "ui_quality": Category(
        key="ui_quality", label="可访问性与视觉质量审计", label_en="Accessibility & UI Quality",
        description="WCAG 判据、对比度、焦点、性能指标与可执行的审计清单",
        include_scope=["WCAG 条款与判据", "对比度与焦点可见", "触控目标尺寸",
                       "布局溢出与视觉回归", "性能指标（CLS/LCP）"],
        exclude_scope=["审美评价（→ visual_aesthetics）"],
        subcategories=["wcag", "contrast", "focus", "touch_target", "layout_overflow", "perf"],
        keywords=("wcag", "contrast", "focus", "aria", "lighthouse", "cls", "a11y",
                  "无障碍", "审计", "溢出"),
        knowledge_types=("principle", "procedure", "warning", "best_practice"),
        related=("color_system", "web_ui", "android_ui"),
        ingest_conditions=["判据可测量或可测试", "标注等级（A/AA/AAA）或指标阈值"],
        quality_requirements=["必须给出可执行检查而非泛泛而谈", "未实测不得声称达标"],
    ),
}

CATEGORY_KEYS: List[str] = list(CATEGORIES)


class TaxonomyError(ValueError):
    """分类校验失败。"""


def get_category(key: str) -> Category:
    if key not in CATEGORIES:
        raise TaxonomyError("未知主分类 %r，允许值: %s" % (key, ", ".join(CATEGORY_KEYS)))
    return CATEGORIES[key]


def validate_assignment(primary: str, secondary: Sequence[str] = ()) -> List[str]:
    """校验一条知识的主/辅分类，返回去重后的辅助标签。

    规则：必须有且仅有一个主分类；辅助标签不得与主分类重复且必须是已知分类；
    只做标签，不复制内容。
    """

    get_category(primary)
    seen, cleaned = set(), []
    for item in secondary or ():
        if not isinstance(item, str):
            raise TaxonomyError("辅助分类必须是字符串，收到 %r" % (item,))
        key = item.strip()
        if not key:
            continue
        if key == primary:
            raise TaxonomyError("辅助分类不能与主分类相同（%s）" % key)
        get_category(key)
        if key not in seen:
            seen.add(key)
            cleaned.append(key)
    return cleaned


#: 每个知识单元必须落地的提取字段（需求六）。
EXTRACTION_FIELDS = (
    "core_principle", "applicable_context", "visual_pattern", "layout_rule",
    "color_rule", "typography_rule", "background_method", "component_spec",
    "interaction_rule", "implementation", "anti_pattern", "performance_note",
    "a11y_requirement", "source_ref", "license_note", "evidence_level",
)

EXTRACTION_MINIMUM = ("core_principle", "applicable_context", "source_ref", "evidence_level")


def describe_taxonomy() -> Dict[str, object]:
    return {
        "primary_keys": CATEGORY_KEYS,
        "categories": [
            {
                "key": c.key, "label": c.label, "label_en": c.label_en,
                "description": c.description,
                "include_scope": list(c.include_scope),
                "exclude_scope": list(c.exclude_scope),
                "subcategories": list(c.subcategories),
                "keywords": list(c.keywords),
                "knowledge_types": list(c.knowledge_types),
                "related": list(c.related),
                "ingest_conditions": list(c.ingest_conditions),
                "quality_requirements": list(c.quality_requirements),
            }
            for c in CATEGORIES.values()
        ],
        "extraction_fields": list(EXTRACTION_FIELDS),
        "extraction_minimum": list(EXTRACTION_MINIMUM),
    }
