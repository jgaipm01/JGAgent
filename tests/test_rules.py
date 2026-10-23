import sqlite3
from datetime import datetime

import pytest

from app import db, rules
from app.config import KST


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    db.set_path(tmp_path / "test.db")


@pytest.fixture
def limit(monkeypatch):
    def set_limit(n):
        monkeypatch.setitem(rules.CONFIG, "limits", {"daily_max_comments": n})
    return set_limit


def add(video_id, status="success", profile="유튜브1"):
    row = db.insert_attempt(video_id, f"제목 {video_id}", profile, f"댓글 {video_id}")
    if status != "posting":
        db.update_result(row, status)
    return row


# --- 영상당 댓글 1개 ---

def test_first_comment_allowed():
    rules.check_can_post("v1")


@pytest.mark.parametrize("status", ["posting", "success", "unverified"])
def test_second_comment_on_same_video_blocked(status):
    add("v1", status)
    with pytest.raises(rules.RuleError) as e:
        rules.check_can_post("v1")
    assert e.value.code == "already_commented"


def test_failed_attempt_can_retry():
    add("v1", "failed")
    rules.check_can_post("v1")


def test_db_index_blocks_duplicate_even_without_rule_check():
    add("v1", "success")
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_attempt("v1", "제목", "유튜브2", "다른 계정으로 또")


def test_stale_posting_becomes_unverified():
    add("v1", "posting")
    assert db.close_stale_posting() == 1
    assert db.active_for_video("v1")["status"] == "unverified"


# --- 하루 상한 ---

def test_daily_limit_blocks(limit):
    limit(2)
    add("v1")
    add("v2", "unverified")
    with pytest.raises(rules.RuleError) as e:
        rules.check_can_post("v3")
    assert e.value.code == "daily_limit"


def test_failed_attempts_do_not_count(limit):
    limit(1)
    add("v1", "failed")
    rules.check_can_post("v2")


def test_limit_resets_at_kst_midnight(limit, monkeypatch):
    limit(1)
    monkeypatch.setattr(db, "now_kst", lambda: datetime(2026, 10, 22, 23, 59, tzinfo=KST))
    add("v1")
    rules.check_can_post("v2", now=datetime(2026, 10, 23, 0, 1, tzinfo=KST))
    with pytest.raises(rules.RuleError):
        rules.check_can_post("v2", now=datetime(2026, 10, 22, 23, 59, 30, tzinfo=KST))


# --- 프로필 배정 ---

@pytest.fixture
def three_profiles(monkeypatch, tmp_path):
    def make(ready):
        items = [{"name": f"유튜브{i}", "dir": tmp_path / f"p{i}", "ready": r} for i, r in enumerate(ready, 1)]
        monkeypatch.setattr(rules, "profiles", lambda: items)
    return make


def test_auto_picks_unused_then_least_recent(three_profiles, monkeypatch):
    three_profiles([True, True, True])
    minutes = iter(range(60))  # 호출할 때마다 1분씩 흐르는 시계
    monkeypatch.setattr(db, "now_kst", lambda: datetime(2026, 10, 23, 10, next(minutes), tzinfo=KST))
    assert rules.pick_profile("auto")["name"] == "유튜브1"
    add("v1", profile="유튜브1")
    assert rules.pick_profile("auto")["name"] == "유튜브2"
    add("v2", profile="유튜브2")
    assert rules.pick_profile("auto")["name"] == "유튜브3"


def test_auto_skips_profiles_not_logged_in(three_profiles):
    three_profiles([False, True, False])
    assert rules.pick_profile("auto")["name"] == "유튜브2"


def test_requested_profile_must_be_ready(three_profiles):
    three_profiles([True, False, True])
    assert rules.pick_profile("유튜브3")["name"] == "유튜브3"
    with pytest.raises(rules.RuleError) as e:
        rules.pick_profile("유튜브2")
    assert e.value.code == "profile_not_ready"


def test_no_ready_profile(three_profiles):
    three_profiles([False, False, False])
    with pytest.raises(rules.RuleError) as e:
        rules.pick_profile("auto")
    assert e.value.code == "no_profile"
