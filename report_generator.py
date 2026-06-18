from datetime import datetime
from typing import Optional, List, Dict
import os
import json

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.columns import Columns

from models import (
    AnalysisResult, SentimentType, MeetingMinutes,
    MeetingMinutesItem, TrackingIssue, InterviewDirection,
    ComplaintDetail, VolumeTrendPoint, BatchComparisonResult,
    BrandComparisonRow
)
from analyzer import Analyzer


console = Console()


class ReportGenerator:
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.datetime_format = self.config.get("output", {}).get("datetime_format", "%Y-%m-%d %H:%M")

    def _sentiment_label(self, sentiment: SentimentType) -> Text:
        mapping = {
            SentimentType.POSITIVE: ("正面", "green"),
            SentimentType.NEGATIVE: ("负面", "red"),
            SentimentType.NEUTRAL: ("中性", "yellow"),
            SentimentType.QUESTION: ("疑问", "cyan"),
        }
        label, color = mapping.get(sentiment, ("未知", "white"))
        return Text(label, style=f"bold {color}")

    def _change_arrow(self, value: float, positive_good: bool = True) -> str:
        if value > 0.5:
            style = "bold green" if positive_good else "bold red"
            return f"[{style}]↑ {value:+.1f}%[/{style}]"
        elif value < -0.5:
            style = "bold red" if positive_good else "bold green"
            return f"[{style}]↓ {value:+.1f}%[/{style}]"
        return f"[bold yellow]→ {value:+.1f}%[/bold yellow]"

    def _make_bar(self, ratio: float, width: int = 20, positive: bool = False) -> str:
        ratio = max(0.0, min(1.0, ratio))
        filled = int(width * ratio)
        bar_char = "█"
        empty_char = "░"
        color_start = "[green]" if positive else "[red]"
        color_end = "[/green]" if positive else "[/red]"
        return f"{color_start}{bar_char * filled}{color_end}{empty_char * (width - filled)}"

    def print_header(self, result: AnalysisResult):
        params = result.query_params
        lines = []
        lines.append(f"[bold magenta]目标品牌:[/bold magenta] {params.target_brand}")
        if params.competing_brands:
            lines.append(f"[bold magenta]对比竞品:[/bold magenta] {', '.join(params.competing_brands)}")
        if params.time_range:
            lines.append(f"[bold magenta]时间范围:[/bold magenta] {params.time_range}")
        if params.focus_themes:
            lines.append(f"[bold magenta]关注主题:[/bold magenta] {', '.join(params.focus_themes)}")
        lines.append(f"[dim]生成时间: {result.generated_at.strftime(self.datetime_format)}[/dim]")
        content = "\n".join(lines)
        console.print(Panel(content, title="[bold blue]口碑速查报告[/bold blue]", border_style="blue", expand=True))

    def print_volume_section(self, result: AnalysisResult):
        va = result.volume_analysis
        console.print("\n[bold underline blue]一、讨论量与情感概况[/bold underline blue]")

        kpi_table = Table(show_header=False, box=box.SIMPLE, expand=True)
        kpi_table.add_column("指标", style="bold")
        kpi_table.add_column("数值", justify="right")

        kpi_table.add_row(
            "本时段讨论量",
            f"[bold]{va.time_range_posts}[/bold] 帖"
        )
        kpi_table.add_row(
            "上一周期讨论量",
            f"{va.previous_range_posts} 帖"
        )
        kpi_table.add_row(
            "环比变化",
            self._change_arrow(va.volume_change_rate, positive_good=True)
        )
        kpi_table.add_row(
            "负面占比",
            f"[bold red]{va.negative_ratio:.1f}%[/bold red]"
        )
        kpi_table.add_row(
            "上一周期负面占比",
            f"{va.previous_negative_ratio:.1f}%"
        )
        kpi_table.add_row(
            "负面占比环比变化",
            self._change_arrow(va.negative_ratio_change, positive_good=False)
        )

        console.print(Panel(kpi_table, title="核心指标（含上一周期可比数据）", border_style="cyan"))

        if va.by_source:
            src_table = Table(title="各平台分布", box=box.MINIMAL, show_lines=False)
            src_table.add_column("平台", style="bold")
            src_table.add_column("讨论量", justify="right")
            src_table.add_column("占比", justify="right")
            total = sum(va.by_source.values())
            for src, cnt in sorted(va.by_source.items(), key=lambda x: x[1], reverse=True):
                pct = cnt / total * 100 if total else 0
                src_table.add_row(src, str(cnt), f"{pct:.1f}%")
            console.print(src_table)

        if va.trend_points:
            self._print_trend_chart(va.trend_points)

    def _print_trend_chart(self, points: List[VolumeTrendPoint]):
        chart_title = "讨论量趋势（按时间分段）"
        max_total = max((p.total_count for p in points), default=1)

        console.print(f"\n[bold]{chart_title}[/bold]")
        table = Table(box=box.HORIZONTALS, show_lines=False)
        table.add_column("时段", style="cyan", width=12)
        table.add_column("总量", justify="right")
        table.add_column("分布图", min_width=25)
        table.add_column("负面占比", justify="right", style="red")

        for p in points:
            date_str = p.date.strftime("%m-%d")
            bar = self._make_bar(p.total_count / max_total if max_total else 0, width=18, positive=True)
            neg_pct = f"{p.negative_ratio * 100:.1f}%" if p.total_count > 0 else "N/A"
            table.add_row(date_str, str(p.total_count), bar, neg_pct)
        console.print(table)

    def print_theme_section(self, result: AnalysisResult):
        ta = result.theme_analysis
        console.print("\n[bold underline blue]二、热门话题关键词[/bold underline blue]")

        cols = []

        if ta.advantages:
            adv_panel = self._keyword_panel("被称赞最多的优点", ta.advantages, "green")
            cols.append(adv_panel)

        if ta.complaints:
            comp_panel = self._keyword_panel("抱怨最多的槽点", ta.complaints, "red")
            cols.append(comp_panel)

        if ta.questions:
            q_panel = self._keyword_panel("用户疑问焦点", ta.questions, "cyan")
            cols.append(q_panel)

        if cols:
            console.print(Columns(cols, equal=True, expand=True))

        if ta.focus_theme_matches:
            console.print("\n[bold yellow]关注主题匹配结果:[/bold yellow]")
            for theme, matches in ta.focus_theme_matches.items():
                match_strs = []
                for m in matches:
                    label = self._sentiment_label(m.sentiment)
                    match_strs.append(f"  • [bold]{m.keyword}[/bold] ({m.count}次) {label}")
                if match_strs:
                    console.print(f"\n[italic]主题: {theme}[/italic]")
                    for s in match_strs:
                        console.print(s)

    def _keyword_panel(self, title: str, keywords, color: str) -> Panel:
        table = Table(show_header=False, box=None, expand=False)
        table.add_column("关键词", style=f"bold {color}", ratio=3)
        table.add_column("次数", justify="right", ratio=1)

        for kw in keywords[:8]:
            table.add_row(kw.keyword, f"[bold]{kw.count}[/bold]")

        return Panel(table, title=f"[{color}]{title}[/{color}]", border_style=color, expand=True)

    def print_representative_posts(self, result: AnalysisResult):
        console.print("\n[bold underline blue]三、代表性帖子摘要[/bold underline blue]")

        posts = result.representative_posts
        if not posts:
            console.print("[dim]（暂无代表性帖子）[/dim]")
            return

        for idx, p in enumerate(posts, 1):
            sentiment = self._sentiment_label(p.sentiment)
            header = Text.assemble(
                (f"【{idx:02d}】 ", "bold white"),
                (f"{p.title}", "bold"),
                "  ",
                sentiment,
            )
            time_str = p.publish_time.strftime(self.datetime_format) if p.publish_time else "未知"
            meta = f"[dim]{p.source} · {p.author}({p.author_level or ''}) · {time_str} · 👍{p.likes} 💬{p.comments_count}[/dim]"
            summary = p.summary or p.content[:80]

            body = f"{meta}\n\n{summary}"
            if p.themes:
                tags = " ".join(f"[#{t}#]" for t in p.themes[:4])
                body += f"\n\n[cyan]{tags}[/cyan]"
            if p.is_competing_brand_troll and p.competing_brand_ref:
                body += f"\n[yellow]⚠ 疑似竞品粉丝({p.competing_brand_ref})带节奏[/yellow]"
            if p.has_official_response:
                body += f"\n[green]✓ 已有官方回应[/green]"

            border_color = {
                SentimentType.POSITIVE: "green",
                SentimentType.NEGATIVE: "red",
                SentimentType.NEUTRAL: "yellow",
                SentimentType.QUESTION: "cyan",
            }.get(p.sentiment, "white")

            console.print(Panel(body, title=header, border_style=border_color, expand=True))

    def print_complaint_detail(self, detail: ComplaintDetail, keyword: str):
        matched_note = ""
        if detail.matched_keyword and detail.matched_keyword != keyword:
            matched_note = f"（模糊匹配到：[bold yellow]{detail.matched_keyword}[/bold yellow]）"

        console.print(Panel(
            f"[bold]槽点深挖: {keyword}[/bold] {matched_note}",
            border_style="bold red",
            expand=True
        ))

        info_table = Table(show_header=False, box=box.SIMPLE, expand=True)
        info_table.add_column("项目", style="bold")
        info_table.add_column("详情")

        info_table.add_row("总提及次数", f"[bold red]{detail.total_mentions}[/bold red] 次")
        info_table.add_row("频率趋势", {
            "骤升": "[bold red]⚠ 骤升（需高度关注）[/bold red]",
            "上升": "[yellow]↑ 上升中[/yellow]",
            "下降": "[green]↓ 趋缓[/green]",
            "平稳": "[blue]→ 平稳[/blue]",
            "数据不足": "[dim]数据不足[/dim]",
        }.get(detail.frequency_trend, detail.frequency_trend))

        if detail.is_competitor_troll:
            troll_info = f"[bold yellow]是[/bold yellow]（疑似 {detail.competitor_brand or '竞品'} 粉丝带节奏，占比 {detail.troll_ratio:.1f}%）"
        else:
            troll_info = f"[green]否[/green]（带节奏占比 {detail.troll_ratio:.1f}%）"
        info_table.add_row("是否竞品带节奏", troll_info)

        info_table.add_row(
            "是否有官方回应",
            "[bold green]是[/bold green]" if detail.has_official_response else "[yellow]否（建议关注）[/yellow]"
        )

        console.print(Panel(info_table, title="核心信息", border_style="magenta"))

        if detail.grouped_expressions:
            console.print(f"\n[bold]代表性原话（按相似表达分组，共 {len(detail.grouped_expressions)} 组）:[/bold]")
            for gi, group in enumerate(detail.grouped_expressions, 1):
                console.print(f"\n[bold red]第 {gi} 组 · {group.group_key}[/bold red]（[bold]{group.count}[/bold] 次提及）")
                for ei, ex in enumerate(group.examples, 1):
                    console.print(f"  [{ei}]「{ex}」")
        elif detail.typical_expressions:
            console.print(f"\n[bold]典型表达 (Top {min(len(detail.typical_expressions), 8)}):[/bold]")
            expr_table = Table(box=box.MINIMAL, show_lines=False)
            expr_table.add_column("#", justify="right", style="dim")
            expr_table.add_column("典型表达")
            expr_table.add_column("次数", justify="right")
            for i, (expr, cnt) in enumerate(detail.typical_expressions[:8], 1):
                expr_table.add_row(str(i), expr, f"[bold]{cnt}[/bold]")
            console.print(expr_table)

        if detail.source_distribution:
            console.print(f"\n[bold]来源分布:[/bold]")
            src_table = Table(box=box.MINIMAL, show_lines=False)
            src_table.add_column("平台", style="bold")
            src_table.add_column("条数", justify="right")
            total = sum(detail.source_distribution.values())
            for src, cnt in sorted(detail.source_distribution.items(), key=lambda x: x[1], reverse=True):
                src_table.add_row(src, f"{cnt} ({cnt/total*100:.0f}%)")
            console.print(src_table)

        if detail.official_response_examples:
            console.print(f"\n[green bold]官方回应示例:[/green bold]")
            for resp in detail.official_response_examples[:3]:
                console.print(f"  [green]» {resp}[/green]")

        if detail.related_posts:
            console.print(f"\n[bold]相关代表帖:[/bold]")
            for p in detail.related_posts[:5]:
                time_str = p.publish_time.strftime(self.datetime_format) if p.publish_time else ""
                console.print(f"  • [cyan]{p.source}[/cyan] {time_str} [italic]{p.title}[/italic]")

    def print_batch_comparison(self, comp: BatchComparisonResult):
        console.print(Panel(
            f"[bold magenta]目标品牌:[/bold magenta] {comp.target_brand}\n"
            f"[bold magenta]对比品牌:[/bold magenta] {', '.join(b for b in comp.brands if b != comp.target_brand)}\n"
            f"[bold magenta]时间范围:[/bold magenta] {comp.time_range or '全量'}\n"
            f"[dim]生成时间: {comp.generated_at.strftime(self.datetime_format)}[/dim]",
            title="[bold red]批量竞品对比报告[/bold red]",
            border_style="red",
            expand=True,
        ))

        console.print("\n[bold underline red]【一、总体指标对照表】[/bold underline red]")
        rows_sorted = sorted(comp.rows, key=lambda r: (not r.is_target, -r.risk_score))

        main_table = Table(title="品牌对比总览（按目标品牌+风险排序）", box=box.ROUNDED, expand=True)
        main_table.add_column("品牌", style="bold")
        main_table.add_column("类型", justify="center")
        main_table.add_column("讨论量", justify="right")
        main_table.add_column("环比", justify="right")
        main_table.add_column("负面占比", justify="right")
        main_table.add_column("Top 差评", justify="left")
        main_table.add_column("Top 好评", justify="left")
        main_table.add_column("带节奏%", justify="right")
        main_table.add_column("官方响应%", justify="right")
        main_table.add_column("风险分", justify="center")

        for r in rows_sorted:
            brand_type = "[bold blue]★ 目标[/bold blue]" if r.is_target else "竞品"

            volume_arrow = self._change_arrow(r.volume_change_rate, positive_good=True)
            if r.volume_change_rate > 30:
                volume_arrow += " ⚠"

            neg_style = "red bold" if r.negative_ratio > 50 else ("yellow" if r.negative_ratio > 35 else "green")
            neg_col = f"[{neg_style}]{r.negative_ratio:.1f}%[/{neg_style}]"

            top_comp = f"{r.top_complaint}({r.top_complaint_count})" if r.top_complaint else "-"
            top_adv = f"{r.top_advantage}({r.top_advantage_count})" if r.top_advantage else "-"

            troll_style = "bold yellow" if r.troll_ratio > 30 else ""
            troll_col = f"[{troll_style}]{r.troll_ratio:.1f}%[/{troll_style}]" if troll_style else f"{r.troll_ratio:.1f}%"

            resp_style = "green bold" if r.official_response_ratio > 30 else ("yellow" if r.official_response_ratio > 15 else "red bold")
            resp_col = f"[{resp_style}]{r.official_response_ratio:.1f}%[/{resp_style}]"

            if r.risk_score >= 4:
                risk_col = f"[bold red]■■ {r.risk_score}[/bold red]"
            elif r.risk_score >= 2:
                risk_col = f"[bold yellow]■ {r.risk_score}[/bold yellow]"
            else:
                risk_col = f"[green] {r.risk_score}[/green]"

            main_table.add_row(
                r.brand, brand_type, str(r.total_posts), volume_arrow, neg_col,
                top_comp, top_adv, troll_col, resp_col, risk_col
            )
        console.print(main_table)

        console.print("\n[bold underline red]【二、槽点横向对比】[/bold underline red]")
        all_complaints: Dict[str, Dict[str, int]] = {}
        for r in comp.rows:
            if r.top_complaint:
                all_complaints.setdefault(r.brand, {})
                all_complaints[r.brand][r.top_complaint] = r.top_complaint_count

        target_row = next((r for r in comp.rows if r.is_target), None)
        if target_row and target_row.top_complaint:
            console.print(f"\n[yellow]→ 目标品牌「{comp.target_brand}」核心槽点：[bold red]{target_row.top_complaint}[/bold red][/yellow]")

            compare_table = Table(title=f"围绕「{target_row.top_complaint}」的竞品情况", box=box.MINIMAL)
            compare_table.add_column("品牌", style="bold")
            compare_table.add_column("该槽点提及数", justify="right")
            compare_table.add_column("相对严重度", justify="right")
            target_count = target_row.top_complaint_count
            for r in comp.rows:
                mention_count = r.top_complaint_count if r.top_complaint == target_row.top_complaint else 0
                if mention_count == 0:
                    severity = "[dim]—[/dim]"
                elif target_count == 0:
                    severity = f"[yellow]高（{mention_count}次）[/yellow]"
                else:
                    ratio = mention_count / target_count
                    if ratio >= 1.2:
                        severity = f"[red]比目标严重 {ratio:.1f}x[/red]"
                    elif ratio >= 0.8:
                        severity = f"[yellow]接近目标[/yellow]"
                    else:
                        severity = f"[green]优于目标 {ratio:.1f}x[/green]"
                compare_table.add_row(r.brand, str(mention_count), severity)
            console.print(compare_table)

        console.print("\n[bold underline red]【三、风险与建议摘要】[/bold underline red]")
        sorted_by_risk = sorted(comp.rows, key=lambda r: -r.risk_score)
        for r in sorted_by_risk:
            if r.is_target:
                console.print(f"\n[bold blue]★ 目标品牌 {r.brand}：[/bold blue]风险分 {r.risk_score}/6")
                tips = []
                if r.negative_ratio > 50:
                    tips.append("负面讨论过半，建议紧急关注")
                if r.volume_change_rate > 30:
                    tips.append("讨论量快速上升，需确认是否有事件发酵")
                if r.troll_ratio > 30:
                    tips.append(f"疑似竞品带节奏比例高（{r.troll_ratio:.0f}%），建议舆情研判")
                if r.official_response_ratio < 15 and r.negative_ratio > 30:
                    tips.append("官方响应率偏低，建议补充危机话术")
                if r.top_complaint and r.top_complaint_count >= max(3, r.total_posts * 0.2):
                    tips.append(f"「{r.top_complaint}」集中爆发，建议重点访谈")
                if tips:
                    for t in tips:
                        console.print(f"  ⚠ {t}")
                else:
                    console.print("  ✓ 各项指标正常，常规观察即可")
            else:
                console.print(f"\n[bold]竞品 {r.brand}：[/bold]风险分 {r.risk_score}/6")
                insights = []
                if r.top_advantage and r.top_advantage_count >= 3:
                    insights.append(f"突出优势：{r.top_advantage}（{r.top_advantage_count}次），可对标学习")
                if r.official_response_ratio > target_row.official_response_ratio if target_row else False:
                    insights.append(f"官方响应率{r.official_response_ratio:.0f}%，优于目标品牌")
                if r.troll_ratio < (target_row.troll_ratio if target_row else 999):
                    insights.append(f"带节奏率较低（{r.troll_ratio:.0f}%），舆情环境相对干净")
                if insights:
                    for ins in insights:
                        console.print(f"  ✓ 可借鉴点：{ins}")

    def print_full_report(self, result: AnalysisResult):
        self.print_header(result)
        self.print_volume_section(result)
        self.print_theme_section(result)
        self.print_representative_posts(result)
        console.print("\n[dim]提示: 输入「追问 槽点关键词」可深挖；输入「对比」可批量竞品对照；输入「导出」保存会议纪要[/dim]")

    def build_meeting_minutes(self, result: AnalysisResult) -> MeetingMinutes:
        params = result.query_params
        va = result.volume_analysis
        ta = result.theme_analysis

        title = f"品牌口碑调研会议纪要 - {params.target_brand}"
        minutes = MeetingMinutes(
            title=title,
            query_params=params,
            generated_at=datetime.now(),
            raw_analysis_ref=f"analysis_{result.generated_at.strftime('%Y%m%d_%H%M%S')}.json",
        )

        findings = []
        findings.append(
            f"监测期间[{params.time_range}]共获取讨论 {va.time_range_posts} 条，"
            f"对比上一周期({va.previous_range_posts}条)环比变化 {va.volume_change_rate:+.1f}%。"
        )
        findings.append(
            f"负面讨论占比 {va.negative_ratio:.1f}%，"
            f"对比上一周期({va.previous_negative_ratio:.1f}%)变化{va.negative_ratio_change:+.1f}个百分点。"
        )
        if va.by_source:
            top_src = max(va.by_source.items(), key=lambda x: x[1])
            findings.append(f"主要讨论平台为「{top_src[0]}」({top_src[1]}条)。")
        if ta.advantages:
            findings.append(f"用户好评最多的方面: {ta.advantages[0].keyword}({ta.advantages[0].count}次提及)。")
        if ta.complaints:
            findings.append(f"用户抱怨最多的方面: {ta.complaints[0].keyword}({ta.complaints[0].count}次提及)。")
        if ta.questions:
            findings.append(f"用户集中疑问: {ta.questions[0].keyword}({ta.questions[0].count}次提及)。")
        minutes.key_findings = findings

        for p in result.representative_posts[:10]:
            if len(p.summary) < 10:
                continue
            related_theme = p.themes[0] if p.themes else (p.keywords[0] if p.keywords else "综合")
            minutes.quotable_quotes.append(MeetingMinutesItem(
                quote=p.summary,
                source=f"{p.source} | {p.title}",
                sentiment=p.sentiment,
                related_theme=related_theme,
            ))

        if ta.complaints:
            analyzer = Analyzer(self.config)
            for comp in ta.complaints[:5]:
                detail = analyzer.get_complaint_detail(comp.keyword, result)
                priority = "高" if detail.frequency_trend in ("骤升", "上升") or detail.troll_ratio > 30 else "中"
                if detail.total_mentions < 3:
                    priority = "低"
                suggestion_parts = []
                if detail.troll_ratio > 30:
                    suggestion_parts.append(f"排查是否有{detail.competitor_brand or '竞品'}粉丝刻意放大")
                if not detail.has_official_response:
                    suggestion_parts.append("建议尽快准备官方回应口径")
                if detail.frequency_trend in ("骤升", "上升"):
                    suggestion_parts.append("重点监测后续走势")
                suggestion = "；".join(suggestion_parts) or "持续观察"
                minutes.tracking_issues.append(TrackingIssue(
                    issue=comp.keyword,
                    priority=priority,
                    related_count=detail.total_mentions,
                    suggestion=suggestion,
                ))

        directions: List[InterviewDirection] = []
        if ta.complaints:
            directions.append(InterviewDirection(
                direction="负面用户深度访谈",
                target_group=f"对{ta.complaints[0].keyword}等问题有抱怨的用户",
                questions=[
                    f"您在使用过程中遇到的「{ta.complaints[0].keyword}」具体表现是？",
                    "当时是否联系过客服？处理结果如何？",
                    "这个问题多大程度影响您的复购意愿？",
                    "是否有对比过竞品在这方面的表现？",
                ]
            ))
        if ta.advantages:
            directions.append(InterviewDirection(
                direction="粉丝用户访谈",
                target_group=f"对{ta.advantages[0].keyword}等方面高度认可的用户",
                questions=[
                    f"您觉得「{ta.advantages[0].keyword}」具体体现在哪些场景？",
                    "当初选择这个品牌的核心原因是？",
                    "哪些情况下会推荐给朋友？",
                ]
            ))
        if ta.questions:
            directions.append(InterviewDirection(
                direction="潜在用户访谈",
                target_group=f"有购买意向、关注{ta.questions[0].keyword}等问题的群体",
                questions=[
                    f"关于「{ta.questions[0].keyword}」，您最希望了解什么信息？",
                    "目前主要有哪些顾虑？",
                    "什么因素会推动您最终下单？",
                ]
            ))
        minutes.interview_directions = directions

        return minutes

    def export_meeting_minutes(self, minutes: MeetingMinutes, output_dir: Optional[str] = None) -> str:
        odir = output_dir or self.config.get("output", {}).get("default_dir", "./reports")
        os.makedirs(odir, exist_ok=True)
        filename = f"会议纪要_{minutes.query_params.target_brand}_{minutes.generated_at.strftime('%Y%m%d_%H%M%S')}.txt"
        filepath = os.path.join(odir, filename)

        lines: List[str] = []
        lines.append("=" * 70)
        lines.append(f"  {minutes.title}")
        lines.append("=" * 70)
        lines.append("")
        lines.append(f"生成时间: {minutes.generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"目标品牌: {minutes.query_params.target_brand}")
        if minutes.query_params.competing_brands:
            lines.append(f"对比竞品: {', '.join(minutes.query_params.competing_brands)}")
        if minutes.query_params.time_range:
            lines.append(f"时间范围: {minutes.query_params.time_range}")
        if minutes.query_params.focus_themes:
            lines.append(f"关注主题: {', '.join(minutes.query_params.focus_themes)}")
        lines.append("")

        lines.append("-" * 70)
        lines.append("【一、核心发现】")
        lines.append("-" * 70)
        for i, finding in enumerate(minutes.key_findings, 1):
            lines.append(f"  {i}. {finding}")
        lines.append("")

        lines.append("-" * 70)
        lines.append("【二、可引用原话】")
        lines.append("-" * 70)
        sentiment_map = {
            SentimentType.POSITIVE: "正面",
            SentimentType.NEGATIVE: "负面",
            SentimentType.NEUTRAL: "中性",
            SentimentType.QUESTION: "疑问",
        }
        for i, item in enumerate(minutes.quotable_quotes, 1):
            sent = sentiment_map.get(item.sentiment, "未知")
            lines.append(f"  {i}.【{sent}·{item.related_theme}】「{item.quote}」")
            lines.append(f"     —— 来源: {item.source}")
        lines.append("")

        lines.append("-" * 70)
        lines.append("【三、建议追踪的问题】")
        lines.append("-" * 70)
        priority_style = {"高": "★★★", "中": "★★", "低": "★"}
        lines.append(f"  {'优先级':<6} {'问题':<12} {'相关讨论':<10} 建议")
        for issue in minutes.tracking_issues:
            p = priority_style.get(issue.priority, "★")
            lines.append(f"  {p:<6} {issue.issue:<12} {issue.related_count:<10} {issue.suggestion}")
        lines.append("")

        lines.append("-" * 70)
        lines.append("【四、下一步访谈方向】")
        lines.append("-" * 70)
        for d in minutes.interview_directions:
            lines.append(f"  ■ {d.direction}")
            lines.append(f"    对象: {d.target_group}")
            lines.append(f"    建议问题:")
            for q in d.questions:
                lines.append(f"      - {q}")
            lines.append("")

        lines.append("-" * 70)
        lines.append(f"原始分析数据参考: {minutes.raw_analysis_ref}")
        lines.append("=" * 70)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        json_path = os.path.join(odir, minutes.raw_analysis_ref)
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({
                    "title": minutes.title,
                    "generated_at": minutes.generated_at.isoformat(),
                    "query_params": {
                        "target_brand": minutes.query_params.target_brand,
                        "competing_brands": minutes.query_params.competing_brands,
                        "focus_themes": minutes.query_params.focus_themes,
                    },
                    "key_findings": minutes.key_findings,
                }, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        return filepath


    def build_comparison_minutes(self, comp: BatchComparisonResult) -> str:
        lines: List[str] = []
        lines.append("=" * 70)
        lines.append(f"  多品牌口碑对比纪要（客户版）")
        lines.append("=" * 70)
        lines.append("")
        lines.append(f"生成时间: {comp.generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"目标品牌: {comp.target_brand}")
        lines.append(f"对比品牌: {', '.join(b for b in comp.brands if b != comp.target_brand)}")
        lines.append(f"监测时段: {comp.time_range or '全量数据'}")
        lines.append("")

        sorted_rows = sorted(comp.rows, key=lambda r: (not r.is_target, -r.risk_score))

        lines.append("-" * 70)
        lines.append("【一、总体指标速览】")
        lines.append("-" * 70)
        header = f"  {'品牌':<10} {'类型':<6} {'讨论量':>6} {'环比':>8} {'负面占比':>8} {'风险分':>6}"
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        for r in sorted_rows:
            btype = "★目标" if r.is_target else "竞品"
            arrow = f"{r.volume_change_rate:+.1f}%"
            neg = f"{r.negative_ratio:.1f}%"
            risk = f"{r.risk_score}/6"
            lines.append(f"  {r.brand:<10} {btype:<6} {r.total_posts:>6} {arrow:>8} {neg:>8} {risk:>6}")
        lines.append("")

        lines.append("-" * 70)
        lines.append("【二、各品牌详细情况与建议动作】")
        lines.append("-" * 70)
        for r in sorted_rows:
            marker = "★ " if r.is_target else "  "
            lines.append("")
            lines.append(f"{marker}{r.brand}")
            lines.append(f"  ├ 负面讨论占比: {r.negative_ratio:.1f}%（环比 {r.volume_change_rate:+.1f}%）")

            if r.top_complaint:
                lines.append(f"  ├ 主要槽点: 「{r.top_complaint}」{r.top_complaint_count} 次提及")
            else:
                lines.append(f"  ├ 主要槽点: 暂无明显集中槽点")

            if r.top_advantage:
                lines.append(f"  ├ 主要好评: 「{r.top_advantage}」{r.top_advantage_count} 次提及")

            lines.append(f"  ├ 带节奏风险: {r.troll_ratio:.1f}% {'⚠ 偏高' if r.troll_ratio > 30 else '正常'}")
            lines.append(f"  ├ 官方响应率: {r.official_response_ratio:.1f}% {'（建议加强）' if r.official_response_ratio < 15 and r.negative_ratio > 30 else ''}")

            lines.append(f"  └ 建议动作:")
            actions: List[str] = []
            if r.is_target:
                if r.negative_ratio > 50:
                    actions.append("紧急召开舆情复盘会议，负面讨论已过半")
                if r.volume_change_rate > 30:
                    actions.append("追踪讨论量上升动因，确认是否有事件发酵")
                if r.top_complaint and r.top_complaint_count >= max(3, r.total_posts * 0.2):
                    actions.append(f"针对「{r.top_complaint}」准备危机话术与客户安抚方案")
                if r.troll_ratio > 30:
                    actions.append("舆情团队介入研判，排查竞品带节奏账号")
                if r.official_response_ratio < 15 and r.negative_ratio > 30:
                    actions.append("提升官方响应时效，避免负面进一步扩散")
            else:
                if r.top_advantage and r.top_advantage_count >= 3:
                    actions.append(f"对标学习竞品「{r.top_advantage}」方面的用户口碑")
                if r.official_response_ratio > 20:
                    actions.append(f"参考竞品 {r.official_response_ratio:.0f}% 的官方响应机制")
                if r.troll_ratio < 10:
                    actions.append("研究竞品舆情治理经验，降低带节奏风险")
            if not actions:
                actions.append("维持常规观察，暂无特殊动作")
            for act in actions:
                lines.append(f"      · {act}")

        lines.append("")
        lines.append("-" * 70)
        lines.append("【三、总结】")
        lines.append("-" * 70)
        target_row = next((r for r in comp.rows if r.is_target), None)
        if target_row:
            worst_comp = max((r for r in comp.rows if not r.is_target), key=lambda r: r.risk_score, default=None)
            best_comp = min((r for r in comp.rows if not r.is_target), key=lambda r: r.risk_score, default=None)
            lines.append(f"  · 目标品牌「{comp.target_brand}」风险等级: {target_row.risk_score}/6")
            if worst_comp:
                lines.append(f"  · 风险最高竞品: 「{worst_comp.brand}」({worst_comp.risk_score}/6)，可重点观察其负面应对")
            if best_comp:
                lines.append(f"  · 表现最佳竞品: 「{best_comp.brand}」({best_comp.risk_score}/6)，可对标学习其口碑运营")
        lines.append("")
        lines.append("=" * 70)
        return "\n".join(lines)

    def export_comparison_minutes(
        self,
        comp: BatchComparisonResult,
        output_dir: Optional[str] = None,
        filename_prefix: Optional[str] = None,
    ) -> str:
        odir = output_dir or self.config.get("output", {}).get("default_dir", "./reports")
        os.makedirs(odir, exist_ok=True)
        prefix = filename_prefix or f"对比纪要_{comp.target_brand}"
        filename = f"{prefix}_{comp.generated_at.strftime('%Y%m%d_%H%M%S')}.txt"
        filepath = os.path.join(odir, filename)
        content = self.build_comparison_minutes(comp)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return filepath


def generate_report(result: AnalysisResult, config: Optional[Dict] = None):
    gen = ReportGenerator(config=config)
    gen.print_full_report(result)
    return gen
