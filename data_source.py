import random
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import uuid

from models import (
    Post, QueryParams, SentimentType, PostType,
    TimeRange
)
from sample_library import SampleLibrary, get_library


BRAND_TEMPLATES: Dict[str, Dict] = {
    "_default": {
        "advantages": [
            ("性价比高", ["性价比真的高", "同价位里最划算", "预算有限选它没错", "价格亲民配置不低"]),
            ("外观设计", ["颜值在线", "设计感很强", "拿在手里很有质感", "外观高级"]),
            ("使用体验好", ["用起来很顺手", "体验感拉满", "上手零难度", "用着舒服"]),
            ("质量可靠", ["用了好几年没坏", "做工扎实", "质量杠杠的", "耐造得很"]),
            ("功能实用", ["功能很实用", "该有的都有", "日常使用完全够用", "功能齐全"]),
            ("售后服务好", ["客服态度好", "售后响应快", "保修很方便", "服务周到"]),
        ],
        "complaints": [
            ("售后差", ["售后就是摆设", "客服根本不理人", "保修踢皮球", "维修要等一个月"]),
            ("涨价离谱", ["又涨价了？", "这价格谁买得起", "割韭菜呢", "一年涨三回"]),
            ("新品翻车", ["新品品控有问题", "新批次质量下降", "新款不如老款", "升级像降级"]),
            ("续航拉胯", ["续航太短了", "一天三充", "电量掉得飞快", "续航尿崩"]),
            ("发热严重", ["用一会儿就发烫", "冬天暖手宝", "热得能煎蛋", "散热不行"]),
            ("系统卡顿", ["用半年就卡", "越更新越慢", "流畅度不够", "卡成PPT"]),
            ("虚假宣传", ["宣传与实际不符", "参数党慎入", "营销过头了", "吹得太狠"]),
            ("包装简陋", ["包装像二手", "拆箱体验差", "运输途中就坏了", "配件缺失"]),
        ],
        "questions": [
            ("新品什么时候出", ["新品有消息吗", "下一代什么时候发布", "求爆料新款"]),
            ("会不会降价", ["618能降多少", "最近有活动吗", "双十一会不会跳水"]),
            ("和竞品哪个好", ["和竞品相比怎么样", "买哪个更值", "求对比测评"]),
            ("保修政策", ["保修多久", "碎屏险值得买吗", "延保要不要"]),
            ("哪里买靠谱", ["哪个渠道是正品", "官网还是第三方", "怕买到翻新"]),
        ],
        "titles_positive": [
            "{brand}用了三个月，说点真心话",
            "终于入手{brand}，真香警告",
            "{brand}这次真的用心了",
            "老用户谈谈{brand}这些年的变化",
            "被{brand}圈粉了",
            "分享一下{brand}的使用心得",
        ],
        "titles_negative": [
            "{brand}一生黑，再也不买了",
            "求助！{brand}售后太气人了",
            "{brand}是不是飘了？质量下滑严重",
            "买{brand}后悔了，劝大家慎重",
            "{brand}涨价是认真的吗？",
            "吐槽一下{brand}的新品品控",
        ],
        "titles_question": [
            "想入手{brand}，求老用户建议",
            "{brand}和竞品怎么选？",
            "问下{brand}的保修政策",
            "{brand}新品什么时候发布？",
            "{brand}最近有没有活动？",
            "{brand}哪个版本值得买？",
        ],
        "titles_neutral": [
            "{brand}近期讨论汇总",
            "{brand}相关问题整理",
            "{brand}使用经验分享贴",
            "关于{brand}的一些观察",
        ],
    }
}


COMPETITOR_TROLL_EXPRESSIONS = [
    "（还是选{competitor}吧，性价比高多了）",
    "我早就换{competitor}了，真香",
    "{competitor}用户表示笑而不语",
    "这就是不选{competitor}的下场",
    "早说了{competitor}更好，不听",
    "{competitor}就没这问题",
]


