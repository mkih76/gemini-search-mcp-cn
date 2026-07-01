"""Comparison queries for Gemini Search (cn fork) vs Tavily.

Categories: 实时数据 / 中文政策 / 财经 / 学术 / 英文新闻 / 通用事实
"""
QUERIES = [
    # Real-time data
    ("realtime_btc", "Bitcoin price today in USD", "en"),
    ("realtime_weather", "Beijing weather today forecast", "en"),

    # Chinese policy
    ("cn_policy_tax", "2026年个人所得税最新政策变化", "zh"),
    ("cn_policy_housing", "2026年房地产契税新政策", "zh"),

    # Finance
    ("finance_gold", "Gold price today USD per ounce", "en"),
    ("finance_stock", "NVIDIA stock price today", "en"),

    # Academic / technical
    ("academic_climate", "global average temperature increase 2025 compared to pre-industrial", "en"),
    ("academic_quantum", "explain quantum entanglement simply", "en"),

    # English news
    ("news_ai_regulation", "EU AI Act enforcement latest news 2026", "en"),
    ("news_china_economy", "China GDP growth latest quarterly data 2026", "en"),

    # General knowledge
    ("gk_math", "what is 47 * 89", "en"),
    ("gk_capital", "capital of Australia", "en"),

    # Chinese general
    ("zh_gk", "2025年诺贝尔物理学奖获得者是谁", "zh"),
]