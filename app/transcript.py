"""영상 자막 가져오기. 자막이 없으면 None 을 돌려주고, 호출한 쪽에서 제목·설명을 쓴다."""
from youtube_transcript_api import YouTubeTranscriptApi

_api = YouTubeTranscriptApi()
_cache: dict[str, str | None] = {}


def fetch_korean(video_id: str) -> str | None:
    if video_id in _cache:
        return _cache[video_id]
    text = None
    try:
        fetched = _api.fetch(video_id, languages=["ko"])
        text = " ".join(s.text.replace("\n", " ") for s in fetched).strip() or None
    except Exception:
        # 자막 꺼짐, 한국어 자막 없음, 요청 차단 등 — 모두 "자막 없음"으로 처리한다.
        text = None
    _cache[video_id] = text
    return text
