import pytest

from app import youtube_api
from app.writer import check_comment

GOOD = ("영상에서 '답장 속도가 마음의 크기는 아니다'라는 말 듣고 좀 위로됐어요ㅠ 요즘 남친 답장이 느려서 불안했거든요. "
        "운명원 연애사주가 잘 본다던데 우리 인연인지 한번 보고 싶다")


def test_good_comment_passes():
    assert 40 <= len(GOOD) <= 120
    assert check_comment(GOOD) == []


def test_too_short():
    assert any("글자 수" in p for p in check_comment("운명원 궁금하다"))


def test_too_long():
    assert any("글자 수" in p for p in check_comment(GOOD + " 진짜로" * 20))


def test_brand_required():
    text = GOOD.replace("운명원", "그 사주집")
    assert any("언급" in p for p in check_comment(text))


@pytest.mark.parametrize("link", ["https://unmyung.com", "www.unmyung.kr", "unmyung.com"])
def test_links_blocked(link):
    assert any("링크" in p for p in check_comment(GOOD[:80] + " " + link))


def test_hashtag_blocked():
    assert any("해시태그" in p for p in check_comment(GOOD[:90] + " #연애사주"))


@pytest.mark.parametrize("fake", [
    "운명원에서 봤는데 진짜 소름 돋게 맞더라고요",
    "운명원 연애사주 받아봤는데 대박",
    "저번 달에 운명원 다녀왔는데 좋았어요",
    "운명원 후기 보고 왔는데 궁금하네",
])
def test_fake_review_blocked(fake):
    text = "영상에서 '먼저 연락하지 마라'는 말 공감돼요. " + fake
    assert any("후기" in p for p in check_comment(text))


def test_everyday_words_not_flagged():
    text = ("영상 속 '카톡 답장 받았는데 단답이면 끝'이라는 말에 뜨끔했어요ㅋㅋ 저도 요즘 그래서요. "
            "운명원 연애사주 잘 본다던데 한번 보고 싶다")
    assert check_comment(text) == []


def test_similar_to_previous_blocked():
    prev = [GOOD]
    near_copy = GOOD.replace("위로됐어요ㅠ", "위로됐어요ㅠㅠ")
    assert any("비슷" in p for p in check_comment(near_copy, prev))


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?si=abc", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://m.youtube.com/watch?app=desktop&v=dQw4w9WgXcQ&t=10", "dQw4w9WgXcQ"),
    ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://example.com", None),
])
def test_parse_video_id(url, expected):
    assert youtube_api.parse_video_id(url) == expected
