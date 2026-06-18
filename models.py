from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from enum import Enum


class SentimentType(Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    QUESTION = "question"


class PostType(Enum):
    MAIN_POST = "main_post"
    COMMENT = "comment"
    REPLY = "reply"


@dataclass
class Post:
    post_id: str
    title: str
    content: str
    author: str
    author_level: Optional[str] = None
    brand: str = ""
    source: str = ""
    source_type: str = ""
    post_type: PostType = PostType.MAIN_POST
    parent_id: Optional[str] = None
    publish_time: Optional[datetime] = None
    sentiment: SentimentType = SentimentType.NEUTRAL
    sentiment_score: float = 0.5
    likes: int = 0
    comments_count: int = 0
    views: int = 0
    themes: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    is_competing_brand_troll: bool = False
    competing_brand_ref: Optional[str] = None
    has_official_response: bool = False
    summary: str = ""
    representative_quotes: List[str] = field(default_factory=list)


@dataclass
class TimeRange:
    start_date: datetime
    end_date: datetime

    def __str__(self):
        return f"{self.start_date.strftime('%Y-%m-%d')} 至 {self.end_date.strftime('%Y-%m-%d')}"


@dataclass
class QueryParams:
    target_brand: str
    competing_brands: List[str] = field(default_factory=list)
    time_range: Optional[TimeRange] = None
    focus_themes: List[str] = field(default_factory=list)
    data_sources: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.focus_themes:
            self.focus_themes = [t.strip() for t in self.focus_themes if t.strip()]
        if self.competing_brands:
            self.competing_brands = [b.strip() for b in self.competing_brands if b.strip()]


@dataclass
class VolumeTrendPoint:
    date: datetime
    total_count: int = 0
    positive_count: int = 0
    negative_count: int = 0
    neutral_count: int = 0
    question_count: int = 0

    @property
    def negative_ratio(self) -> float:
        return self.negative_count / self.total_count if self.total_count > 0 else 0.0


@dataclass
class VolumeAnalysis:
    total_posts: int = 0
    time_range_posts: int = 0
    previous_range_posts: int = 0
    volume_change_rate: float = 0.0
    negative_ratio: float = 0.0
    previous_negative_ratio: float = 0.0
    negative_ratio_change: float = 0.0
    by_source: Dict[str, int] = field(default_factory=dict)
    by_theme: Dict[str, int] = field(default_factory=dict)
    trend_points: List[VolumeTrendPoint] = field(default_factory=list)


@dataclass
class ThemeKeyword:
    keyword: str
    count: int
    sentiment: SentimentType
    representative_post_ids: List[str] = field(default_factory=list)


@dataclass
class ThemeAnalysis:
    advantages: List[ThemeKeyword] = field(default_factory=list)
    complaints: List[ThemeKeyword] = field(default_factory=list)
    questions: List[ThemeKeyword] = field(default_factory=list)
    focus_theme_matches: Dict[str, List[ThemeKeyword]] = field(default_factory=dict)


@dataclass
class ExpressionGroup:
    group_key: str
    count: int
    examples: List[str] = field(default_factory=list)


@dataclass
class ComplaintDetail:
    complaint_keyword: str
    total_mentions: int
    matched_keyword: str = ""
    typical_expressions: List[Tuple[str, int]] = field(default_factory=list)
    grouped_expressions: List[ExpressionGroup] = field(default_factory=list)
    frequency_trend: str = ""
    is_competitor_troll: bool = False
    competitor_brand: Optional[str] = None
    troll_ratio: float = 0.0
    has_official_response: bool = False
    official_response_examples: List[str] = field(default_factory=list)
    source_distribution: Dict[str, int] = field(default_factory=dict)
    related_posts: List[Post] = field(default_factory=list)


@dataclass
class AnalysisResult:
    query_params: QueryParams
    volume_analysis: VolumeAnalysis = field(default_factory=VolumeAnalysis)
    theme_analysis: ThemeAnalysis = field(default_factory=ThemeAnalysis)
    representative_posts: List[Post] = field(default_factory=list)
    all_posts: List[Post] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.now)
    complaint_details_cache: Dict[str, ComplaintDetail] = field(default_factory=dict)


@dataclass
class MeetingMinutesItem:
    quote: str
    source: str
    sentiment: SentimentType
    related_theme: str


@dataclass
class TrackingIssue:
    issue: str
    priority: str
    related_count: int
    suggestion: str


@dataclass
class InterviewDirection:
    direction: str
    target_group: str
    questions: List[str]


@dataclass
class MeetingMinutes:
    title: str
    query_params: QueryParams
    generated_at: datetime
    key_findings: List[str] = field(default_factory=list)
    quotable_quotes: List[MeetingMinutesItem] = field(default_factory=list)
    tracking_issues: List[TrackingIssue] = field(default_factory=list)
    interview_directions: List[InterviewDirection] = field(default_factory=list)
    raw_analysis_ref: str = ""


@dataclass
class BrandComparisonRow:
    brand: str
    is_target: bool = False
    total_posts: int = 0
    negative_ratio: float = 0.0
    volume_change_rate: float = 0.0
    top_complaint: str = ""
    top_complaint_count: int = 0
    top_advantage: str = ""
    top_advantage_count: int = 0
    troll_ratio: float = 0.0
    official_response_ratio: float = 0.0
    risk_score: int = 0


@dataclass
class BatchComparisonResult:
    brands: List[str]
    target_brand: str
    time_range: Optional[TimeRange]
    rows: List[BrandComparisonRow] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.now)
    brand_results: Dict[str, AnalysisResult] = field(default_factory=dict)
