#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
冒烟测试 v4 - 验证口碑速查工具全部 v4 新特性
"""

import sys
import os
import shutil
import gc
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import QueryParams, TimeRange
from data_source import fetch_posts_with_library
from analyzer import analyze, Analyzer
from report_generator import ReportGenerator, build_project_progress_minutes, export_project_progress_minutes
from sample_library import SampleLibrary
from project_manager import ProjectManager


TEST_DB_PATH = "./sample_library/test_v4_sample_posts.db"
TEST_PROJECTS_DIR = "./projects_test_v4"
TEST_REPORTS_DIR = "./reports_test_v4"


def cleanup_test_db():
    gc.collect()
    try:
        import sample_library
        sample_library._global_library = None
    except Exception:
        pass
    for attempt in range(3):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
                break
            except PermissionError:
                import time
                time.sleep(0.2)
                continue
        else:
            break
    for d in [TEST_PROJECTS_DIR, TEST_REPORTS_DIR]:
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)


def main():
    print("=" * 70)
    print("  品牌口碑速查工具 v4 - 全面冒烟测试")
    print("=" * 70)

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
        pm = ProjectManager(projects_dir=TEST_PROJECTS_DIR)
        os.makedirs(TEST_REPORTS_DIR, exist_ok=True)

        # ======= 测试1: 项目总览 + 查询快照自动记录 =======
        print("\n" + "-" * 70)
        print("[1/10] 测试 项目总览 - 查询快照自动记录")
        print("-" * 70)

        proj = pm.create_project(name="小米Q2口碑调研", params=params)
        print(f"  创建项目: {proj.name} (ID: {proj.project_id})")

        posts, stats = fetch_posts_with_library(
            params, count=300, use_library=True, library=lib
        )
        result = analyze(posts, params)
        result_summary = {
            "current_posts": result.volume_analysis.time_range_posts,
            "previous_posts": result.volume_analysis.previous_range_posts,
            "volume_change": result.volume_analysis.volume_change_rate,
            "negative_ratio": result.volume_analysis.negative_ratio,
        }
        if result.theme_analysis.complaints:
            result_summary["top_complaint"] = f"{result.theme_analysis.complaints[0].keyword}({result.theme_analysis.complaints[0].count}次)"
        snap1 = pm.add_query_snapshot(proj, params, result_summary)
        print(f"  快照1: ID={snap1.snapshot_id}, 当前帖数={result_summary['current_posts']}, 负面占比={result_summary['negative_ratio']:.1f}%")

        proj_reloaded = pm.load_project(proj.project_id)
        assert len(proj_reloaded.query_snapshots) == 1, "应有1个查询快照！"
        assert proj_reloaded.query_snapshots[0].snapshot_id == snap1.snapshot_id
        print("  ✅ 通过（查询快照自动记录到项目）")

        # ======= 测试2: 多次查询快照 + 口碑变化趋势 =======
        print("\n" + "-" * 70)
        print("[2/10] 测试 多次查询快照 + 口碑变化趋势")
        print("-" * 70)

        params2 = QueryParams(
            target_brand="小米手机",
            competing_brands=["华为手机"],
            time_range=TimeRange(
                start_date=datetime.now() - timedelta(days=60),
                end_date=datetime.now(),
            ),
            focus_themes=["售后", "新品"],
        )
        posts2, _ = fetch_posts_with_library(
            params2, count=300, use_library=True, library=lib
        )
        result2 = analyze(posts2, params2)
        summary2 = {
            "current_posts": result2.volume_analysis.time_range_posts,
            "previous_posts": result2.volume_analysis.previous_range_posts,
            "volume_change": result2.volume_analysis.volume_change_rate,
            "negative_ratio": result2.volume_analysis.negative_ratio,
        }
        if result2.theme_analysis.complaints:
            summary2["top_complaint"] = f"{result2.theme_analysis.complaints[0].keyword}({result2.theme_analysis.complaints[0].count}次)"
        snap2 = pm.add_query_snapshot(proj, params2, summary2, notes="扩展到60天")
        print(f"  快照2: ID={snap2.snapshot_id}, 当前帖数={summary2['current_posts']}, 负面占比={summary2['negative_ratio']:.1f}%")

        proj_reloaded = pm.load_project(proj.project_id)
        assert len(proj_reloaded.query_snapshots) == 2, "应有2个查询快照！"
        assert proj_reloaded.query_snapshots[1].notes == "扩展到60天"
        print("  ✅ 通过（多次快照保存 + 备注）")

        # ======= 测试3: 项目进展纪要导出 =======
        print("\n" + "-" * 70)
        print("[3/10] 测试 项目进展纪要导出")
        print("-" * 70)

        progress_content = build_project_progress_minutes(proj_reloaded)
        assert "查询快照" in progress_content, "进展纪要应含查询快照章节！"
        assert "口碑变化趋势" in progress_content, "进展纪要应含口碑变化趋势（2个快照以上）！"
        assert "追问记录" in progress_content
        assert "导出纪要记录" in progress_content

        filepath = export_project_progress_minutes(proj_reloaded, output_dir=TEST_REPORTS_DIR)
        assert os.path.exists(filepath), "进展纪要文件应存在！"
        with open(filepath, "r", encoding="utf-8") as f:
            file_content = f.read()
        assert "调研项目进展纪要" in file_content
        assert "口碑变化趋势" in file_content
        print(f"  导出路径: {filepath}")
        print(f"  文件大小: {len(file_content)} 字符")
        print("  ✅ 通过（项目进展纪要结构完整，含跨快照对比）")

        # ======= 测试4: reuse 模式双周期样本稳定 =======
        print("\n" + "-" * 70)
        print("[4/10] 测试 reuse 模式双周期样本稳定 - 补采样后切回 reuse")
        print("-" * 70)

        _, _ = fetch_posts_with_library(
            params, count=300, use_library=True, library=lib, mode="resample"
        )

        posts_reuse_a, _ = fetch_posts_with_library(
            params, count=300, use_library=True, library=lib, mode="reuse"
        )
        result_reuse_a = analyze(posts_reuse_a, params)

        posts_reuse_b, _ = fetch_posts_with_library(
            params, count=300, use_library=True, library=lib, mode="reuse"
        )
        result_reuse_b = analyze(posts_reuse_b, params)

        print(f"  reuse-A: current={result_reuse_a.volume_analysis.time_range_posts}, previous={result_reuse_a.volume_analysis.previous_range_posts}")
        print(f"  reuse-B: current={result_reuse_b.volume_analysis.time_range_posts}, previous={result_reuse_b.volume_analysis.previous_range_posts}")

        assert result_reuse_a.volume_analysis.time_range_posts == result_reuse_b.volume_analysis.time_range_posts, "reuse两次当前周期帖数应一致！"
        assert result_reuse_a.volume_analysis.previous_range_posts == result_reuse_b.volume_analysis.previous_range_posts, "reuse两次上一周期帖数应一致！"
        assert result_reuse_a.volume_analysis.previous_range_posts > 0, "reuse模式应保留上一周期样本！"
        print("  ✅ 通过（reuse模式双周期样本稳定，上周期帖数>0）")

        # ======= 测试5: reuse 重启后结果一致 =======
        print("\n" + "-" * 70)
        print("[5/10] 测试 reuse 重启后数据一致性")
        print("-" * 70)

        ids_a = sorted(p.post_id for p in posts_reuse_a if p.brand == params.target_brand)
        import sample_library
        sample_library._global_library = None
        gc.collect()

        lib2 = SampleLibrary(db_path=TEST_DB_PATH)
        posts_restart, _ = fetch_posts_with_library(
            params, count=300, use_library=True, library=lib2, mode="reuse"
        )
        ids_restart = sorted(p.post_id for p in posts_restart if p.brand == params.target_brand)

        print(f"  原始ID数: {len(ids_a)}, 重启后ID数: {len(ids_restart)}")
        print(f"  ID集合完全一致: {ids_a == ids_restart}")
        assert ids_a == ids_restart, "重启后reuse模式样本ID应完全一致！"

        result_restart = analyze(posts_restart, params)
        assert result_restart.volume_analysis.time_range_posts == result_reuse_a.volume_analysis.time_range_posts
        assert result_restart.volume_analysis.previous_range_posts == result_reuse_a.volume_analysis.previous_range_posts
        print("  ✅ 通过（重启后reuse结果完全一致，环比/双周期帖数对齐）")

        # ======= 测试6: 空周期追问显示暂无提及 =======
        print("\n" + "-" * 70)
        print("[6/10] 测试 空周期追问 - 当前范围无帖子时显示暂无提及")
        print("-" * 70)

        future_params = QueryParams(
            target_brand="小米手机",
            competing_brands=[],
            time_range=TimeRange(
                start_date=datetime.now() + timedelta(days=365),
                end_date=datetime.now() + timedelta(days=395),
            ),
            focus_themes=["售后"],
        )
        future_posts, _ = fetch_posts_with_library(
            future_params, count=100, use_library=True, library=lib2, mode="reuse"
        )
        future_result = analyze(future_posts, future_params)
        print(f"  未来范围当前周期帖数: {len(future_result.current_range_posts)}")
        assert len(future_result.current_range_posts) == 0, "未来范围当前周期应为空！"

        analyzer = Analyzer()
        detail = analyzer.get_complaint_detail("售后", future_result)
        print(f"  追问结果: total_mentions={detail.total_mentions}, trend={detail.frequency_trend}")
        assert detail.total_mentions == 0, "空周期追问提及数应为0！"
        assert detail.frequency_trend == "当前范围暂无提及", "空周期追问趋势应提示暂无提及！"
        print("  ✅ 通过（空周期追问正确显示暂无提及，不拿上周期凑数）")

        # ======= 测试7: 会议纪要空周期口径同步 =======
        print("\n" + "-" * 70)
        print("[7/10] 测试 会议纪要 - 空周期口径同步（追踪问题跳过暂无提及）")
        print("-" * 70)

        report_gen = ReportGenerator()
        minutes = report_gen.build_meeting_minutes(future_result)
        for issue in minutes.tracking_issues:
            assert issue.related_count > 0, f"追踪问题「{issue.issue}」提及数应为0时不应出现在纪要中！"
        print(f"  追踪问题数: {len(minutes.tracking_issues)} (空周期应为0)")
        assert len(minutes.tracking_issues) == 0, "空周期不应有追踪问题！"
        print("  ✅ 通过（空周期时追踪问题正确跳过）")

        # ======= 测试8: 对比纪要证据附录 =======
        print("\n" + "-" * 70)
        print("[8/10] 测试 对比纪要证据附录 - 每品牌附可引用原帖摘要")
        print("-" * 70)

        comp = analyzer.compare_brands(
            all_posts=posts,
            target_brand=params.target_brand,
            competing_brands=params.competing_brands,
            time_range=params.time_range,
        )
        for row in comp.rows:
            print(f"  {row.brand}: evidence_posts={len(row.evidence_posts)}")
            assert len(row.evidence_posts) <= 3
            if row.total_posts > 0:
                assert len(row.evidence_posts) > 0, f"{row.brand} 有帖子时应有证据帖！"

        filepath = report_gen.export_comparison_minutes(comp, output_dir=TEST_REPORTS_DIR)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        assert "证据附录" in content, "对比纪要应包含证据附录章节！"
        assert "可引用原帖" in content, "证据附录应标注可引用原帖！"
        print(f"  导出路径: {filepath}")
        print(f"  文件大小: {len(content)} 字符")
        print("  ✅ 通过（对比纪要含证据附录，每品牌附原帖摘要+来源时间）")

        # ======= 测试9: 项目快照重启后保留 =======
        print("\n" + "-" * 70)
        print("[9/10] 测试 项目快照重启后保留")
        print("-" * 70)

        pm2 = ProjectManager(projects_dir=TEST_PROJECTS_DIR)
        proj_after = pm2.load_project(proj.project_id)
        assert proj_after is not None
        assert len(proj_after.query_snapshots) == 2, f"重启后应保留2个快照，实际{len(proj_after.query_snapshots)}！"
        assert proj_after.query_snapshots[0].result_summary.get("current_posts") == result_summary["current_posts"]
        assert proj_after.query_snapshots[1].notes == "扩展到60天"
        print(f"  重启后快照数: {len(proj_after.query_snapshots)}")
        print("  ✅ 通过（项目快照重启后完整保留）")

        # ======= 测试10: 继续查询 - 基于项目参数重新分析 =======
        print("\n" + "-" * 70)
        print("[10/10] 测试 继续查询 - 基于项目参数重新分析结果一致")
        print("-" * 70)

        proj_params = proj_after.query_params
        posts_continue, _ = fetch_posts_with_library(
            proj_params, count=300, use_library=True, library=lib2, mode="reuse"
        )
        result_continue = analyze(posts_continue, proj_params)
        print(f"  继续查询: current={result_continue.volume_analysis.time_range_posts}, previous={result_continue.volume_analysis.previous_range_posts}")
        assert result_continue.volume_analysis.time_range_posts == result_reuse_a.volume_analysis.time_range_posts, "继续查询当前周期应一致！"
        assert result_continue.volume_analysis.previous_range_posts == result_reuse_a.volume_analysis.previous_range_posts, "继续查询上一周期应一致！"
        print("  ✅ 通过（基于项目参数继续查询结果一致）")

        # ======= 清理 =======
        try:
            shutil.rmtree(TEST_REPORTS_DIR, ignore_errors=True)
        except Exception:
            pass

        print("\n" + "=" * 70)
        print("  🎉 v4 全部 10 项测试通过！")
        print("=" * 70)
        print("\n验证的新功能:")
        print("  ① 项目沉淀     → 查询快照自动记录，项目总览，继续查询，进展纪要导出")
        print("  ② 多次快照     → 口碑变化趋势跨快照对比")
        print("  ③ 样本复核     → reuse 按周期比例分配截断，补采样后双周期样本稳定")
        print("  ④ 口径纯净     → 空周期追问显示暂无提及，会议纪要追踪问题跳过")
        print("  ⑤ 证据附录     → 对比纪要每品牌附可引用原帖摘要+来源时间")
        print("\n下一步:")
        print("  python main.py --brand 小米手机 --competitors 华为手机,苹果手机 --days 30 --project 小米Q2调研 --export-compare --no-interactive")
        print("  python main.py (进入交互，输入「快照」「继续」「导出进展」体验v4新功能)")

    finally:
        cleanup_test_db()


if __name__ == "__main__":
    main()
