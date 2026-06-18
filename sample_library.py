import sqlite3
import json
import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import uuid

from models import (
    Post, QueryParams, SentimentType, PostType, TimeRange
)


DEFAULT_DB_PATH = "./sample_library/sample_posts.db"


class SampleLibrary:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    post_id TEXT PRIMARY KEY,
                    brand TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_type TEXT,
                    title TEXT,
                    content TEXT,
                    author TEXT,
                    author_level TEXT,
                    post_type TEXT,
                    parent_id TEXT,
                    publish_time TEXT,
                    sentiment TEXT,
                    sentiment_score REAL,
                    likes INTEGER DEFAULT 0,
                    comments_count INTEGER DEFAULT 0,
                    views INTEGER DEFAULT 0,
                    themes TEXT,
                    keywords TEXT,
                    is_competing_brand_troll INTEGER DEFAULT 0,
                    competing_brand_ref TEXT,
                    has_official_response INTEGER DEFAULT 0,
                    summary TEXT,
                    representative_quotes TEXT,
                    inserted_at TEXT,
                    fingerprint TEXT UNIQUE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_brand ON posts(brand)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_source ON posts(source)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_publish ON posts(publish_time)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_brand_publish ON posts(brand, publish_time)")
            conn.commit()

    @staticmethod
    def _make_fingerprint(p: Post) -> str:
        import hashlib
        raw = f"{p.brand}|{p.source}|{p.title[:30]}|{p.content[:50]}|{p.author}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _row_to_post(row: sqlite3.Row) -> Post:
        sentiment_map = {e.value: e for e in SentimentType}
        post_type_map = {e.value: e for e in PostType}
        publish_time = None
        if row["publish_time"]:
            try:
                publish_time = datetime.fromisoformat(row["publish_time"])
            except ValueError:
                pass

        themes = json.loads(row["themes"]) if row["themes"] else []
        keywords = json.loads(row["keywords"]) if row["keywords"] else []
        representative_quotes = json.loads(row["representative_quotes"]) if row["representative_quotes"] else []

        return Post(
            post_id=row["post_id"],
            title=row["title"] or "",
            content=row["content"] or "",
            author=row["author"] or "",
            author_level=row["author_level"],
            brand=row["brand"],
            source=row["source"] or "",
            source_type=row["source_type"] or "",
            post_type=post_type_map.get(row["post_type"], PostType.MAIN_POST),
            parent_id=row["parent_id"],
            publish_time=publish_time,
            sentiment=sentiment_map.get(row["sentiment"], SentimentType.NEUTRAL),
            sentiment_score=row["sentiment_score"] or 0.5,
            likes=row["likes"] or 0,
            comments_count=row["comments_count"] or 0,
            views=row["views"] or 0,
            themes=themes,
            keywords=keywords,
            is_competing_brand_troll=bool(row["is_competing_brand_troll"]),
            competing_brand_ref=row["competing_brand_ref"],
            has_official_response=bool(row["has_official_response"]),
            summary=row["summary"] or "",
            representative_quotes=representative_quotes,
        )

    @staticmethod
    def _post_to_values(p: Post) -> Tuple:
        fingerprint = SampleLibrary._make_fingerprint(p)
        return (
            p.post_id or str(uuid.uuid4())[:8],
            p.brand,
            p.source,
            p.source_type,
            p.title,
            p.content,
            p.author,
            p.author_level,
            p.post_type.value,
            p.parent_id,
            p.publish_time.isoformat() if p.publish_time else None,
            p.sentiment.value,
            p.sentiment_score,
            p.likes,
            p.comments_count,
            p.views,
            json.dumps(p.themes, ensure_ascii=False),
            json.dumps(p.keywords, ensure_ascii=False),
            1 if p.is_competing_brand_troll else 0,
            p.competing_brand_ref,
            1 if p.has_official_response else 0,
            p.summary,
            json.dumps(p.representative_quotes, ensure_ascii=False),
            datetime.now().isoformat(),
            fingerprint,
        )

    def fetch_by_brands_and_time(
        self,
        brands: List[str],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        sources: Optional[List[str]] = None,
    ) -> List[Post]:
        if not brands:
            return []

        placeholders = ",".join(["?"] * len(brands))
        sql = f"SELECT * FROM posts WHERE brand IN ({placeholders})"
        params: list = list(brands)

        if start_date:
            sql += " AND publish_time >= ?"
            params.append(start_date.isoformat())
        if end_date:
            sql += " AND publish_time <= ?"
            params.append(end_date.isoformat())
        if sources:
            src_holders = ",".join(["?"] * len(sources))
            sql += f" AND source IN ({src_holders})"
            params.extend(sources)

        sql += " ORDER BY publish_time DESC"

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_post(r) for r in rows]

    def save_posts(self, posts: List[Post]) -> int:
        if not posts:
            return 0
        inserted = 0
        with self._connect() as conn:
            for p in posts:
                values = self._post_to_values(p)
                try:
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO posts (
                            post_id, brand, source, source_type, title, content,
                            author, author_level, post_type, parent_id, publish_time,
                            sentiment, sentiment_score, likes, comments_count, views,
                            themes, keywords, is_competing_brand_troll, competing_brand_ref,
                            has_official_response, summary, representative_quotes,
                            inserted_at, fingerprint
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        values,
                    )
                    if cur.rowcount and cur.rowcount > 0:
                        inserted += 1
                except Exception:
                    continue
            conn.commit()
        return inserted

    def count_by_brand(self, brand: str) -> Dict[str, int]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM posts WHERE brand=?",
                (brand,)
            ).fetchone()
            total = row["total"] if row else 0

            by_src = {}
            rows = conn.execute(
                "SELECT source, COUNT(*) AS cnt FROM posts WHERE brand=? GROUP BY source",
                (brand,)
            ).fetchall()
            for r in rows:
                by_src[r["source"]] = r["cnt"]

            sent_dist = {}
            rows = conn.execute(
                "SELECT sentiment, COUNT(*) AS cnt FROM posts WHERE brand=? GROUP BY sentiment",
                (brand,)
            ).fetchall()
            for r in rows:
                sent_dist[r["sentiment"]] = r["cnt"]

            return {"total": total, "by_source": by_src, "by_sentiment": sent_dist}

    def clear_brand(self, brand: str) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM posts WHERE brand=?", (brand,))
            conn.commit()
            return cur.rowcount

    def list_brands(self) -> List[Tuple[str, int, Optional[str]]]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT brand, COUNT(*) AS cnt, MAX(publish_time) AS latest
                FROM posts GROUP BY brand ORDER BY cnt DESC
            """).fetchall()
            return [(r["brand"], r["cnt"], r["latest"]) for r in rows]


_global_library: Optional[SampleLibrary] = None


def get_library(db_path: str = DEFAULT_DB_PATH) -> SampleLibrary:
    global _global_library
    if _global_library is None:
        _global_library = SampleLibrary(db_path=db_path)
    return _global_library
