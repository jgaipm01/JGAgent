"""대시보드 서버. 화면(static/)과 API 를 제공한다."""
import sqlite3
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, poster, rules, writer, youtube_api
from .config import SCREENSHOT_DIR, anthropic_key_set, profiles, youtube_key
from .transcript import fetch_korean
from .youtube_api import YouTubeError

STATIC = Path(__file__).parent / "static"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

JOBS: dict[str, dict] = {}
DRAFTS: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(_app):
    db.close_stale_posting()
    yield


app = FastAPI(title="유튜브 댓글 에이전트", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.mount("/screenshots", StaticFiles(directory=SCREENSHOT_DIR), name="screenshots")


def _fail(status: int, message: str, **extra):
    raise HTTPException(status, {"message": message, **extra})


def _yt(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except YouTubeError as e:
        _fail(400, str(e))


def _public(videos: list[dict]) -> list[dict]:
    """목록용: 설명은 빼고, 이미 댓글 단 영상을 표시한다."""
    done = db.commented_video_ids()
    return [{k: v for k, v in vid.items() if k != "description"} | {"commented": vid["id"] in done}
            for vid in videos]


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def status():
    return {
        "today": rules.today_count(),
        "limit": rules.daily_max(),
        "profiles": [{"name": p["name"], "ready": p["ready"]} for p in profiles()],
        "keys": {"anthropic": anthropic_key_set(), "youtube": bool(youtube_key())},
        "comment_rules": writer.comment_rules(),
        "busy": rules.post_lock.locked(),
        "steps": [{"code": c, "label": label} for c, label in poster.STEPS],
    }


@app.get("/api/videos")
def videos(refresh: bool = False):
    return {"videos": _public(_yt(youtube_api.search_latest, force=refresh))}


@app.get("/api/videos/rising")
def rising(refresh: bool = False):
    return {"videos": _public(_yt(youtube_api.find_rising, force=refresh))}


class UrlIn(BaseModel):
    url: str


@app.post("/api/videos/by-url")
def by_url(body: UrlIn):
    vid = youtube_api.parse_video_id(body.url)
    if not vid:
        _fail(400, "올바른 유튜브 영상 링크가 아니에요.")
    return {"video": _public([_yt(youtube_api.get_video, vid)])[0]}


class DraftIn(BaseModel):
    video_id: str
    regenerate: bool = False


@app.post("/api/drafts")
def make_draft(body: DraftIn):
    if not anthropic_key_set():
        _fail(400, "Claude API 키가 없어요. .env 파일에 ANTHROPIC_API_KEY 를 넣어 주세요.")
    if not body.regenerate and body.video_id in DRAFTS:
        return DRAFTS[body.video_id]
    video = _yt(youtube_api.get_video, body.video_id)
    transcript = fetch_korean(body.video_id)
    comments = _yt(youtube_api.top_comments, body.video_id)
    try:
        result = writer.generate(video, transcript, comments, db.recent_texts(10))
    except writer.WriterError as e:
        _fail(502, str(e))
    result["video_id"] = body.video_id
    DRAFTS[body.video_id] = result
    return result


class CheckIn(BaseModel):
    text: str


@app.post("/api/check")
def check(body: CheckIn):
    text = writer.normalize(body.text)
    return {"length": len(text), "problems": writer.check_comment(text, db.recent_texts(10))}


class PostIn(BaseModel):
    video_id: str
    text: str
    profile: str = "auto"


@app.post("/api/post")
def post(body: PostIn):
    # 동시에 한 건만. 잠금은 게시 스레드가 끝날 때 푼다.
    if not rules.post_lock.acquire(blocking=False):
        _fail(409, "다른 댓글을 게시하는 중이에요. 끝난 뒤 다시 눌러 주세요.")
    started = False
    try:
        text = writer.normalize(body.text)
        rules.check_can_post(body.video_id)
        problems = writer.check_comment(text, db.recent_texts(10))
        if problems:
            _fail(400, "댓글이 규칙에 맞지 않아요.", problems=problems)
        profile = rules.pick_profile(body.profile)
        title = youtube_api.VIDEO_INFO.get(body.video_id, {}).get("title") or body.video_id
        try:
            row_id = db.insert_attempt(body.video_id, title, profile["name"], text)
        except sqlite3.IntegrityError:
            raise rules.RuleError("already_commented", "이미 댓글을 단 영상이에요. 한 영상에는 댓글 1개만 달 수 있어요.")

        job_id = uuid.uuid4().hex[:12]
        JOBS[job_id] = {
            "id": job_id, "state": "running", "step": "opening_profile", "progress": 0,
            "video_id": body.video_id, "profile": profile["name"],
            "message": None, "comment_url": None, "screenshot": None,
        }
        threading.Thread(target=_run_post, args=(job_id, row_id, body.video_id, text, profile), daemon=True).start()
        started = True
        return {"job_id": job_id, "profile": profile["name"]}
    except rules.RuleError as e:
        _fail(400, e.message, code=e.code)
    finally:
        if not started:
            rules.post_lock.release()


def _run_post(job_id: str, row_id: int, video_id: str, text: str, profile: dict) -> None:
    job = JOBS[job_id]

    def on_step(step: str, progress: int | None) -> None:
        job["step"] = step
        if progress is not None:
            job["progress"] = progress

    try:
        result = poster.post_comment(video_id, text, profile, on_step)
        db.update_result(row_id, "success", screenshot=result.screenshot, comment_url=result.comment_url)
        job.update(state="success", comment_url=result.comment_url, screenshot=result.screenshot)
    except poster.PostError as e:
        state = "unverified" if e.submitted else "failed"
        db.update_result(row_id, state, error=e.message, screenshot=e.screenshot)
        job.update(state=state, message=e.message, screenshot=e.screenshot)
    except Exception as e:  # 마지막 안전망
        db.update_result(row_id, "failed", error=str(e)[:300])
        job.update(state="failed", message=f"예상치 못한 오류: {str(e)[:200]}")
    finally:
        rules.post_lock.release()


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    if job_id not in JOBS:
        _fail(404, "작업을 찾을 수 없어요.")
    return JOBS[job_id]


@app.get("/api/log")
def log():
    return {"rows": db.log()}
