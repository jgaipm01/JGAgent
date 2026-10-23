"""YouTube Data API v3 — 영상 검색, 상세 정보, 인기 댓글, 뜨기 직전 영상."""
import re
import time
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .config import CONFIG, youtube_key


class YouTubeError(Exception):
    pass


_cache: dict[str, tuple[float, object]] = {}
CACHE_SECONDS = 300

# 영상 상세는 초안 생성 때 다시 쓰므로 기억해 둔다.
VIDEO_INFO: dict[str, dict] = {}


def _yt():
    # googleapiclient 클라이언트는 스레드 간에 공유하면 안전하지 않아서 호출마다 만든다.
    key = youtube_key()
    if not key:
        raise YouTubeError("YouTube API 키가 없어요. .env 파일에 YOUTUBE_API_KEY 를 넣어 주세요.")
    return build("youtube", "v3", developerKey=key, cache_discovery=False)


def _cached(key: str, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = fn()
    _cache[key] = (time.time(), value)
    return value


def _http_message(e: HttpError) -> str:
    if e.resp.status == 403 and b"quota" in (e.content or b""):
        return "YouTube API 하루 사용량을 다 썼어요. 내일 다시 시도하거나 다른 키를 써 주세요."
    if e.resp.status in (400, 403):
        return "YouTube API 키가 올바르지 않거나 YouTube Data API v3 가 꺼져 있어요."
    return f"YouTube API 오류 ({e.resp.status})"


def _duration_seconds(iso: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def _to_video(item: dict) -> dict:
    sn = item["snippet"]
    st = item.get("statistics", {})
    thumbs = sn.get("thumbnails", {})
    thumb = (thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}).get("url", "")
    return {
        "id": item["id"],
        "title": sn.get("title", ""),
        "channel": sn.get("channelTitle", ""),
        "published_at": sn.get("publishedAt", ""),
        "thumbnail": thumb,
        "description": sn.get("description", ""),
        "duration_sec": _duration_seconds(item.get("contentDetails", {}).get("duration", "")),
        "view_count": int(st.get("viewCount", 0)),
        "comment_count": int(st["commentCount"]) if "commentCount" in st else None,
        "live": sn.get("liveBroadcastContent", "none") != "none",
        "category_id": int(sn.get("categoryId", 0) or 0),
        "url": f"https://www.youtube.com/watch?v={item['id']}",
    }


def _details(ids: list[str]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for i in range(0, len(ids), 50):  # videos.list 는 한 번에 50개까지
        try:
            res = _yt().videos().list(
                part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50]), maxResults=50
            ).execute()
        except HttpError as e:
            raise YouTubeError(_http_message(e)) from e
        by_id.update({it["id"]: _to_video(it) for it in res.get("items", [])})
    videos = [by_id[i] for i in ids if i in by_id]
    for v in videos:
        VIDEO_INFO[v["id"]] = v
    return videos


def _search_ids(query: str, max_results: int, published_after: datetime | None = None,
                order: str = "date") -> list[str]:
    """쇼츠가 검색 결과를 채우지 않도록 4~20분(medium), 20분 이상(long)을 따로 검색해 합친다.
    할당량: 검색 1번에 100, 그래서 호출 1번에 200."""
    ids: list[str] = []
    for duration in ("medium", "long"):
        params = dict(
            part="id", q=query, type="video", order=order, videoDuration=duration,
            regionCode="KR", relevanceLanguage="ko", maxResults=max_results,
        )
        if published_after:
            params["publishedAfter"] = published_after.strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            res = _yt().search().list(**params).execute()
        except HttpError as e:
            raise YouTubeError(_http_message(e)) from e
        for it in res.get("items", []):
            vid = it.get("id", {}).get("videoId")
            if vid and vid not in ids:
                ids.append(vid)
    return ids


