"""게시 기록 저장소 (SQLite).

status 값
- posting    : 게시 진행 중
- success    : 게시 후 내 댓글까지 확인
- unverified : 게시 버튼은 눌렀지만 확인 실패 (실제로 올라갔을 수 있으므로 게시한 것으로 친다)
- failed     : 게시 버튼을 누르기 전에 실패 (올라가지 않음)
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import DATA_DIR, now_kst

ACTIVE_STATUSES = ("posting", "success", "unverified")

DB_PATH: Path = DATA_DIR / "app.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    TEXT NOT NULL,
    video_title TEXT,
    profile     TEXT NOT NULL,
    text        TEXT NOT NULL,
    status      TEXT NOT NULL,
    error       TEXT,
    screenshot  TEXT,
    comment_url TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
-- 영상당 댓글 1개를 DB 차원에서도 보장한다 (실패한 시도는 제외).
CREATE UNIQUE INDEX IF NOT EXISTS one_comment_per_video
    ON comments(video_id) WHERE status IN ('posting', 'success', 'unverified');
"""


def set_path(path: Path) -> None:
    """테스트에서 임시 DB를 쓰기 위해 경로를 바꾼다."""
    global DB_PATH
    DB_PATH = path


@contextmanager
def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def insert_attempt(video_id: str, video_title: str, profile: str, text: str) -> int:
    ts = now_kst().isoformat(timespec="seconds")
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO comments (video_id, video_title, profile, text, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'posting', ?, ?)",
            (video_id, video_title, profile, text, ts, ts),
        )
        return cur.lastrowid


def update_result(row_id: int, status: str, error: str | None = None,
                  screenshot: str | None = None, comment_url: str | None = None) -> None:
    ts = now_kst().isoformat(timespec="seconds")
    with _conn() as c:
        c.execute(
            "UPDATE comments SET status=?, error=?, screenshot=?, comment_url=?, updated_at=? WHERE id=?",
            (status, error, screenshot, comment_url, ts, row_id),
        )


def close_stale_posting() -> int:
    """서버가 게시 도중 꺼졌다면 결과를 모르므로 '확인 안 됨'으로 바꾼다 (재게시 방지)."""
    ts = now_kst().isoformat(timespec="seconds")
    with _conn() as c:
        cur = c.execute(
            "UPDATE comments SET status='unverified', error='게시 중에 서버가 종료되어 결과를 확인하지 못했어요.',"
            " updated_at=? WHERE status='posting'",
            (ts,),
        )
        return cur.rowcount


def delete_for_video(video_id: str) -> int:
    """정리용: 한 영상의 기록을 지운다 (scripts/ 의 정리 스크립트에서만 사용)."""
    with _conn() as c:
        return c.execute("DELETE FROM comments WHERE video_id=?", (video_id,)).rowcount


def delete_row(row_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM comments WHERE id=?", (row_id,))


def active_for_video(video_id: str) -> dict | None:
    marks = ",".join("?" * len(ACTIVE_STATUSES))
    with _conn() as c:
        row = c.execute(
            f"SELECT * FROM comments WHERE video_id=? AND status IN ({marks}) LIMIT 1",
            (video_id, *ACTIVE_STATUSES),
        ).fetchone()
        return dict(row) if row else None


def count_active_on(date_str: str) -> int:
    """해당 날짜(KST, YYYY-MM-DD)에 게시했거나 게시 중인 댓글 수."""
    marks = ",".join("?" * len(ACTIVE_STATUSES))
    with _conn() as c:
        return c.execute(
            f"SELECT COUNT(*) FROM comments WHERE substr(created_at, 1, 10)=? AND status IN ({marks})",
            (date_str, *ACTIVE_STATUSES),
        ).fetchone()[0]


def commented_video_ids() -> set[str]:
    marks = ",".join("?" * len(ACTIVE_STATUSES))
    with _conn() as c:
        rows = c.execute(
            f"SELECT DISTINCT video_id FROM comments WHERE status IN ({marks})", ACTIVE_STATUSES
        ).fetchall()
        return {r[0] for r in rows}


def recent_texts(limit: int = 10) -> list[str]:
    marks = ",".join("?" * len(ACTIVE_STATUSES))
    with _conn() as c:
        rows = c.execute(
            f"SELECT text FROM comments WHERE status IN ({marks}) ORDER BY id DESC LIMIT ?",
            (*ACTIVE_STATUSES, limit),
        ).fetchall()
        return [r[0] for r in rows]


def last_used_by_profile() -> dict[str, str]:
    with _conn() as c:
        rows = c.execute(
            "SELECT profile, MAX(created_at) FROM comments GROUP BY profile"
        ).fetchall()
        return {r[0]: r[1] for r in rows}


def log(limit: int = 200) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM comments ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
