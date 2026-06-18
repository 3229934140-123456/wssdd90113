from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import re

from models import (
    Post, QueryParams, AnalysisResult, VolumeAnalysis,
    VolumeTrendPoint, ThemeAnalysis, ThemeKeyword, SentimentType,
    ComplaintDetail, TimeRange
)


class Analyzer:
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.top_n = self.config.get("analysis", {}).get("top_n_keywords", 15)

    def analyze(self, posts: List[Post], params: QueryParams) -> AnalysisResult:
        target_posts = [p for p in posts if p.brand == params.target_brand]

        result = AnalysisResult(
            query_params=params,
            all_posts=target_posts,
            generated_at=datetime.now(),
        )

        result.volume_analysis = self._analyze_volume(target_posts, params)
        result.theme_analysis = self._analyze_themes(target_posts, params)
        result.representative_posts = self._select_representative_posts(target_posts, params)

        return result

    def _analyze_volume(self, posts: List[Post], params: QueryParams) -> VolumeAnalysis:
        va = VolumeAnalysis()
        va.total_posts = len(posts)

        if params.time_range is None or len(posts) == 0:
            return va

        time_range = params.time_range
        in_range = [
            p for p in posts
            if p.publish_time and time_range.start_date <= p.publish_time <= time_range.end_date
        ]
        va.time_range_posts = len(in_range)

        range_days = max(1, (time_range.end_date - time_range.start_date).days)
        prev_start = time_range.start_date - timedelta(days=range_days)
        prev_end = time_range.start_date - timedelta(seconds=1)
        prev_range = [
            p for p in posts
            if p.publish_time and prev_start <= p.publish_time <= prev_end
        ]
        va.previous_range_posts = len(prev_range)

        if va.previous_range_posts > 0:
            va.volume_change_rate = (va.time_range_posts - va.previous_range_posts) / va.previous_range_posts * 100
        elif va.time_range_posts > 0:
            va.volume_change_rate = 100.0

        if va.time_range_posts > 0:
            va.negative_ratio = sum(1 for p in in_range if p.sentiment == SentimentType.NEGATIVE) / va.time_range_posts * 100
        if va.previous_range_posts > 0:
            va.previous_negative_ratio = sum(1 for p in prev_range if p.sentiment == SentimentType.NEGATIVE) / va.previous_range_posts * 100
        va.negative_ratio_change = va.negative_ratio - va.previous_negative_ratio

        source_counter = Counter(p.source for p in in_range if p.source)
        va.by_source = dict(source_counter.most_common())

        theme_counter: Counter = Counter()
        for p in in_range:
            for t in p.themes:
                theme_counter[t] += 1
        va.by_theme = dict(theme_counter.most_common(self.top_n))

        va.trend_points = self._build_trend_points(in_range, time_range)

        return va

    def _build_trend_points(self, posts: List[Post], time_range: TimeRange) -> List[VolumeTrendPoint]:
        total_days = max(1, (time_range.end_date - time_range.start_date).days)
        num_buckets = min(total_days, 7)
        bucket_days = max(1, total_days // num_buckets)

        points: List[VolumeTrendPoint] = []
        for i in range(num_buckets):
            bucket_start = time_range.start_date + timedelta(days=i * bucket_days)
            if i == num_buckets - 1:
                bucket_end = time_range.end_date
            else:
                bucket_end = time_range.start_date + timedelta(days=(i + 1) * bucket_days) - timedelta(seconds=1)

            tp = VolumeTrendPoint(date=bucket_start)
            for p in posts:
                if p.publish_time and bucket_start <= p.publish_time <= bucket_end:
                    tp.total_count += 1
                    if p.sentiment == SentimentType.POSITIVE:
                        tp.positive_count += 1
                    elif p.sentiment == SentimentType.NEGATIVE:
                        tp.negative_count += 1
                    elif p.sentiment == SentimentType.QUESTION:
                        tp.question_count += 1
                    else:
                        tp.neutral_count += 1
            points.append(tp)
        return points

    def _analyze_themes(self, posts: List[Post], params: QueryParams) -> ThemeAnalysis:
        ta = ThemeAnalysis()

        pos_kw: Dict[str, Tuple[Counter, List[str]]] = defaultdict(lambda: (Counter(), []))
        neg_kw: Dict[str, Tuple[Counter, List[str]]] = defaultdict(lambda: (Counter(), []))
        q_kw: Dict[str, Tuple[Counter, List[str]]] = defaultdict(lambda: (Counter(), []))

        for p in posts:
            for kw in p.keywords:
                if not kw:
                    continue
                if p.sentiment == SentimentType.POSITIVE:
                    pos_kw[kw][0][kw] += 1
                    pos_kw[kw][1].append(p.post_id)
                elif p.sentiment == SentimentType.NEGATIVE:
                    neg_kw[kw][0][kw] += 1
                    neg_kw[kw][1].append(p.post_id)
                elif p.sentiment == SentimentType.QUESTION:
                    q_kw[kw][0][kw] += 1
                    q_kw[kw][1].append(p.post_id)

        ta.advantages = [
            ThemeKeyword(
                keyword=kw,
                count=sum(cnt.values()),
                sentiment=SentimentType.POSITIVE,
                representative_post_ids=pids[:5],
            )
            for kw, (cnt, pids) in sorted(pos_kw.items(), key=lambda x: sum(x[1][0].values()), reverse=True)[:self.top_n]
        ]

        ta.complaints = [
            ThemeKeyword(
                keyword=kw,
                count=sum(cnt.values()),
                sentiment=SentimentType.NEGATIVE,
                representative_post_ids=pids[:5],
            )
            for kw, (cnt, pids) in sorted(neg_kw.items(), key=lambda x: sum(x[1][0].values()), reverse=True)[:self.top_n]
        ]

        ta.questions = [
            ThemeKeyword(
                keyword=kw,
                count=sum(cnt.values()),
                sentiment=SentimentType.QUESTION,
                representative_post_ids=pids[:5],
            )
            for kw, (cnt, pids) in sorted(q_kw.items(), key=lambda x: sum(x[1][0].values()), reverse=True)[:self.top_n]
        ]

        if params.focus_themes:
            for theme in params.focus_themes:
                matches: List[ThemeKeyword] = []
                for source_list in [ta.advantages, ta.complaints, ta.questions]:
                    for tk in source_list:
                        if theme in tk.keyword or tk.keyword in theme:
                            matches.append(tk)
                if matches:
                    ta.focus_theme_matches[theme] = matches

        return ta

    def _select_representative_posts(self, posts: List[Post], params: QueryParams) -> List[Post]:
        max_posts = self.config.get("output", {}).get("max_representative_posts", 8)
        focus_set = set(params.focus_themes) if params.focus_themes else set()

        scored: List[Tuple[int, Post]] = []
        for p in posts:
            score = 0
            score += p.likes * 2
            score += p.comments_count * 5
            score += min(p.views // 100, 100)
            if p.post_type.value == "main_post":
                score += 50
            theme_hits = len(set(p.themes) & focus_set)
            score += theme_hits * 100
            scored.append((score, p))

        scored.sort(key=lambda x: x[0], reverse=True)

        selected: List[Post] = []
        themes_covered: set = set()
        sentiment_covered: Dict[SentimentType, int] = defaultdict(int)
        target_sentiments = {
            SentimentType.POSITIVE: max(2, max_posts // 4),
            SentimentType.NEGATIVE: max(3, max_posts // 3),
            SentimentType.QUESTION: max(1, max_posts // 5),
            SentimentType.NEUTRAL: max(1, max_posts // 5),
        }

        for _, p in scored:
            if sentiment_covered[p.sentiment] >= target_sentiments.get(p.sentiment, 2):
                if len(selected) >= max_posts:
                    break
                continue
            selected.append(p)
            sentiment_covered[p.sentiment] += 1
            themes_covered.update(p.themes)
            if len(selected) >= max_posts:
                break

        if len(selected) < max_posts:
            seen_ids = {p.post_id for p in selected}
            for _, p in scored:
                if p.post_id not in seen_ids:
                    selected.append(p)
                    seen_ids.add(p.post_id)
                    if len(selected) >= max_posts:
                        break

        return selected

    def get_complaint_detail(
        self,
        keyword: str,
        analysis_result: AnalysisResult,
    ) -> ComplaintDetail:
        if keyword in analysis_result.complaint_details_cache:
            return analysis_result.complaint_details_cache[keyword]

        posts = analysis_result.all_posts
        matched_posts = [
            p for p in posts
            if p.sentiment == SentimentType.NEGATIVE and any(
                keyword in kw or kw in keyword for kw in p.keywords
            )
        ]

        detail = ComplaintDetail(
            complaint_keyword=keyword,
            total_mentions=len(matched_posts),
            related_posts=matched_posts,
        )

        expression_counter: Counter = Counter()
        source_counter: Counter = Counter()
        troll_count = 0
        competitor_brands: Counter = Counter()
        official_resp_count = 0

        for p in matched_posts:
            expr = p.summary
            if expr:
                expression_counter[expr] += 1
            if p.source:
                source_counter[p.source] += 1
            if p.is_competing_brand_troll:
                troll_count += 1
                if p.competing_brand_ref:
                    competitor_brands[p.competing_brand_ref] += 1
            if p.has_official_response:
                official_resp_count += 1
                for quote in p.representative_quotes[1:]:
                    if quote and quote not in detail.official_response_examples:
                        detail.official_response_examples.append(quote)

        detail.typical_expressions = expression_counter.most_common(8)
        detail.source_distribution = dict(source_counter.most_common())
        detail.is_competitor_troll = troll_count > 0
        if competitor_brands:
            detail.competitor_brand = competitor_brands.most_common(1)[0][0]
        detail.troll_ratio = troll_count / len(matched_posts) * 100 if matched_posts else 0.0
        detail.has_official_response = official_resp_count > 0

        if analysis_result.query_params.time_range and matched_posts:
            tr = analysis_result.query_params.time_range
            total_days = max(1, (tr.end_date - tr.start_date).days)
            mid = tr.start_date + timedelta(days=total_days / 2)
            first_half = sum(1 for p in matched_posts if p.publish_time and p.publish_time < mid)
            second_half = sum(1 for p in matched_posts if p.publish_time and p.publish_time >= mid)
            if first_half == 0 and second_half > 0:
                detail.frequency_trend = "骤升"
            elif second_half > first_half * 1.5:
                detail.frequency_trend = "上升"
            elif second_half < first_half * 0.5:
                detail.frequency_trend = "下降"
            else:
                detail.frequency_trend = "平稳"
        else:
            detail.frequency_trend = "数据不足"

        analysis_result.complaint_details_cache[keyword] = detail
        return detail


def analyze(posts: List[Post], params: QueryParams, config: Optional[Dict] = None) -> AnalysisResult:
    analyzer = Analyzer(config=config)
    return analyzer.analyze(posts, params)