def _usable(v: dict) -> bool:
    """댓글이 막힌 영상(commentCount 없음), 라이브, 쇼츠, 제외 카테고리·키워드 영상은 뺀다."""
    cfg = CONFIG.get("search", {})
    if v["comment_count"] is None or v["live"]:
        return False
    if not int(cfg.get("min_duration_sec", 181)) <= v["duration_sec"] <= int(cfg.get("max_duration_sec", 3600)):
        return False
    if v.get("category_id") in set(cfg.get("exclude_categories", [])):
        return False
    if not re.search(r"[가-힣]", v["title"]):  # 한국어 영상만
        return False
    text = f"{v['title']} {v['channel']}"
    return not any(k in text for k in cfg.get("exclude_keywords", []))


def search_latest(force: bool = False) -> list[dict]:
    cfg = CONFIG.get("search", {})
    query = cfg.get("query", "연애")
    limit = int(cfg.get("max_results", 20))
    after = datetime.now(timezone.utc) - timedelta(days=int(cfg.get("within_days", 7)))
    min_comments = int(cfg.get("min_comments", 0))

    def run():
        # 최근 기간 안에서 조회수 순·관련도 순으로 각각 찾아 합치고, 댓글 많은 영상부터 limit 개를 고른다.
        # (조회수 순이 반응 많은 영상을 훨씬 많이 찾는다. 화면에서 최신순으로 다시 정렬할 수 있다)
        ids: list[str] = []
        for order in cfg.get("orders", ["viewCount", "relevance"]):
            ids += [i for i in _search_ids(query, 50, published_after=after, order=order) if i not in ids]
        videos = [v for v in _details(ids) if _usable(v) and v["comment_count"] >= min_comments]
        videos.sort(key=lambda v: v["comment_count"], reverse=True)
        return videos[:limit]

    if force:
        _cache.pop("latest", None)
    return _cached("latest", run)


def find_rising(force: bool = False) -> list[dict]:
    """조회수 min~max 사이이면서 시간당 조회수가 기준 이상인 최근 영상."""
    cfg = CONFIG.get("rising", {})
    now = datetime.now(timezone.utc)
    after = now - timedelta(hours=int(cfg.get("within_hours", 48)))

    def run():
        ids = _search_ids(cfg.get("query", "연애"), 50, published_after=after)
        result = []
        for v in _details(ids):
            if not _usable(v):
                continue
            published = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
            hours = max((now - published).total_seconds() / 3600, 0.25)
            v["hours_since"] = round(hours, 1)
            v["views_per_hour"] = round(v["view_count"] / hours)
            if (int(cfg.get("min_views", 1000)) <= v["view_count"] <= int(cfg.get("max_views", 5000))
                    and v["views_per_hour"] >= int(cfg.get("min_views_per_hour", 150))):
                result.append(v)
        return sorted(result, key=lambda v: v["views_per_hour"], reverse=True)

    if force:
        _cache.pop("rising", None)
    return _cached("rising", run)


_ID_PATTERNS = [
    r"(?:v=|/shorts/|/live/|/embed/|youtu\.be/)([A-Za-z0-9_-]{11})",
    r"^([A-Za-z0-9_-]{11})$",
]


def parse_video_id(url_or_id: str) -> str | None:
    s = (url_or_id or "").strip()
    for pat in _ID_PATTERNS:
        m = re.search(pat, s)
        if m:
            return m.group(1)
    return None


def get_video(video_id: str) -> dict:
    if video_id in VIDEO_INFO:
        return VIDEO_INFO[video_id]
    videos = _details([video_id])
    if not videos:
        raise YouTubeError("영상을 찾을 수 없어요. 링크를 다시 확인해 주세요.")
    return videos[0]


def top_comments(video_id: str, limit: int = 20) -> list[str]:
    try:
        res = _yt().commentThreads().list(
            part="snippet", videoId=video_id, order="relevance",
            maxResults=limit, textFormat="plainText",
        ).execute()
    except HttpError:
        return []  # 댓글을 못 읽어도 초안은 만들 수 있다.
    out = []
    for it in res.get("items", []):
        top = it["snippet"]["topLevelComment"]["snippet"]
        out.append(f"(좋아요 {top.get('likeCount', 0)}) {top.get('textDisplay', '').strip()}")
    return out
