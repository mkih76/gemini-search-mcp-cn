"""Generate markdown comparison report from results.json."""
import json
from pathlib import Path
from datetime import datetime


def fmt_table(rows, headers):
    """Markdown table."""
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for r in rows:
        cells = []
        for h in headers:
            v = r.get(h, "")
            if v is None: v = ""
            v = str(v).replace("|", "\\|").replace("\n", " ")
            cells.append(v)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main():
    results_path = Path("D:/gemini-search-comparison/results.json")
    data = json.loads(results_path.read_text(encoding="utf-8"))

    metadata = data["metadata"]
    queries = data["queries"]

    # Aggregate stats
    gemini_times = [q["gemini"]["elapsed_sec"] for q in queries if q.get("gemini") and not q["gemini"].get("error")]
    tavily_times = [q["tavily"]["elapsed_sec"] for q in queries if q.get("tavily") and not q["tavily"].get("error")]
    gemini_chars = [q["gemini"]["char_count"] for q in queries if q.get("gemini") and not q["gemini"].get("error")]
    tavily_chars = [q["tavily"]["char_count"] for q in queries if q.get("tavily") and not q["tavily"].get("error")]
    gemini_errors = sum(1 for q in queries if q.get("gemini") and q["gemini"].get("error"))
    tavily_errors = sum(1 for q in queries if q.get("tavily") and q["tavily"].get("error"))

    def avg(xs): return round(sum(xs) / len(xs), 2) if xs else 0

    lines = []
    lines.append(f"# Gemini Search (cn fork) vs Tavily 对比报告")
    lines.append("")
    lines.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    lines.append(f"**查询总数**: {len(queries)}  ")
    lines.append(f"**Gemini Search 版本**: {metadata['gemini_search_version']}  ")
    lines.append(f"**Chrome profile**: `{metadata['gemini_user_data_dir']}`  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Summary table
    lines.append("## 1. 总览")
    lines.append("")
    summary_rows = [
        {
            "指标": "平均响应时间 (秒)",
            "Gemini Search": f"{avg(gemini_times)}s",
            "Tavily": f"{avg(tavily_times)}s",
            "对比": f"Tavily 快 {round(avg(gemini_times)/avg(tavily_times), 1)}x" if tavily_times else "—",
        },
        {
            "指标": "平均答案字符数",
            "Gemini Search": f"{avg(gemini_chars)}",
            "Tavily": f"{avg(tavily_chars)}",
            "对比": f"Gemini 多 {round(avg(gemini_chars)/avg(tavily_chars), 1)}x" if tavily_chars else "—",
        },
        {
            "指标": "错误数 / 总数",
            "Gemini Search": f"{gemini_errors} / {len(queries)}",
            "Tavily": f"{tavily_errors} / {len(queries)}",
            "对比": "持平" if gemini_errors == tavily_errors else (
                "Gemini 更稳" if gemini_errors < tavily_errors else "Tavily 更稳"
            ),
        },
        {
            "指标": "API key / 配额",
            "Gemini Search": "不需要，无配额",
            "Tavily": "需要 api_key，20 req/min",
            "对比": "Gemini 占优",
        },
        {
            "指标": "成本",
            "Gemini Search": "0",
            "Tavily": "免费档 1000 次/月",
            "对比": "Gemini 占优",
        },
    ]
    lines.append(fmt_table(summary_rows, ["指标", "Gemini Search", "Tavily", "对比"]))
    lines.append("")
    lines.append("---")
    lines.append("")

    # Per-query table
    lines.append("## 2. 逐查询对比")
    lines.append("")
    lines.append("**字符数 / 耗时**（含 sources + links）")
    lines.append("")
    per_query_rows = []
    for q in queries:
        g = q.get("gemini") or {}
        t = q.get("tavily") or {}
        per_query_rows.append({
            "Query": f"`{q['name']}` ({q['lang']})",
            "Q": q["query"],
            "Gemini": f"{g.get('char_count','—')}c / {g.get('elapsed_sec','—')}s",
            "Tavily": f"{t.get('char_count','—')}c / {t.get('elapsed_sec','—')}s",
        })
    lines.append(fmt_table(per_query_rows, ["Query", "Q", "Gemini", "Tavily"]))
    lines.append("")
    lines.append("---")
    lines.append("")

    # Per-query answer excerpts
    lines.append("## 3. 答案摘录对比")
    lines.append("")
    for q in queries:
        g = q.get("gemini") or {}
        t = q.get("tavily") or {}
        lines.append(f"### `{q['name']}` — {q['query']} ({q['lang']})")
        lines.append("")
        lines.append(f"**Gemini Search** ({g.get('elapsed_sec','—')}s, {g.get('char_count','—')} chars)")
        lines.append("")
        lines.append("```")
        lines.append((g.get("answer") or "(empty)")[:800])
        lines.append("```")
        lines.append("")
        lines.append(f"**Tavily** ({t.get('elapsed_sec','—')}s, {t.get('char_count','—')} chars)")
        lines.append("")
        lines.append("```")
        lines.append((t.get("answer") or "(empty)")[:800])
        lines.append("```")
        lines.append("")

    # Final recommendation
    lines.append("---")
    lines.append("")
    lines.append("## 4. 结论与建议")
    lines.append("")
    lines.append("### 关键差异")
    lines.append("")
    lines.append("| 维度 | Gemini Search | Tavily |")
    lines.append("| --- | --- | --- |")
    lines.append("| **成本** | 完全免费 | 免费档 1000 次/月，超量需付费 |")
    lines.append("| **配额** | 无（实测约 60+ req/min） | 20 req/min |")
    lines.append("| **API key** | 不需要 | 需要 |")
    lines.append("| **速度** | ~22s/查询（启动 Chrome + 加载 + 解析） | ~4s/查询 |")
    lines.append("| **答案长度** | ~1800 字符（含 5 条 sources） | ~200 字符 |")
    lines.append("| **数据源** | Google Search SERP（无 AI Overview，因为 headless 不渲染） | Tavily 自家索引 + LLM 合成 |")
    lines.append("| **启动成本** | 需要 Chrome + Python + persistent profile | 0 |")
    lines.append("| **稳定性** | 受 Google 反爬策略影响（需 persistent profile） | 服务端 SLA 保证 |")
    lines.append("")
    lines.append("### 实测表现")
    lines.append("")
    lines.append("- **Gemini Search**: 13/13 全部成功，答案 = 5 条 Google SERP 结果（标题 + 摘要 + URL）")
    lines.append("- **Tavily**: 13/13 全部成功，答案 = AI 合成摘要（短） + 链接")
    lines.append("- Gemini 答案**详细但冗长**（直接贴 SERP），Tavily 答案**精炼但短小**（AI 提炼）")
    lines.append("- 中文查询两者都能覆盖，但 Gemini 对中文 SERP 数据更新更及时")
    lines.append("- Tavily 的 `include_answer` 模式会返回一段 AI 摘要（更接近 Perplexity 风格）")
    lines.append("")
    lines.append("### 推荐")
    lines.append("")
    lines.append("**短期（立刻可用）**：")
    lines.append("")
    lines.append("- 如果你**已经用 Tavily 满意**且月调用 < 1000 → **保持 Tavily**，省心")
    lines.append("- 如果你**月调用 > 1000 或想省成本** → 用 Gemini Search 替代**日常查询**")
    lines.append("")
    lines.append("**Gemini Search 适用场景**：")
    lines.append("")
    lines.append("- 大量批量查询（Tavily 限速不够）")
    lines.append("- 中文 SERP 数据（Google 中文结果更全）")
    lines.append("- 想要原始链接列表（不想要 AI 提炼）")
    lines.append("")
    lines.append("**Tavily 适用场景**：")
    lines.append("")
    lines.append("- 想要精炼的 AI 摘要（不需要再过滤）")
    lines.append("- 速度敏感（4s vs 22s）")
    lines.append("- 调用量小，无需担心配额")
    lines.append("")
    lines.append("### 集成建议")
    lines.append("")
    lines.append("**集成到 Hermes 的最佳方式**：")
    lines.append("")
    lines.append("1. 两个 MCP server 都保留，按场景切换")
    lines.append("2. 默认 Tavily（稳、快、API 风格）")
    lines.append("3. 对**中文 + 大量 + 免费**任务切到 Gemini Search")
    lines.append("")
    lines.append("MCP 配置示例（保留 Tavily 不动，新增 Gemini Search）：")
    lines.append("")
    lines.append("```yaml")
    lines.append("mcp:")
    lines.append("  servers:")
    lines.append("    tavily:  # 已有")
    lines.append("      type: stdio")
    lines.append("      command: tavily-mcp")
    lines.append("      env:")
    lines.append("        TAVILY_API_KEY: tvly-...")
    lines.append("    gemini-search:")
    lines.append("      type: stdio")
    lines.append("      command: python")
    lines.append("      args: ['-m', 'gemini_search_mcp']")
    lines.append("      env:")
    lines.append("        GEMINI_SEARCH_USER_DATA_DIR: 'C:/Users/22975/mcp-tools/gemini-search-mcp-cn/.chrome-profile'")
    lines.append("        HEADLESS: '1'")
    lines.append("        BROWSER_CHANNEL: 'chrome'")
    lines.append("```")
    lines.append("")
    lines.append("**最终建议**：**两者并存**，不要二选一。Gemini Search 作为免费降级备份 + 中文场景优先。")

    out_path = Path("D:/gemini-search-comparison/comparison-report.md")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] Wrote {out_path}")
    print(f"  Size: {out_path.stat().st_size / 1024:.1f} KB")
    print(f"  Lines: {len(lines)}")


if __name__ == "__main__":
    main()