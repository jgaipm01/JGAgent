"""config.yaml 과 .env 를 읽어 앱 전체에서 쓰는 설정을 제공한다."""
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SCREENSHOT_DIR = DATA_DIR / "screenshots"
KST = ZoneInfo("Asia/Seoul")

load_dotenv(ROOT / ".env")


def _load() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


CONFIG = _load()


def now_kst() -> datetime:
    return datetime.now(KST)


def anthropic_key_set() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def youtube_key() -> str | None:
    return os.getenv("YOUTUBE_API_KEY") or None


def test_video_url() -> str | None:
    """개발용 테스트 영상 링크 (.env TEST_VIDEO_URL). 비어 있으면 화면에 버튼이 안 보인다."""
    return (os.getenv("TEST_VIDEO_URL") or "").strip() or None


def profiles() -> list[dict]:
    """설정된 크롬 프로필 목록. 폴더가 있어야(=로그인 준비가 됐어야) 사용할 수 있다."""
    result = []
    for p in CONFIG.get("profiles", []):
        path = (ROOT / p["dir"]).resolve()
        result.append({"name": p["name"], "dir": path, "ready": path.is_dir()})
    return result


def profile_by_name(name: str) -> dict | None:
    return next((p for p in profiles() if p["name"] == name), None)
