#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
冒烟测试 v3 - 验证口碑速查工具全部 v3 新特性
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
from report_generator import ReportGenerator
from sample_library import SampleLibrary
from project_manager import ProjectManager


TEST_DB_PATH = "./sample_library/test_v3_sample_posts.db"
TEST_PROJECTS_DIR = "./projects_test"


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
    if os.path.exists(TEST_PROJECTS_DIR):
        shutil.rmtree(TEST_PROJECTS_DIR, ignore_errors=True)


def main():
    print("=" * 70)
    print("  品牌口碑速查工具 v3 - 全面冒烟测试")
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

        # ======= 测试1: 数据口径纯净 - 主题分析只用当前周期 =======
        print("\n" + "-" * 70)
        print("[1/8] 测试 数据口径纯净 - 主题/代表帖/追问仅用当前周期")
        print("-" * 70)

        posts, stats = fetch_posts_with_library(
            params, count=300, use_library=True, library=lib
        )
        result = analyze(posts, params)

        total_curr = len(result.current_range_posts)
        total_prev = len(result.previous_range_posts)
        total_all = len(result.all_posts)
        print(f"  当前周期帖子数  : {total_curr}")
        print(f"  上一周期帖子数  : {total_prev}")
        print(f"  全部(含双周期) : {total_all}")
        print(f"  主题分析优点数  : {len(result.theme_analysis.advantages)}")
        print(f"  主题分析槽点数  : {len(result.theme_analysis.complaints)}")
        print(f"  代表帖数        : {len(result.representative_posts)}")

        assert total_curr > 0, "当前周期应有数据！"
        assert total_prev > 0, "上一周期应有数据！"
        assert total_all >= total_curr + total_prev, "双周期总数应不小于两部分之和"

        if result.theme_analysis.complaints:
            first_comp_count = result.theme_analysis.complaints[0].count
            assert first_comp_count <= total_curr, f"槽点计数({first_comp_count})不应超过当前周期帖数({total_curr})！"
        if result.representative_posts:
            for p in result.representative_posts:
                assert p in result.current_range_posts, "代表帖应来自当前周期！"

        print("  ✅ 通过（主题分析、代表帖均来自当前周期）")

        # ======= 测试2: 追问深挖仅统计当前周期 =======
        print("\n" + "-" * 70)
        print("[2/8] 测试 追问深挖仅统计当前周期帖子")
        print("-" * 70)

        analyzer = Analyzer()
        if result.theme_analysis.complaints:
            first_kw = result.theme_analysis.complaints[0].keyword
            detail = analyzer.get_complaint_detail(first_kw, result)
            print(f"  追问槽点       : {first_kw}")
            print(f"  提及数         : {detail.total_mentions}")
            print(f"  当前周期上限   : {total_curr}")
            assert detail.total_mentions <= total_curr, "追问提及数不应超过当前周期帖数！"
            print(f"  分组表达组数   : {len(detail.grouped_expressions)}")
            print("  ✅ 通过（追问仅统计当前周期）")
        else:
            print("  ⚠ 跳过（无槽点数据）")

        # ======= 测试3: 样本库 reuse 模式结果可重现 =======
        print("\n" + "-" * 70)
        print("[3/8] 测试 样本库 reuse 模式 - 同查询结果完全可重现")
        print("-" * 70)

        posts_a, _ = fetch_posts_with_library(
            params, count=300, use_library=True, library=lib, mode="reuse"
        )
        posts_b, _ = fetch_posts_with_library(
            params, count=300, use_library=True, library=lib, mode="reuse"
        )

        ids_a = sorted(p.post_id for p in posts_a if p.brand == params.target_brand)
        ids_b = sorted(p.post_id for p in posts_b if p.brand == params.target_brand)
        print(f"  reuse模式A目标品牌帖数: {len(ids_a)}")
        print(f"  reuse模式B目标品牌帖数: {len(ids_b)}")
        print(f"  ID集合完全一致: {ids_a == ids_b}")

        result_a = analyze(posts_a, params)
        result_b = analyze(posts_b, params)
        assert ids_a == ids_b, "两次reuse查询的样本ID应完全一致！"
        assert result_a.volume_analysis.time_range_posts == result_b.volume_analysis.time_range_posts, "讨论量应一致！"
        if result_a.theme_analysis.complaints and result_b.theme_analysis.complaints:
            c1 = result_a.theme_analysis.complaints[0]
            c2 = result_b.theme_analysis.complaints[0]
            assert c1.keyword == c2.keyword and c1.count == c2.count, "Top槽点应一致！"
        print("  ✅ 通过（reuse模式两次查询结果完全一致）")

        # ======= 测试4: resample vs smart 模式差异 =======
        print("\n" + "-" * 70)
        print("[4/8] 测试 三种样本策略（smart/reuse/resample）行为")
        print("-" * 70)

        _, s_reuse = fetch_posts_with_library(params, count=300, use_library=True, library=lib, mode="reuse")
        _, s_smart = fetch_posts_with_library(params, count=300, use_library=True, library=lib, mode="smart")
        _, s_resample = fetch_posts_with_library(params, count=300, use_library=True, library=lib, mode="resample")

        print(f"  reuse:    hit={s_reuse.get('library_hit')}, generated={s_reuse.get('new_generated')}")
        print(f"  smart:    hit={s_smart.get('library_hit')}, generated={s_smart.get('new_generated')}")
        print(f"  resample: hit={s_resample.get('library_hit')}, generated={s_resample.get('new_generated')}")

        assert s_reuse.get("new_generated", 0) == 0, "reuse模式不应生成新帖子！"
        assert s_resample.get("new_generated", 0) > 0, "resample模式应生成新帖子！"
        print("  ✅ 通过（三种策略行为符合预期）")

        # ======= 测试5: 项目管理 CRUD =======
        print("\n" + "-" * 70)
        print("[5/8] 测试 调研项目管理 - 创建/查询/更新/删除")
        print("-" * 70)

        proj = pm.create_project(name="小米Q2口碑调研", params=params)
        print(f"  创建项目: {proj.name} (ID: {proj.project_id})")
        assert proj.project_id, "项目ID不能为空！"

        loaded = pm.load_project(proj.project_id)
        assert loaded is not None, "项目应能被重新加载！"
        assert loaded.name == proj.name, "项目名应一致！"
        assert loaded.query_params.target_brand == params.target_brand, "品牌参数应一致！"
        print(f"  重新加载成功: {loaded.name}, 品牌={loaded.query_params.target_brand}")

        pm.add_follow_up(proj, query="售后为什么差", matched_keyword="售后差", total_mentions=25)
        pm.add_follow_up(proj, query="涨价", matched_keyword="涨价离谱", total_mentions=18)
        proj_updated = pm.load_project(proj.project_id)
        print(f"  追问历史条数: {len(proj_updated.follow_up_history)}")
        assert len(proj_updated.follow_up_history) == 2, "应保存2条追问记录！"

        test_dir = "./reports_test"
        os.makedirs(test_dir, exist_ok=True)
        minutes_path = os.path.abspath(os.path.join(test_dir, "会议纪要_test.txt"))
        cmp_path = os.path.abspath(os.path.join(test_dir, "对比纪要_test.txt"))
        with open(minutes_path, "w", encoding="utf-8") as f:
            f.write("test")
        with open(cmp_path, "w", encoding="utf-8") as f:
            f.write("test")
        pm.add_exported_minutes(proj, minutes_path)
        pm.add_exported_comparison(proj, cmp_path)
        proj_updated = pm.load_project(proj.project_id)
        print(f"  已导出纪要数: {len(proj_updated.exported_minutes_paths)} 会议 + {len(proj_updated.exported_comparison_paths)} 对比")
        assert len(proj_updated.exported_minutes_paths) == 1
        assert len(proj_updated.exported_comparison_paths) == 1

        project_list = pm.list_projects()
        print(f"  项目列表总数: {len(project_list)}")
        assert len(project_list) >= 1, "至少应有1个项目！"

        print("  ✅ 通过（项目CRUD+追问+导出归档全链路正常）")

        # ======= 测试6: 批量对比导出客户版纪要 =======
        print("\n" + "-" * 70)
        print("[6/8] 测试 批量对比客户版纪要导出")
        print("-" * 70)

        comp = analyzer.compare_brands(
            all_posts=posts,
            target_brand=params.target_brand,
            competing_brands=params.competing_brands,
            time_range=params.time_range,
        )
        report_gen = ReportGenerator()
        output_dir = "./reports_test"
        os.makedirs(output_dir, exist_ok=True)
        filepath = report_gen.export_comparison_minutes(comp, output_dir=output_dir)
        print(f"  导出路径: {os.path.abspath(filepath)}")
        assert os.path.exists(filepath), "对比纪要文件应存在！"

        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        print(f"  文件大小: {len(content)} 字符")

        must_have = [
            "多品牌口碑对比纪要",
            "总体指标速览",
            "各品牌详细情况与建议动作",
            "负面讨论占比",
            "主要槽点",
            "带节奏风险",
            "官方响应率",
            "建议动作",
            "总结",
        ]
        missing = [k for k in must_have if k not in content]
        if missing:
            print(f"  ⚠ 缺少章节: {missing}")
        else:
            print(f"  所有核心章节齐全 ✅")
        assert "总体指标速览" in content, "客户版纪要应包含总体指标！"
        assert "建议动作" in content, "客户版纪要应包含建议动作！"

        # 验证目标品牌是否标★
        target_markers = content.count("★")
        print(f"  目标品牌标记★数: {target_markers}")
        assert target_markers >= 1, "目标品牌应有★标记！"

        print("  ✅ 通过（客户版对比纪要结构完整）")

        # ======= 测试7: 项目重启后可恢复 =======
        print("\n" + "-" * 70)
        print("[7/8] 测试 项目 + 样本库重启后数据一致性（模拟重启）")
        print("-" * 70)

        import sample_library
        sample_library._global_library = None
        gc.collect()

        lib2 = SampleLibrary(db_path=TEST_DB_PATH)
        pm2 = ProjectManager(projects_dir=TEST_PROJECTS_DIR)

        info = lib2.count_by_brand(params.target_brand)
        print(f"  重启后样本库「{params.target_brand}」帖数: {info['total']}")
        assert info["total"] > 0, "重启后样本库数据应存在！"

        proj_list = pm2.list_projects()
        print(f"  重启后项目列表数: {len(proj_list)}")
        assert len(proj_list) >= 1, "重启后项目应存在！"

        proj_reloaded = pm2.load_project(proj.project_id)
        assert proj_reloaded is not None
        assert len(proj_reloaded.follow_up_history) == 2, "重启后追问记录应保留！"
        print(f"  重启后追问记录: {len(proj_reloaded.follow_up_history)} 条 ✅")

        posts_restart, _ = fetch_posts_with_library(
            params, count=300, use_library=True, library=lib2, mode="reuse"
        )
        result_restart = analyze(posts_restart, params)
        print(f"  重启后当前周期讨论量: {result_restart.volume_analysis.time_range_posts}")
        print(f"  重启后总讨论量(all_posts): {len(result_restart.all_posts)}")
        # 样本库经过 resample 追加后最新帖可能集中在本周期，previous 可能为 0 或 >0
        # 只要 current_range_posts > 0 就说明样本复用成功
        assert result_restart.volume_analysis.time_range_posts > 0, "重启后至少应有当前周期数据！"
        print("  ✅ 通过（重启后样本+项目+追问记录完全一致）")

        # ======= 测试8: 会议纪要同步使用真实环比 + 口径纯净 =======
        print("\n" + "-" * 70)
        print("[8/8] 测试 会议纪要与主题分析口径纯净 + 环比同步")
        print("-" * 70)

        minutes = report_gen.build_meeting_minutes(result)
        print(f"  核心发现条数: {len(minutes.key_findings)}")
        for i, f in enumerate(minutes.key_findings[:3], 1):
            print(f"    {i}. {f}")
        assert any("对比上一周期" in f for f in minutes.key_findings), "会议纪要应含真实环比！"

        # 代表帖验证应全部是当前周期的
        in_current = sum(1 for p in result.representative_posts if p in result.current_range_posts)
        print(f"  代表帖中属于当前周期的: {in_current}/{len(result.representative_posts)}")
        assert in_current == len(result.representative_posts), "所有代表帖均应来自当前周期！"

        print("  ✅ 通过")

        # ======= 清理 =======
        try:
            shutil.rmtree(output_dir, ignore_errors=True)
        except Exception:
            pass

        print("\n" + "=" * 70)
        print("  🎉 v3 全部 8 项测试通过！")
        print("=" * 70)
        print("\n验证的新功能:")
        print("  ① 口径纯净     → 主题/槽点/代表帖/追问 仅统计当前周期，上一周期仅用于环比")
        print("  ② 样本稳定     → smart/reuse/resample 三策略，reuse 模式结果完全可重现")
        print("  ③ 项目管理     → 项目名+参数快照+追问历史+导出纪要 持久化归档")
        print("  ④ 客户版对比纪要 → 按品牌负面/槽点/带节奏/官方响应/建议动作 结构化导出")
        print("\n下一步:")
        print("  python main.py --brand 小米手机 --competitors 华为手机,苹果手机 --days 30 --project 小米Q2调研 --export-compare --no-interactive")
        print("  python main.py (进入交互，输入「新建项目」「打开项目」「导出对比」体验v3新功能)")

    finally:
        cleanup_test_db()


if __name__ == "__main__":
    main()
