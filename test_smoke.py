#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速测试脚本 - 验证口碑速查工具完整流程
"""

import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import QueryParams, TimeRange, SentimentType
from data_source import fetch_posts
from analyzer import analyze, Analyzer
from report_generator import ReportGenerator


def main():
    print("=" * 60)
    print("  品牌口碑速查工具 - 自动测试")
    print("=" * 60)

    params = QueryParams(
        target_brand="小米手机",
        competing_brands=["华为手机", "苹果手机"],
        time_range=TimeRange(
            start_date=datetime.now() - timedelta(days=30),
            end_date=datetime.now(),
        ),
        focus_themes=["售后", "新品", "涨价", "续航"],
    )

    print(f"\n[1/5] 目标品牌: {params.target_brand}")
    print(f"      竞品: {', '.join(params.competing_brands)}")
    print(f"      时间: {params.time_range}")
    print(f"      主题: {', '.join(params.focus_themes)}")

    print("\n[2/5] 正在生成模拟帖子数据...")
    posts = fetch_posts(params, count=300, seed=42)
    target_posts = [p for p in posts if p.brand == params.target_brand]
    print(f"      共生成 {len(posts)} 条帖子，其中目标品牌 {len(target_posts)} 条")

    sentiment_counts = {}
    for p in target_posts:
        sentiment_counts[p.sentiment.value] = sentiment_counts.get(p.sentiment.value, 0) + 1
    print(f"      情感分布: {sentiment_counts}")

    print("\n[3/5] 正在执行分析...")
    result = analyze(posts, params)
    va = result.volume_analysis
    ta = result.theme_analysis

    print(f"      本时段讨论量: {va.time_range_posts} (环比 {va.volume_change_rate:+.1f}%)")
    print(f"      负面占比: {va.negative_ratio:.1f}% (环比 {va.negative_ratio_change:+.1f}%)")
    print(f"      平台分布: {dict(list(va.by_source.items())[:3])}")

    print(f"\n      优点 Top 3:")
    for i, adv in enumerate(ta.advantages[:3], 1):
        print(f"        {i}. {adv.keyword}: {adv.count} 次")

    print(f"      槽点 Top 3:")
    for i, comp in enumerate(ta.complaints[:3], 1):
        print(f"        {i}. {comp.keyword}: {comp.count} 次")

    print(f"      疑问 Top 3:")
    for i, q in enumerate(ta.questions[:3], 1):
        print(f"        {i}. {q.keyword}: {q.count} 次")

    print(f"\n[4/5] 测试追问功能 (槽点: {ta.complaints[0].keyword if ta.complaints else '售后差'})...")
    analyzer = Analyzer()
    test_keyword = ta.complaints[0].keyword if ta.complaints else "售后差"
    detail = analyzer.get_complaint_detail(test_keyword, result)
    print(f"      关键词: {detail.complaint_keyword}")
    print(f"      提及次数: {detail.total_mentions}")
    print(f"      频率趋势: {detail.frequency_trend}")
    print(f"      是否竞品带节奏: {detail.is_competitor_troll} ({detail.troll_ratio:.1f}%)")
    print(f"      是否有官方回应: {detail.has_official_response}")
    print(f"      典型表达数: {len(detail.typical_expressions)}")

    print(f"\n[5/5] 测试会议纪要导出...")
    report_gen = ReportGenerator()
    minutes = report_gen.build_meeting_minutes(result)
    output_path = report_gen.export_meeting_minutes(minutes, output_dir="./reports")
    print(f"      核心发现数: {len(minutes.key_findings)}")
    print(f"      可引用原话数: {len(minutes.quotable_quotes)}")
    print(f"      待追踪问题数: {len(minutes.tracking_issues)}")
    print(f"      访谈方向数: {len(minutes.interview_directions)}")
    print(f"      已保存到: {os.path.abspath(output_path)}")

    print("\n" + "=" * 60)
    print("  ✅ 所有测试通过！工具运行正常。")
    print("=" * 60)
    print("\n下一步:")
    print("  1. 安装依赖: pip install -r requirements.txt")
    print("  2. 交互模式: python main.py")
    print("  3. 命令行模式: python main.py --brand 小米手机 --days 30 --themes 售后,新品,涨价 --export")


if __name__ == "__main__":
    main()
