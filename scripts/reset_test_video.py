"""개발용: .env 의 TEST_VIDEO_URL 영상에 대한 게시 기록만 지워서 다시 테스트할 수 있게 한다.

사용법:  python scripts/reset_test_video.py

- 다른 영상의 기록과 '영상당 1개' 규칙은 그대로다.
- 유튜브에 실제로 달린 댓글은 지워지지 않으니, 유튜브에서 직접 삭제해 주세요.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.config import test_video_url  # noqa: E402
from app.youtube_api import parse_video_id  # noqa: E402


def main() -> None:
    url = test_video_url()
    video_id = parse_video_id(url or "")
    if not video_id:
        print(".env 에 TEST_VIDEO_URL 이 없거나 올바른 유튜브 링크가 아니에요.")
        sys.exit(1)
    removed = db.delete_for_video(video_id)
    print(f"테스트 영상({video_id}) 기록 {removed}건을 지웠어요. 대시보드를 새로고침하세요.")
    print("유튜브에 달린 테스트 댓글은 유튜브에서 직접 삭제해 주세요.")


if __name__ == "__main__":
    main()
