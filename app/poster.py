"""크롬 프로필을 열어 유튜브 댓글을 한 글자씩 입력하고, 게시한 뒤 내 댓글이 보이는지 확인한다.

- 평소 쓰는 기본 프로필은 크롬이 자동 제어를 막으므로, 프로필 폴더를 지정해 연다.
- 유튜브 화면 구조가 바뀌면 SELECTORS 만 고치면 된다.
"""
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from playwright.sync_api import Error as PWError
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from .config import CONFIG, SCREENSHOT_DIR, now_kst
from .writer import normalize

SELECTORS = {
    "masthead": "ytd-masthead",
    "avatar": "ytd-masthead #avatar-btn",
    "sign_in": "ytd-masthead a[href*='ServiceLogin']",
    "comments": "ytd-comments#comments",
    "comments_message": "ytd-comments ytd-message-renderer",
    "placeholder": "ytd-comments #simplebox-placeholder",
    "editor": "ytd-comments #contenteditable-root",
    "submit": "ytd-comments #submit-button button",
    "thread": "ytd-comments ytd-comment-thread-renderer",
    "thread_text": "#content-text",
    "thread_link": "#published-time-text a",
    "channel_dialog": "ytd-channel-creation-dialog-renderer",
    # 내 댓글 삭제용 (scripts/delete_comments.py)
    "thread_menu": "#action-menu-button button, #action-menu button",
    "menu_item": "tp-yt-iron-dropdown ytd-menu-navigation-item-renderer, tp-yt-iron-dropdown ytd-menu-service-item-renderer",
    "dialog": "tp-yt-paper-dialog:visible, yt-confirm-dialog-renderer:visible",
}

# (단계 코드, 화면 표시 이름)
STEPS = [
    ("opening_profile", "프로필 여는 중"),
    ("opening_video", "영상 여는 중"),
    ("finding_box", "댓글창 찾는 중"),
    ("typing", "입력 중"),
    ("submitting", "게시 중"),
    ("verifying", "내 댓글 확인 중"),
    ("done", "게시 완료"),
]