OFFICIAL_RESPONSES = [
    "亲亲，非常抱歉给您带来不好的体验，麻烦私信一下您的订单号，我们马上为您处理~",
    "感谢您的反馈，我们已将此问题转交给相关部门，会尽快给您答复。",
    "您好，针对您反映的问题，我们的客服正在跟进，请保持电话畅通。",
    "感谢您对{brand}的关注，关于新品的信息请以官方公告为准哦~",
]


FORUM_SOURCES = [
    ("百度贴吧", "tieba"),
    ("知乎话题", "zhihu"),
    ("小红书笔记", "xiaohongshu"),
    ("微博话题", "weibo"),
    ("NGA玩家社区", "nga"),
]


AUTHOR_NAMES = [
    "路人甲", "数码爱好者", "老用户一枚", "萌新求带", "理性消费者",
    "资深玩家", "佛系测评", "剁手党", "等等党", "学生党",
    "上班族小王", "产品经理李", "程序员张", "设计师陈", "宝妈刘",
    "小白用户", "硬核玩家", "种草达人", "拔草专业户", "客观中立党",
]


AUTHOR_LEVELS = [
    "LV1 新手上路", "LV3 初级会员", "LV5 中级会员",
    "LV7 高级会员", "LV9 金牌会员", "LV12 论坛元老",
    "普通用户", "核心用户", "认证用户",
]


