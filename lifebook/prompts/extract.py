"""Extraction prompts and tool schemas for executor."""
from __future__ import annotations

from typing import Any

from ..config import DEFAULT_CATEGORIES

EXTRACT_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "笔记标题，简洁、具体，不超过 40 字。",
        },
        "summary": {
            "type": "string",
            "description": "一句话概括这篇内容的核心主张或信息。",
        },
        "key_points": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-7 条结构化要点，每条一句话，覆盖原文主要信息。",
        },
        "narrative": {
            "type": "string",
            "description": "加工后的可读 Markdown 正文，段落连贯，保留原文关键事实和数据，可含小标题。",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "2-4 个标签。必须遵守 Obsidian 标签语法：仅含中文/英文/数字/连字符"
                "（-）/下划线（_），禁止空格、点号、引号、括号、斜杠等任何其他标点。"
                "不带 # 号。至少包含一个内容性质类标签，从以下白名单中选：资讯、趣闻、"
                "教程、观点、深度分析、参考文档、工具介绍、案例研究。其余为主题标签，"
                "避免过于宽泛（如\"技术\"）。反例：\"Node.js SDK\"（含空格和点）应写作"
                "\"NodeJS-SDK\"；\"API调用\"合法。"
            ),
            "minItems": 2,
            "maxItems": 4,
        },
        "category": {
            "type": "string",
            "enum": DEFAULT_CATEGORIES,
            "description": (
                "归档目录名，必须严格从枚举值中选一个。唯一维度是**主题领域/行业/学科**。"
                "边界优先级（遇到模糊主题时按此决策）："
                "(1) AI 公司商业新闻（融资/高管变动/定价策略/商业模式分析/订阅模式/封号风波）"
                "→ 经济与产业；AI 技术本身（模型发布/算法/工程实践/产品功能/SDK）→ AI技术。"
                "判断方法：问「去掉 AI 这个词，文章还成立吗？」如果主线是商业/管理/市场/"
                "公司战略，就算提到了 AI 也归经济与产业。"
                "(2) 硬件产品发布/技术/参数 → 消费电子。"
                "(3) AI 监管/平台监管/数据合规/未成年人保护 → 科技监管，不分散到具体领域。"
                "(4) 芯片设计/制造/封装/存储统一归 半导体。"
                "(5) CAD/建模库主线是'Python 库/SDK/API' → 开发者工具。"
                "(6) 职场/劳动争议/工会/罢工 → 组织与劳动；管理实践/领导力/创业经验 → 组织与劳动。"
                "(7) 媒体平台/内容分发/营销策略 → 媒体生态。"
                "(8) 宏观产业分析/消费降级/平台经济 → 经济与产业。"
                "反例：「OpenAI 高管离职」→ 经济与产业（高管变动是公司治理）；"
                "「Claude 订阅涨价」→ 经济与产业（定价是商业决策）；"
                "「某公司用 AI 裁员」→ 组织与劳动（主线是组织变革）。"
            ),
        },
        "related_keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-8 个用于查找相关笔记的关键词（人名、技术名、概念名等）。",
        },
        "confidence": {
            "type": "number",
            "description": "0-1，表示你对分类和要点抽取的置信度。",
            "minimum": 0,
            "maximum": 1,
        },
        "alt_category": {
            "type": "string",
            "enum": DEFAULT_CATEGORIES,
            "description": (
                "第二候选分类。当 confidence < 0.8 时必须提供，表示你认为"
                "第二可能的分类。confidence >= 0.8 时可省略。"
            ),
        },
    },
    "required": ["title", "summary", "key_points", "narrative", "tags", "category",
                 "related_keywords", "confidence"],
}