class PostError(Exception):
    def __init__(self, code: str, message: str, submitted: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.submitted = submitted  # 게시 버튼을 이미 눌렀는지 (눌렀다면 실제로 올라갔을 수 있음)
        self.screenshot: str | None = None


@dataclass
class PostResult:
    comment_url: str | None
    screenshot: str | None


def profile_in_use(profile_dir: Path) -> bool:
    """크롬이 이 프로필 폴더를 쓰는 중이면 lockfile 이 잠겨 있다."""
    lock = profile_dir / "lockfile"
    if not lock.exists():
        return False
    try:
        with open(lock, "a"):
            return False
    except PermissionError:
        return True


def _screenshot(page, video_id: str, tag: str) -> str | None:
    try:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{now_kst():%Y%m%d-%H%M%S}_{video_id}_{tag}.png"
        page.screenshot(path=str(SCREENSHOT_DIR / name))
        return f"/screenshots/{name}"
    except Exception:
        return None


def _quiet_video(page) -> None:
    # 시연 중 영상 소리가 나지 않게 멈춘다.
    page.evaluate("() => { const v = document.querySelector('video'); if (v) { v.muted = true; v.pause(); } }")


def _ensure_logged_in(page) -> None:
    page.wait_for_selector(f"{SELECTORS['avatar']}, {SELECTORS['sign_in']}", timeout=20000)
    if page.locator(SELECTORS["avatar"]).count() == 0:
        raise PostError("not_logged_in", "이 프로필은 유튜브에 로그인되어 있지 않아요. scripts/open_profile.py 로 로그인해 주세요.")


def _find_comment_box(page):
    for _ in range(25):
        box = page.locator(SELECTORS["placeholder"])
        if box.count() and box.first.is_visible():
            return box.first
        msg = page.locator(SELECTORS["comments_message"])
        if msg.count() and msg.first.is_visible():
            text = msg.first.inner_text()
            if "사용 중지" in text or "turned off" in text:
                raise PostError("comments_disabled", "댓글이 사용 중지된 영상이에요.")
        page.evaluate("() => window.scrollBy({ top: 500, behavior: 'smooth' })")
        page.wait_for_timeout(700)
        _quiet_video(page)
    raise PostError("no_comment_box", "댓글 입력창을 찾지 못했어요.")


def _open_editor(page):
    try:
        page.wait_for_selector(SELECTORS["editor"], state="visible", timeout=8000)
    except PWTimeout:
        if page.locator(SELECTORS["channel_dialog"]).count():
            raise PostError("no_channel", "게시용 계정에 유튜브 채널이 없어요. 유튜브에서 채널을 먼저 만들어 주세요.")
        raise PostError("no_editor", "댓글 입력칸이 열리지 않았어요.")
    return page.locator(SELECTORS["editor"]).first


def _wait_enabled(locator, seconds: float = 5) -> None:
    end = time.time() + seconds
    while time.time() < end:
        if locator.is_visible() and locator.is_enabled():
            return
        time.sleep(0.2)
    raise PostError("submit_disabled", "게시 버튼이 활성화되지 않았어요.")


def _find_my_comment(page, text: str, seconds: float = 20):
    end = time.time() + seconds
    while time.time() < end:
        threads = page.locator(SELECTORS["thread"])
        for i in range(min(threads.count(), 10)):
            th = threads.nth(i)
            try:
                body = normalize(th.locator(SELECTORS["thread_text"]).first.inner_text(timeout=1000))
            except PWError:
                continue
            if body == text or (len(text) > 20 and text[:20] in body):
                return th
        page.wait_for_timeout(500)
    raise PostError("not_verified", "게시 버튼은 눌렀지만 목록에서 내 댓글을 찾지 못했어요.", submitted=True)


def open_profile(p, profile: dict):
    """게시용 프로필로 크롬을 연다 (게시·삭제 공용)."""
    return p.chromium.launch_persistent_context(
        user_data_dir=str(profile["dir"]), channel="chrome", headless=False,
        locale="ko-KR", no_viewport=True, args=["--start-maximized"],
        chromium_sandbox=True,  # 크롬 보안 샌드박스 유지 (끄면 "--no-sandbox" 경고 줄이 뜸)
    )


def delete_my_comment(page, video_id: str, text: str, comment_url: str | None = None) -> bool:
    """이미 열린 페이지에서 내 댓글을 찾아 삭제한다. 찾지 못하면 False (이미 지워졌을 수 있음)."""
    page.goto(comment_url or f"https://www.youtube.com/watch?v={video_id}&hl=ko", wait_until="domcontentloaded")
    page.wait_for_selector(SELECTORS["masthead"], timeout=30000)
    _ensure_logged_in(page)
    _quiet_video(page)
    _find_comment_box(page)
    try:
        thread = _find_my_comment(page, normalize(text), seconds=15)
    except PostError:
        return False
    thread.scroll_into_view_if_needed()
    thread.hover()
    thread.locator(SELECTORS["thread_menu"]).first.click()
    page.locator(SELECTORS["menu_item"]).filter(has_text="삭제").first.click()
    dialog = page.locator(SELECTORS["dialog"]).first
    dialog.wait_for(timeout=10000)
    dialog.get_by_role("button", name="삭제").first.click()
    page.wait_for_timeout(2500)
    return True


def post_comment(video_id: str, text: str, profile: dict,
                 on_step: Callable[[str, int | None], None]) -> PostResult:
    text = normalize(text)
    pdir: Path = profile["dir"]
    if profile_in_use(pdir):
        raise PostError("profile_in_use", f"'{profile['name']}' 크롬 창이 이미 열려 있어요. 그 창을 닫고 다시 눌러 주세요.")

    typing = CONFIG.get("typing", {})
    lo, hi = int(typing.get("min_delay_ms", 60)), int(typing.get("max_delay_ms", 180))

    on_step("opening_profile", None)
    with sync_playwright() as p:
        try:
            ctx = open_profile(p, profile)
        except PWError as e:
            msg = str(e)
            if any(k in msg for k in ("in use", "ProcessSingleton", "existing browser session")):
                raise PostError("profile_in_use", f"'{profile['name']}' 크롬 창이 이미 열려 있어요. 그 창을 닫고 다시 눌러 주세요.") from e
            raise PostError("launch_failed", f"크롬을 열지 못했어요: {msg.splitlines()[0][:200]}") from e

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        submitted = False
        try:
            on_step("opening_video", None)
            page.goto(f"https://www.youtube.com/watch?v={video_id}&hl=ko", wait_until="domcontentloaded", timeout=45000)
            page.wait_for_selector(SELECTORS["masthead"], timeout=30000)
            _ensure_logged_in(page)
            _quiet_video(page)

            on_step("finding_box", None)
            box = _find_comment_box(page)
            box.scroll_into_view_if_needed()
            box.click()
            editor = _open_editor(page)
            editor.click()

            on_step("typing", 0)
            for i, ch in enumerate(text, 1):
                page.keyboard.type(ch)
                page.wait_for_timeout(random.randint(lo, hi))
                if i % 3 == 0 or i == len(text):
                    on_step("typing", round(i / len(text) * 100))
            if normalize(editor.inner_text()) != text:
                raise PostError("typing_mismatch", "입력된 글자가 댓글 초안과 달라요. 다시 시도해 주세요.")

            on_step("submitting", None)
            submit = page.locator(SELECTORS["submit"]).first
            _wait_enabled(submit)
            submit.click()
            submitted = True

            on_step("verifying", None)
            thread = _find_my_comment(page, text)
            href = thread.locator(SELECTORS["thread_link"]).first.get_attribute("href") or ""
            url = ("https://www.youtube.com" + href) if href.startswith("/") else (href or f"https://www.youtube.com/watch?v={video_id}")
            thread.scroll_into_view_if_needed()
            thread.evaluate("el => { el.style.outline = '3px solid #e2a400'; el.style.outlineOffset = '6px'; el.style.borderRadius = '8px'; }")
            shot = _screenshot(page, video_id, "ok")

            on_step("done", None)
            page.wait_for_timeout(3000)
            return PostResult(comment_url=url, screenshot=shot)

        except PostError as e:
            e.submitted = e.submitted or submitted
            e.screenshot = _screenshot(page, video_id, "fail")
            raise
        except PWTimeout as e:
            err = PostError(
                "timeout",
                "게시 버튼은 눌렀지만 확인 중에 시간이 초과됐어요." if submitted else "화면 요소를 기다리다 시간이 초과됐어요.",
                submitted,
            )
            err.screenshot = _screenshot(page, video_id, "fail")
            raise err from e
        except Exception as e:
            if "has been closed" in str(e):
                raise PostError(
                    "window_closed",
                    "게시 중에 크롬 창이 닫혔어요. 게시가 끝날 때까지 창을 닫거나 건드리지 말아 주세요.",
                    submitted,
                ) from e
            err = PostError("unexpected", f"예상치 못한 오류: {str(e).splitlines()[0][:200]}", submitted)
            err.screenshot = _screenshot(page, video_id, "fail")
            raise err from e
        finally:
            try:
                ctx.close()
            except Exception:
                pass
