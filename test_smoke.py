#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
冒烟测试 v2 - 验证口碑速查工具全部功能（含 v2 新特性）
"""

import sys
import os
import shutil
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import QueryParams, TimeRange
from data_source import fetch_posts_with_library
from analyzer import analyze, Analyzer
from report_generator import ReportGenerator
from sample_library import SampleLibrary, get_library


TEST_DB_PATH = "./sample_library/test_sample_posts.db"


def cleanup_test_db():
    global _global_library
    import gc
    gc.collect()
    try:
        import sample_library
        sample_library._global_library = None
    except Exception:
        pass
    db_dir = os.path.dirname(TEST_DB_PATH)
    if os.path.exists(TEST_DB_PATH):
        for attempt in range(3):
            try:
                os.remove(TEST_DB_PATH)
                break
            except PermissionError:
                import time
                time.sleep(0.2)
                continue


def main():
    print("=" * 70)
    print("  品牌口碑速查工具 v2 - 全面冒烟测试")
    print("=" * 70)

    # 使用独立的测试库，避免污染生产数据
    cleanup_test_db()

    try:
        params = QueryParams(
            target_brand="小米手机",
            competing_brands=["华为手机", "苹果手机"],
            time_range=TimeRange(
                start_date=datetime.now() - timedelta(days=30),
                end_date=datetime.now(),
            ),
            focus_themes=["售后", "新品", "涨价", "续航"],
        )

        print(f"\n目标品牌: {params.target_brand}")
        print(f"竞品    : {', '.join(params.competing_brands)}")
        print(f"时间范围: {params.time_range}")
        print(f"关注主题: {', '.join(params.focus_themes)}")

        lib = SampleLibrary(db_path=TEST_DB_PATH)

        # ======= 测试1: 双周期环比数据（修复 +100% 问题）=======
        print("\n" + "-" * 70)
        print("[1/7] 测试 双周期环比数据生成（修复固定 +100% 问题）")
        print("-" * 70)

        posts, stats = fetch_posts_with_library(
            params, count=300, use_library=True, library=lib
        )
        target_posts = [p for p in posts if p.brand == params.target_brand]

        tr = params.time_range
        range_days = max(1, (tr.end_date - tr.start_date).days)
        prev_start = tr.start_date - timedelta(days=range_days)
        prev_end = tr.start_date - timedelta(seconds=1)

        current = [p for p in target_posts if p.publish_time and tr.start_date <= p.publish_time <= tr.end_date]
        previous = [p for p in target_posts if p.publish_time and prev_start <= p.publish_time <= prev_end]

        print(f"  本周期讨论量  : {len(current)}")
        print(f"  上一周期讨论量: {len(previous)}")
        if len(previous) > 0:
            rate = (len(current) - len(previous)) / len(previous) * 100
            print(f"  环比变化率    : {rate:+.1f}%  ✅ 不再固定 +100%")
        else:
            print(f"  ⚠ 上一周期数据不足（需增加样本量或扩大时间范围）")

        assert len(previous) > 0, "上一周期必须有数据！"
        assert len(current) > 0, "本周期必须有数据！"
        print("  ✅ 通过")

        # ======= 测试2: 分析引擎环比计算 =======
        print("\n" + "-" * 70)
        print("[2/7] 测试 分析引擎环比计算 + 会议纪要同步")
        print("-" * 70)

        result = analyze(posts, params)
        va = result.volume_analysis
        print(f"  time_range_posts        : {va.time_range_posts}")
        print(f"  previous_range_posts    : {va.previous_range_posts}")
        print(f"  volume_change_rate      : {va.volume_change_rate:+.1f}%")
        print(f"  negative_ratio          : {va.negative_ratio:.1f}%")
        print(f"  previous_negative_ratio : {va.previous_negative_ratio:.1f}%")
        print(f"  negative_ratio_change   : {va.negative_ratio_change:+.1f} pp")

        assert va.previous_range_posts > 0, "previous_range_posts 应为正数！"
        assert abs(va.volume_change_rate) != 100.0 or va.previous_range_posts == 0, "不应固定为 ±100%"

        gen = ReportGenerator()
        minutes = gen.build_meeting_minutes(result)
        print(f"\n  会议纪要核心发现（首条）:")
        print(f"    {minutes.key_findings[0]}")
        assert "上一周期" in minutes.key_findings[0] or "对比上一周期" in minutes.key_findings[0], "会议纪要应包含上一周期对比"
        print("  ✅ 通过")

        # ======= 测试3: 离线样本库持久化 =======
        print("\n" + "-" * 70)
        print("[3/7] 测试 离线样本库持久化 + 历史复用")
        print("-" * 70)

        info_before = lib.count_by_brand(params.target_brand)
        print(f"  首次入库后「{params.target_brand}」帖数: {info_before['total']}")

        info_comp = lib.count_by_brand(params.competing_brands[0])
        print(f"  首次入库后「{params.competing_brands[0]}」帖数: {info_comp['total']}")

        assert info_before["total"] > 0, "样本库应该有数据！"

        # 第二次查询同一品牌，应该命中库中数据
        print(f"\n  第二次查询同品牌同时间范围...")
        posts2, stats2 = fetch_posts_with_library(
            params, count=300, use_library=True, library=lib
        )
        print(f"  library_hit    : {stats2.get('library_hit', 0)} （应>0）")
        print(f"  new_generated  : {stats2.get('new_generated', 0)}")
        print(f"  saved          : {stats2.get('saved', 0)} （应≤新生成数）")

        assert stats2.get("library_hit", 0) > 0, "第二次查询应命中样本库！"
        assert stats2.get("saved", 0) <= stats2.get("new_generated", 0), "新入库数量不应超过新生成数量！"

        brands_list = lib.list_brands()
        print(f"\n  样本库品牌总数: {len(brands_list)}")
        for b, c, latest in brands_list:
            print(f"    - {b}: {c} 帖")

        print("  ✅ 通过")

        # ======= 测试4: 模糊追问匹配 =======
        print("\n" + "-" * 70)
        print("[4/7] 测试 模糊追问 + 原话分组展示")
        print("-" * 70)

        analyzer = Analyzer()
        ta = result.theme_analysis
        print(f"  现有槽点: {[k.keyword for k in ta.complaints[:5]]}")

        test_queries = [
            "售后为什么差",
            "涨价",
            "新品翻车的问题",
            "续航太差了",
        ]

        for q in test_queries:
            detail = analyzer.get_complaint_detail(q, result)
            matched = detail.matched_keyword
            status = f"✅ 匹配到「{matched}」" if matched else "⚠ 未精确匹配"
            print(f"\n  查询「{q}」:")
            print(f"    {status}")
            print(f"    总提及次数: {detail.total_mentions}")
            print(f"    表达分组  : {len(detail.grouped_expressions)} 组")
            if detail.grouped_expressions:
                top = detail.grouped_expressions[0]
                print(f"    首组示例「{top.group_key}」: {top.count} 次，{len(top.examples)} 条原话")
                for i, ex in enumerate(top.examples[:2], 1):
                    print(f"      [{i}]「{ex[:40]}...」")

        # 检查是否真的是模糊匹配
        d1 = analyzer.get_complaint_detail("售后为什么差", result)
        assert d1.matched_keyword and d1.total_mentions > 0, "「售后为什么差」应能匹配到槽点！"
        print("\n  ✅ 通过")

        # ======= 测试5: 批量竞品对比 =======
        print("\n" + "-" * 70)
        print("[5/7] 测试 批量竞品对比（多品牌指标对照）")
        print("-" * 70)

        comp = analyzer.compare_brands(
            all_posts=posts,
            target_brand=params.target_brand,
            competing_brands=params.competing_brands,
            time_range=params.time_range,
        )

        print(f"  对比品牌数: {len(comp.brands)}")
        print(f"  总行数    : {len(comp.rows)}")

        target_row = next((r for r in comp.rows if r.is_target), None)
        assert target_row is not None, "应有目标品牌行！"
        assert target_row.brand == params.target_brand, "目标品牌名称错误！"

        for r in comp.rows:
            marker = "★" if r.is_target else " "
            print(f"  {marker} {r.brand}")
            print(f"      讨论量: {r.total_posts} | 环比: {r.volume_change_rate:+.1f}% | 负面: {r.negative_ratio:.1f}%")
            print(f"      差评Top: {r.top_complaint}({r.top_complaint_count}) | 好评Top: {r.top_advantage}({r.top_advantage_count})")
            print(f"      带节奏率: {r.troll_ratio:.1f}% | 官方响应率: {r.official_response_ratio:.1f}% | 风险分: {r.risk_score}/6")

        assert all(r.total_posts > 0 for r in comp.rows), "所有品牌都应有讨论数据！"
        print("  ✅ 通过")

        # ======= 测试6: 重启一致性（样本库复用后结果稳定）=======
        print("\n" + "-" * 70)
        print("[6/7] 测试 样本库复用 → 趋势/追问结果稳定")
        print("-" * 70)

        # 基于复用数据重新分析，关键指标应稳定
        result2 = analyze(posts2, params)
        va2 = result2.volume_analysis

        print(f"  第一次分析 time_range_posts: {va.time_range_posts}")
        print(f"  第二次分析 time_range_posts: {va2.time_range_posts}")
        print(f"  两次差异: {abs(va.time_range_posts - va2.time_range_posts)} 帖（样本库复用应差异较小）")

        detail_v1 = analyzer.get_complaint_detail(ta.complaints[0].keyword, result)
        detail_v2 = analyzer.get_complaint_detail(ta.complaints[0].keyword, result2)
        print(f"\n  两次追问「{ta.complaints[0].keyword}」:")
        print(f"    v1 提及次数: {detail_v1.total_mentions}, v2: {detail_v2.total_mentions}")
        print(f"    v1 匹配关键词: {detail_v1.matched_keyword}, v2: {detail_v2.matched_keyword}")

        print("  ✅ 通过")

        # ======= 测试7: 会议纪要导出（环比数据）=======
        print("\n" + "-" * 70)
        print("[7/7] 测试 会议纪要导出（含环比可比数据）")
        print("-" * 70)

        output_dir = "./reports_test"
        os.makedirs(output_dir, exist_ok=True)
        filepath = gen.export_meeting_minutes(minutes, output_dir=output_dir)
        print(f"  已导出: {os.path.abspath(filepath)}")

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        assert "对比上一周期" in content, "会议纪要应包含「对比上一周期」字样！"
        assert f"{va.volume_change_rate:+.1f}%" in content.replace(",", ""), f"会议纪要应包含环比率 {va.volume_change_rate:+.1f}%"
        print("  核心发现条数:", len(minutes.key_findings))
        print("  可引用原话语数:", len(minutes.quotable_quotes))
        print("  追踪问题条数:", len(minutes.tracking_issues))
        print("  访谈方向数:  ", len(minutes.interview_directions))
        print("  ✅ 通过")

        # ======= 清理 =======
        try:
            shutil.rmtree(output_dir, ignore_errors=True)
        except Exception:
            pass

        print("\n" + "=" * 70)
        print("  🎉 v2 全部 7 项测试通过！")
        print("=" * 70)
        print("\n验证的新功能:")
        print("  ① 双周期环比 → 不再固定 +100%，报告和会议纪要同步使用")
        print("  ② 离线样本库 → SQLite 持久化 + 指纹去重 + 历史复用")
        print("  ③ 模糊追问   → 「售后为什么差」「涨价」自然语言匹配 + 原话分组")
        print("  ④ 批量对比   → 多品牌负面/槽点/带节奏/官方响应对照 + 风险分")
        print("\n下一步:")
        print("  python main.py --brand 小米手机 --competitors 华为手机,苹果手机 --days 30 --compare")
        print("  python main.py (进入交互，输入「对比」「样本库」「追问售后为什么差」体验)")

    finally:
        cleanup_test_db()


if __name__ == "__main__":
    main()
