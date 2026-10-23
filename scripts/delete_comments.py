"""에이전트가 단 댓글을 유튜브에서 지우고, 게시 기록에서도 지운다.

사용법:
  python scripts/delete_comments.py --all            기록에 있는 댓글 전부
  python scripts/delete_comments.py <영상ID> ...     특정 영상만

- 실패(failed) 기록은 유튜브에 올라간 게 없으므로 기록만 지운다.
- 유튜브에서 지우지 못한 댓글은 기록을 남겨 둔다 (다시 실행하면 재시도).
- 해당 프로필의 크롬 창이 열려 있으면 먼저 닫아야 한다.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from app import db, poster  # noqa: E402
from app.config import SCREENSHOT_DIR, profile_by_name  # noqa: E402


def _forget(row: dict) -> None:
    db.delete_row(row["id"])
    if row.get("screenshot"):
        (SCREENSHOT_DIR / Path(row["screenshot"]).name).unlink(missing_ok=True)


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    rows = db.log(100000)
    if args != ["--all"]:
        rows = [r for r in rows if r["video_id"] in set(args)]
    if not rows:
        print("지울 기록이 없어요.")
        return

    by_profile: dict[str, list[dict]] = {}
    for r in rows:
        if r["status"] == "failed":
            _forget(r)
            print(f"[기록만 삭제] {r['video_title']} (게시되지 않은 시도)")
        else:
            by_profile.setdefault(r["profile"], []).append(r)

    with sync_playwright() as p:
        for name, items in by_profile.items():
            prof = profile_by_name(name)
            if not prof or not prof["ready"]:
                print(f"[건너뜀] '{name}' 프로필이 없어요.")
                continue
            if poster.profile_in_use(prof["dir"]):
                print(f"[건너뜀] '{name}' 크롬 창이 열려 있어요. 닫고 다시 실행해 주세요.")
                continue
            ctx = poster.open_profile(p, prof)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                for r in items:
                    try:
                        found = poster.delete_my_comment(page, r["video_id"], r["text"], r["comment_url"])
                    except Exception as e:
                        print(f"[실패] {r['video_title']}: {str(e).splitlines()[0][:150]}")
                        continue
                    _forget(r)
                    print(f"[삭제] {r['video_title']}" if found
                          else f"[기록만 삭제] {r['video_title']} (유튜브에서 댓글을 찾지 못함 — 이미 지워졌을 수 있음)")
            finally:
                ctx.close()


if __name__ == "__main__":
    main()