EXTRACT_SYSTEM = """你是一位严谨的知识库编辑。你的任务是把一篇原始素材加工成结构化的主题笔记。

分类与标签的分野（重要）：
- category 固定为 {cat_count} 选一的枚举：{cat_list}。必须严格从这个列表里选一个，
  不得新建、不得改名、不得合并。
- 边界优先级（遇到模糊主题时按此决策）：
  * AI 公司商业新闻（融资/高管变动/定价策略/商业模式/订阅模式/封号风波）
    → 经济与产业；AI 技术本身（模型发布/算法/工程实践/产品功能/SDK）
    → AI技术。判断方法：问「去掉 AI 这个词，文章还成立吗？」如果主线是
    商业/管理/市场/公司战略，就算提到了 AI 也归经济与产业。
  * 硬件产品发布/技术/参数 → 消费电子
  * AI 监管/平台监管/数据合规/未成年人保护 → 科技监管（不散到具体领域）
  * 芯片设计/制造/封装/存储 → 半导体
  * CAD/建模库主线是"Python 库/SDK/API" → 开发者工具
  * 职场/劳动争议/工会/罢工/管理实践/领导力/创业经验 → 组织与劳动
  * 媒体平台/内容分发/营销策略 → 媒体生态
  * 宏观产业分析/消费降级/平台经济 → 经济与产业
  * 反例：「OpenAI 高管离职」→ 经济与产业（高管变动是公司治理，不是技术）；
    「Claude 订阅涨价」→ 经济与产业（定价是商业决策）；
    「某公司用 AI 裁员」→ 组织与劳动（主线是组织变革）
- tag 承担其余所有维度：内容性质（资讯/教程/趣闻等）、具体主体（人名/
  产品名/概念名）、交叉领域。一篇笔记可以有多个 tag。
- 当 confidence < 0.8 时，必须在 alt_category 中记录第二候选分类，方便后续
  人工审核。confidence >= 0.8 时可省略 alt_category。

要求：
1. 保留原文核心事实、数据、论点，不虚构。
2. narrative 必须是可读的中文 Markdown 正文，不是 JSON 或列表堆叠。
3. key_points 是对 narrative 的高密度提炼，用于后续检索和关联。
4. 如果原文语言是英文，narrative 用中文改写，但保留专有名词原文。
5. category 严格从枚举中选。
6. tags 必须严格遵守 Obsidian 语法：仅含中文/英文/数字/连字符/下划线，
   禁止空格和任何标点。含空格或点号的词要改写（"Node.js SDK" → "NodeJS-SDK"）。
7. tags 中必须至少有一个内容性质类标签（资讯/趣闻/教程/观点/深度分析/
   参考文档/工具介绍/案例研究），方便按阅读场景过滤。
8. tags 不得与 category 同名（避免信息重复）。例如 category=AI技术 时，
   tag 里不要再出现"AI技术"，应选更具体的主体/交叉领域词。

文体硬性要求（narrative 正文必须遵守，违反任何一条都视为失败）：
A. 禁用 emoji 和装饰符号。标题和正文不得出现 ⚙️🧠🚀💡✅🔥✨📌🎯 等任何
   表情符号或装饰字符。
B. narrative 不得以 H1（# 标题）重复笔记 title。可直接从内容起笔，或使用
   H2（##）分节。
C. 禁用过渡句、铺垫句、总结收尾段。例如"以下是..."、"综上所述"、
   "总的来说"、"这套方案为...提供了完整路径"、"可根据具体场景灵活选择"
   等套话一律删除。
D. bold 仅用于关键数值或专有名词。同一段落内 **...** 最多出现 2 处。
E. narrative 必须承载 key_points 之外的新信息（机制、原理、适用场景、
   局限性、对比、来源背景等）。如果原文信息量不足以支撑正文新增内容，
   narrative 留空或极简，不要用话术凑字数重复 key_points。
F. 原文出现的具体数值、版本号、日期、百分比必须原样保留。禁止弱化为
   "约"、"通常"、"大致"、"可能"。原文是 40% 就写 40%，不要改成"约 40%"。
G. 列表项末尾不加句号。"名称：说明"格式使用全角冒号"："。
H. 所有引号一律使用直角引号「」（嵌套时外层「」内层『』）。禁止使用
   弯引号 " " ' '，也禁止使用直引号 " '。
I. 禁用无意义的连接词和套话：此外、另外、值得一提的是、需要注意的是、
   总的来说、综上、简而言之、不难看出、由此可见。需要衔接时直接陈述
   下一个事实。
J. 禁止使用破折号 — 或 ——。需要补充说明就另起一句，或用半角括号（）。"""


def build_extract_tool_schema(categories: list[str]) -> dict[str, Any]:
    """Build EXTRACT_TOOL_SCHEMA with a dynamic category enum."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "title": EXTRACT_TOOL_SCHEMA["properties"]["title"],
            "summary": EXTRACT_TOOL_SCHEMA["properties"]["summary"],
            "key_points": EXTRACT_TOOL_SCHEMA["properties"]["key_points"],
            "narrative": EXTRACT_TOOL_SCHEMA["properties"]["narrative"],
            "tags": EXTRACT_TOOL_SCHEMA["properties"]["tags"],
            "category": {
                "type": "string",
                "enum": categories,
                "description": EXTRACT_TOOL_SCHEMA["properties"]["category"]["description"],
            },
            "related_keywords": EXTRACT_TOOL_SCHEMA["properties"]["related_keywords"],
            "confidence": EXTRACT_TOOL_SCHEMA["properties"]["confidence"],
            "alt_category": {
                "type": "string",
                "enum": categories,
                "description": EXTRACT_TOOL_SCHEMA["properties"]["alt_category"]["description"],
            },
        },
        "required": list(EXTRACT_TOOL_SCHEMA["required"]),
    }
    return schema


def build_extract_system(categories: list[str]) -> str:
    """Build EXTRACT_SYSTEM with a dynamic category list."""
    cat_list = "、".join(categories)
    cat_count = len(categories)
    return EXTRACT_SYSTEM.format(cat_list=cat_list, cat_count=cat_count)
