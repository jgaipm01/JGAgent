"""운영 규칙 — 화면이 아니라 서버 코드에서 강제한다.

1. 영상당 댓글 1개 (계정이 달라도 한 영상에는 한 번만)
2. 하루 게시 상한 (config.yaml limits.daily_max_comments, KST 기준)
3. 동시에 한 건만 게시
"""
import threading
from datetime import datetime

from . import db
from .config import CONFIG, now_kst, profiles

post_lock = threading.Lock()


class RuleError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def daily_max() -> int:
    return int(CONFIG.get("limits", {}).get("daily_max_comments", 10))


def today_count(now: datetime | None = None) -> int:
    now = now or now_kst()
    return db.count_active_on(now.date().isoformat())


def check_can_post(video_id: str, now: datetime | None = None) -> None:
    existing = db.active_for_video(video_id)
    if existing:
        raise RuleError(
            "already_commented",
            f"이미 댓글을 단 영상이에요 ({existing['profile']}). 한 영상에는 댓글 1개만 달 수 있어요.",
        )
    limit = daily_max()
    if today_count(now) >= limit:
        raise RuleError("daily_limit", f"오늘 게시 상한({limit}개)에 도달했어요. 내일 다시 시도해 주세요.")


def pick_profile(requested: str | None) -> dict:
    """요청한 프로필을 쓰거나, '자동'이면 준비된 프로필 중 가장 오래전에 쓴 것을 고른다."""
    ready = [p for p in profiles() if p["ready"]]
    if not ready:
        raise RuleError(
            "no_profile",
            "로그인된 크롬 프로필이 없어요. scripts/open_profile.py 로 먼저 로그인해 주세요.",
        )
    if requested and requested != "auto":
        match = next((p for p in profiles() if p["name"] == requested), None)
        if not match:
            raise RuleError("unknown_profile", f"'{requested}' 프로필이 설정에 없어요.")
        if not match["ready"]:
            raise RuleError("profile_not_ready", f"'{requested}' 프로필은 아직 로그인 전이에요.")
        return match
    last_used = db.last_used_by_profile()
    # 한 번도 안 쓴 프로필("")이 먼저, 그다음 오래전에 쓴 순서. 같으면 설정 순서.
    return min(ready, key=lambda p: last_used.get(p["name"], ""))