class DataSourceSimulator:
    def __init__(self, seed: Optional[int] = None):
        self._seed = seed
        if seed is not None:
            random.seed(seed)

    def _get_template(self, brand: str) -> Dict:
        if brand in BRAND_TEMPLATES:
            return BRAND_TEMPLATES[brand]
        return BRAND_TEMPLATES["_default"]

    def _generate_content(
        self,
        brand: str,
        sentiment: SentimentType,
        focus_themes: List[str],
        competing_brands: List[str],
    ) -> Tuple[str, List[str], str, Optional[str], bool]:
        template = self._get_template(brand)
        content_parts: List[str] = []
        keywords: List[str] = []
        summary = ""
        competitor_ref: Optional[str] = None
        is_troll = False

        if sentiment == SentimentType.POSITIVE:
            pool = template["advantages"]
            if focus_themes:
                theme_pool = [(kw, exps) for kw, exps in pool if any(t in kw or kw in t for t in focus_themes)]
                if theme_pool:
                    pool = theme_pool
            num_points = random.randint(1, 3)
            selected = random.sample(pool, min(num_points, len(pool)))
            for kw, expressions in selected:
                keywords.append(kw)
                expr = random.choice(expressions)
                content_parts.append(expr)
                if len(expressions) > 1 and random.random() < 0.4:
                    content_parts.append("另外" + random.choice([e for e in expressions if e != expr]))

        elif sentiment == SentimentType.NEGATIVE:
            pool = template["complaints"]
            if focus_themes:
                theme_pool = [(kw, exps) for kw, exps in pool if any(t in kw or kw in t for t in focus_themes)]
                if theme_pool:
                    pool = theme_pool
            num_points = random.randint(1, 2)
            selected = random.sample(pool, min(num_points, len(pool)))
            for kw, expressions in selected:
                keywords.append(kw)
                expr = random.choice(expressions)
                content_parts.append(expr)
                if random.random() < 0.3 and len(expressions) > 1:
                    content_parts.append("而且" + random.choice([e for e in expressions if e != expr]))

            if competing_brands and random.random() < 0.3:
                is_troll = True
                competitor_ref = random.choice(competing_brands)
                troll_expr = random.choice(COMPETITOR_TROLL_EXPRESSIONS).format(competitor=competitor_ref)
                content_parts.append(troll_expr)

        elif sentiment == SentimentType.QUESTION:
            pool = template["questions"]
            if focus_themes:
                theme_pool = [(kw, exps) for kw, exps in pool if any(t in kw or kw in t for t in focus_themes)]
                if theme_pool:
                    pool = theme_pool
            selected = random.choice(pool)
            keywords.append(selected[0])
            content_parts.append(random.choice(selected[1]))
            if random.random() < 0.5:
                extra = random.choice(["求各位大佬解答", "有经验的来说说", "先谢谢大家了"])
                content_parts.append(extra)

        else:
            content_parts.append(f"最近在关注{brand}，看了很多讨论，想整理一下思路。")
            if focus_themes:
                content_parts.append(f"主要想了解一下关于{'、'.join(focus_themes)}方面的信息。")

        content = "，".join(content_parts) + "。"
        summary = content[:80] + ("..." if len(content) > 80 else "")
        return content, keywords, summary, competitor_ref, is_troll

    def _generate_title(self, brand: str, sentiment: SentimentType, focus_themes: List[str]) -> str:
        template = self._get_template(brand)
        if sentiment == SentimentType.POSITIVE:
            title = random.choice(template["titles_positive"])
        elif sentiment == SentimentType.NEGATIVE:
            title = random.choice(template["titles_negative"])
        elif sentiment == SentimentType.QUESTION:
            title = random.choice(template["titles_question"])
        else:
            title = random.choice(template["titles_neutral"])
        return title.format(brand=brand)

    def _pick_sentiment(
        self,
        brand: str,
        focus_themes: List[str],
    ) -> SentimentType:
        weights = [0.30, 0.35, 0.20, 0.15]
        negative_themes = ["售后", "涨价", "发热", "卡顿", "翻车", "虚假"]
        if any(any(nt in t for nt in negative_themes) for t in focus_themes):
            weights = [0.15, 0.55, 0.15, 0.15]
        return random.choices(
            [SentimentType.POSITIVE, SentimentType.NEGATIVE, SentimentType.NEUTRAL, SentimentType.QUESTION],
            weights=weights, k=1
        )[0]

    def _generate_posts_for_range(
        self,
        brand: str,
        time_range: TimeRange,
        count: int,
        focus_themes: List[str],
        competing_brands: List[str],
        data_sources: List[str],
    ) -> List[Post]:
        posts: List[Post] = []
        total_days = max(1, (time_range.end_date - time_range.start_date).days)

        for _ in range(count):
            sentiment = self._pick_sentiment(brand, focus_themes)
            source_name, source_type = random.choice(FORUM_SOURCES)
            if data_sources and source_name not in data_sources:
                continue

            random_days = random.uniform(0, total_days)
            publish_time = time_range.start_date + timedelta(days=random_days)
            publish_time = publish_time.replace(
                hour=random.randint(0, 23),
                minute=random.randint(0, 59),
                second=random.randint(0, 59)
            )

            content, keywords, summary, comp_ref, is_troll = self._generate_content(
                brand=brand,
                sentiment=sentiment,
                focus_themes=focus_themes,
                competing_brands=competing_brands,
            )

            title = self._generate_title(brand, sentiment, focus_themes)

            sentiment_score_map = {
                SentimentType.POSITIVE: random.uniform(0.65, 0.95),
                SentimentType.NEGATIVE: random.uniform(0.05, 0.35),
                SentimentType.NEUTRAL: random.uniform(0.45, 0.55),
                SentimentType.QUESTION: random.uniform(0.40, 0.60),
            }

            has_official_resp = False
            official_resp_examples: List[str] = []
            if sentiment == SentimentType.NEGATIVE and random.random() < 0.2:
                has_official_resp = True
                official_resp_examples.append(random.choice(OFFICIAL_RESPONSES).format(brand=brand))

            themes = list(set(keywords + ([t for t in focus_themes if any(t in kw or kw in t for kw in keywords)] if focus_themes else [])))

            post = Post(
                post_id=str(uuid.uuid4())[:8],
                title=title,
                content=content,
                author=random.choice(AUTHOR_NAMES),
                author_level=random.choice(AUTHOR_LEVELS),
                brand=brand,
                source=source_name,
                source_type=source_type,
                post_type=PostType.MAIN_POST if random.random() < 0.7 else PostType.COMMENT,
                parent_id=None,
                publish_time=publish_time,
                sentiment=sentiment,
                sentiment_score=sentiment_score_map[sentiment],
                likes=random.randint(0, 500) if sentiment in (SentimentType.POSITIVE, SentimentType.NEGATIVE) else random.randint(0, 50),
                comments_count=random.randint(0, 200),
                views=random.randint(100, 50000),
                themes=themes,
                keywords=keywords,
                is_competing_brand_troll=is_troll,
                competing_brand_ref=comp_ref,
                has_official_response=has_official_resp,
                summary=summary,
                representative_quotes=[summary] + official_resp_examples,
            )
            posts.append(post)
        return posts

    def fetch_posts_with_library(
        self,
        params: QueryParams,
        count: int = 200,
        library: Optional[SampleLibrary] = None,
        use_library: bool = True,
    ) -> Tuple[List[Post], Dict]:
        """
        生成/获取双周期数据：前一周期 + 当前周期，保证环比有意义。
        优先从离线样本库中按品牌+时间范围读取，不足部分生成后入库。
        """
        if params.time_range is None:
            end = datetime.now()
            start = end - timedelta(days=30)
            time_range = TimeRange(start_date=start, end_date=end)
        else:
            time_range = params.time_range

        range_days = max(1, (time_range.end_date - time_range.start_date).days)
        prev_start = time_range.start_date - timedelta(days=range_days)
        prev_end = time_range.start_date - timedelta(seconds=1)
        full_start = prev_start
        full_end = time_range.end_date
        full_range = TimeRange(start_date=full_start, end_date=full_end)

        brands_to_collect = [params.target_brand] + params.competing_brands
        sources_filter = params.data_sources or []

        lib_stats = {"library_hit": 0, "new_generated": 0, "saved": 0}
        all_posts: List[Post] = []

        if use_library:
            if library is None:
                library = get_library()
            existing = library.fetch_by_brands_and_time(
                brands=brands_to_collect,
                start_date=full_start,
                end_date=full_end,
                sources=sources_filter if sources_filter else None,
            )
            all_posts.extend(existing)
            lib_stats["library_hit"] = len(existing)

        for brand in brands_to_collect:
            target_share = 0.6 if brand == params.target_brand else 0.4 / max(1, len(params.competing_brands))
            desired_count = int(count * target_share)

            existing_for_brand = [p for p in all_posts if p.brand == brand]
            if len(existing_for_brand) >= desired_count:
                continue
            need_count = desired_count - len(existing_for_brand)

            current_count_current = int(need_count * 0.55)
            current_count_prev = need_count - current_count_current

            competing = params.competing_brands if brand == params.target_brand else []

            new_current = self._generate_posts_for_range(
                brand=brand,
                time_range=time_range,
                count=current_count_current,
                focus_themes=params.focus_themes,
                competing_brands=competing,
                data_sources=sources_filter,
            )
            prev_tr = TimeRange(start_date=prev_start, end_date=prev_end)
            new_prev = self._generate_posts_for_range(
                brand=brand,
                time_range=prev_tr,
                count=current_count_prev,
                focus_themes=params.focus_themes,
                competing_brands=competing,
                data_sources=sources_filter,
            )

            new_posts = new_current + new_prev
            all_posts.extend(new_posts)
            lib_stats["new_generated"] += len(new_posts)

            if use_library and library is not None and new_posts:
                saved = library.save_posts(new_posts)
                lib_stats["saved"] += saved

        all_posts.sort(key=lambda p: p.publish_time or datetime.now(), reverse=True)
        return all_posts, lib_stats

    def fetch_posts(self, params: QueryParams, count: int = 200) -> List[Post]:
        posts, _ = self.fetch_posts_with_library(params, count=count, use_library=False)
        return posts


def fetch_posts(params: QueryParams, count: int = 200, seed: Optional[int] = None) -> List[Post]:
    simulator = DataSourceSimulator(seed=seed)
    return simulator.fetch_posts(params, count=count)


def fetch_posts_with_library(
    params: QueryParams,
    count: int = 200,
    seed: Optional[int] = None,
    use_library: bool = True,
    library: Optional[SampleLibrary] = None,
) -> Tuple[List[Post], Dict]:
    simulator = DataSourceSimulator(seed=seed)
    return simulator.fetch_posts_with_library(params, count=count, use_library=use_library, library=library)
