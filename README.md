# 유튜브 댓글 에이전트 대시보드

(주)제이지그룹 AI PM 과제 · Track 2 마케팅 AI 에이전트

영상을 불러오고, 고르고, 버튼을 한 번 누르면 크롬 프로필이 열리면서 댓글이 한 글자씩 입력되고 게시됩니다.
AI는 영상 속 연애 고민을 먼저 정리하고, 그 영상을 본 시청자의 말투로 '운명원' 연애 사주가 궁금해지는 댓글을 씁니다.

| 칸 | 하는 일 |
|---|---|
| ① 영상 불러오기 | 최신 연애 영상 목록 (썸네일·제목·채널·올린 날짜). `뜨기 직전` 탭, 링크 직접 입력 |
| ② 영상 선택 | AI가 자막과 인기 댓글을 읽고 **영상 속 고민 한 줄**, 참고한 장면, **댓글 초안**을 보여줌. 초안은 직접 고칠 수 있고 규칙 검사가 실시간으로 표시됨 |
| ③ 댓글 달기 | 크롬 프로필이 열리고 댓글창 → 한 글자씩 타이핑 → 게시 → 내 댓글 확인. 진행 상태를 표시하고, 실패하면 이유와 화면 캡처를 남김 |

아래에는 게시 기록(어느 영상에 · 어느 계정으로 · 무슨 댓글을 · 성공/실패)이 표시됩니다.

왜 이렇게 설계했는지는 [docs/제작의도.md](docs/제작의도.md)에 정리했습니다.

---

## 1. 준비물

- Windows 또는 macOS, **Google Chrome**, **Python 3.11 이상**
- **Claude API 키**: https://console.anthropic.com
- **YouTube Data API v3 키**: Google Cloud Console → 프로젝트 만들기 → "YouTube Data API v3" 사용 설정 → 사용자 인증 정보 → API 키
- **게시용 구글 계정** 1개 (가점까지 하려면 3개). 아래 [3. 게시용 계정 준비](#3-게시용-계정-준비) 참고

## 2. 설치와 실행

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS: source .venv/bin/activate
pip install -r requirements.txt   # 브라우저는 설치된 Chrome 을 쓰므로 playwright install 은 필요 없음

copy .env.example .env            # macOS: cp .env.example .env
# .env 를 열어 ANTHROPIC_API_KEY, YOUTUBE_API_KEY 를 채운다

python run.py                     # 브라우저에서 http://127.0.0.1:8000 이 열림
```

## 3. 게시용 계정 준비

### 계정 만들기 — 주의점
- **평소 쓰는 개인 계정은 쓰지 않습니다.** 자동화된 댓글 때문에 계정이 제한되면 메일·드라이브까지 영향을 받을 수 있습니다.
- **Gmail ID는 관리하기 쉽게 정합니다** (예: `jg.aipm01`). 댓글에는 보이지 않습니다. Gmail은 마침표를 무시하므로 2·3번 계정은 숫자로 구분합니다 (`jg.aipm02`).
- **계정 이름(성·이름)은 아무거나 넣어도 됩니다.** 실존 인물이나 유명인 이름만 피합니다.
- **생년월일은 성인으로 넣습니다.** 미성년자 계정은 댓글이 제한됩니다.
- **전화번호 인증은 본인 번호를 써도 됩니다.** 공개되지 않습니다. 번호 하나로 인증할 수 있는 계정 수에는 제한이 있습니다. 임시 문자 인증 사이트는 쓰지 않습니다.
- **유튜브 채널을 꼭 만듭니다.** 채널이 없으면 댓글을 달 수 없습니다.
- **채널 이름은 평범한 시청자 이름으로 정합니다** (예: 새벽감성). 회사명이나 '운명원'을 넣으면 공식 계정처럼 보이거나 광고 계정으로 바로 드러납니다.
- **시연 며칠 전에 만들어 평범하게 써 둡니다** (영상 시청, 구독, 일반 댓글 한두 개). 막 만든 계정의 홍보성 댓글은 스팸 필터에 걸려 숨겨지기 쉽습니다.

### 크롬 프로필에 로그인하기
```bash
python scripts/open_profile.py 유튜브1
```
1. 에이전트 전용 프로필 폴더(`profiles/youtube1`)로 일반 크롬이 열립니다. 평소 쓰는 크롬과는 완전히 분리된 공간입니다.
2. 그 창에서 게시용 계정으로 로그인합니다. 계정을 아직 안 만들었다면 이 창에서 **[계정 만들기]**를 눌러 만들면 로그인까지 한 번에 끝납니다.
3. 유튜브 오른쪽 위에 프로필 사진이 보이면 완료입니다.
4. **그 크롬 창을 닫습니다.** 열려 있으면 에이전트가 같은 프로필을 열 수 없습니다.

> 로그인을 사람이 직접 하는 이유: 자동화된 크롬에서는 구글이 로그인을 막습니다. 한 번 로그인해 두면 에이전트는 그 로그인 상태를 그대로 씁니다.

가점용 유튜브2·3도 같은 방법으로 준비합니다. 폴더가 있는 프로필만 대시보드에서 선택할 수 있습니다.

## 4. 설정 (`config.yaml`)

```yaml
profiles:                     # 내 컴퓨터의 크롬 프로필 (유튜브2·3도 같은 형식)
  - { name: 유튜브1, dir: profiles/youtube1 }
comment: { min_chars: 40, max_chars: 120, brand: 운명원 }
limits:  { daily_max_comments: 10 }
search:  { query: "연애 고민|연애 상담|남자 심리|...", within_days: 30, max_results: 50, min_comments: 10 }
rising:  { min_views: 1000, max_views: 5000, min_views_per_hour: 150 }
typing:  { min_delay_ms: 60, max_delay_ms: 180 }
ai:      { model: claude-opus-5-5, effort: high }
```

## 5. 운영 규칙 — 코드에서 강제

| 규칙 | 어떻게 지키나 |
|---|---|
| 영상당 댓글 1개 | 게시 전에 서버가 기록을 확인하고, DB 고유 인덱스로 한 번 더 막음. 계정이 달라도 같은 영상에는 달 수 없음 |
| 하루 게시 상한 (기본 10개) | 한국 시간 기준 오늘 게시 수를 세서 상한이면 거부 |
| 동시에 한 건만 | 게시 중에는 다른 게시 요청을 거부 |
| 중복 게시 방지 | 게시 버튼을 누른 뒤 확인만 실패한 경우도 '확인 안 됨'으로 기록하고 게시한 것으로 침 |
| 댓글 내용 | 40~120자, 운명원 언급, 링크·해시태그 금지, 지어낸 이용 후기 금지, 이전 댓글과 너무 비슷하면 거부. AI가 쓴 직후와 게시 직전에 두 번 검사 |
| 기록 | 어느 영상에 · 어느 계정으로 · 무슨 댓글을 · 성공/실패 · 캡처를 시간순으로 저장하고 표시 |

화면의 버튼 비활성화는 안내용일 뿐이고, 모든 규칙은 서버(`app/rules.py`, `app/main.py`)에서 검사합니다.

## 6. 폴더 구조

```
app/
  main.py         대시보드 서버와 API
  rules.py        운영 규칙 (영상당 1개, 하루 상한, 동시 실행, 계정 배정)
  db.py           게시 기록 (SQLite)
  youtube_api.py  영상 검색·상세·인기 댓글·뜨기 직전 영상
  transcript.py   한국어 자막 (없으면 제목·설명 사용)
  writer.py       Claude 댓글 초안 + 규칙 검사기
  poster.py       크롬 자동화 (프로필 열기 → 타이핑 → 게시 → 확인)
  static/         대시보드 화면
scripts/open_profile.py   게시용 프로필 로그인용
tests/                    운영 규칙·검사기 테스트
```

## 7. 테스트

```bash
python -m pytest -q
```

**실제 게시 연습은 내 채널의 테스트 영상에서 합니다.** 남의 영상에서 시행착오를 하지 않기 위해서입니다.
1. 직접 찍은 짧은 영상을 개인 계정 채널에 **일부 공개**로 올립니다. 시청자층은 "아동용 아님"으로, 댓글은 "모든 댓글 허용"으로 설정합니다.
2. 그 링크를 ①칸 링크 입력창에 붙여넣어 불러옵니다. `.env` 의 `TEST_VIDEO_URL` 에도 넣어 둡니다 (3번 정리 스크립트가 씀).
3. 같은 테스트 영상으로 다시 연습하려면, 유튜브에서 테스트 댓글을 지운 뒤 `python scripts/reset_test_video.py` 를 실행합니다. 이 스크립트는 그 영상의 기록만 지우고, 다른 영상의 규칙은 그대로 둡니다.

**에이전트가 단 댓글 지우기** (예: 시연이 끝난 뒤): `python scripts/delete_comments.py --all` 또는 `python scripts/delete_comments.py <영상ID>`. 게시용 계정으로 크롬을 열어 유튜브에서 댓글을 삭제하고, 기록도 지웁니다.

## 8. 문제 해결

| 화면에 나오는 메시지 | 해결 |
|---|---|
| 크롬 창이 이미 열려 있어요 | 해당 프로필로 열어 둔 크롬 창을 닫고 다시 누름 |
| 로그인되어 있지 않아요 | `python scripts/open_profile.py 유튜브1` 로 다시 로그인 |
| 게시용 계정에 유튜브 채널이 없어요 | 그 프로필 창에서 유튜브 채널 만들기 |
| 댓글이 사용 중지된 영상이에요 | 다른 영상 선택 |
| 자막 없음 · 제목·설명 기반 | 자막이 없는 영상이라 제목·설명으로 초안을 만듦. 장면 언급이 약할 수 있음 |
| YouTube API 하루 사용량을 다 썼어요 | 다음 날 다시 시도 ([영상 불러오기] 1번에 할당량 약 400, 하루 기본 10,000. 5분 안에 다시 누르면 저장된 목록을 씀) |

## 9. Git 에 올리지 않는 것

`.gitignore` 에 들어 있습니다. 커밋 전에 `git status` 로 한 번 더 확인합니다.

- `.env`: API 키
- `profiles/`: 크롬 프로필 (구글 로그인 쿠키가 들어 있어 유출되면 계정이 넘어감)
- `data/`: 게시 기록 DB, 화면 캡처

## 10. 사용한 오픈소스

| 라이브러리 | 용도 | 라이선스 |
|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | 대시보드 서버 | MIT |
| [Uvicorn](https://github.com/encode/uvicorn) | 서버 실행 | BSD-3-Clause |
| [Playwright for Python](https://github.com/microsoft/playwright-python) | 크롬 자동화 | Apache-2.0 |
| [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) | Claude 호출 | MIT |
| [Pydantic](https://github.com/pydantic/pydantic) | AI 응답 형식 검증 | MIT |
| [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) | 자막 가져오기 | MIT |
| [google-api-python-client](https://github.com/googleapis/google-api-python-client) | YouTube Data API | Apache-2.0 |
| [PyYAML](https://github.com/yaml/pyyaml) | 설정 파일 | MIT |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | .env 읽기 | BSD-3-Clause |
| [tzdata](https://github.com/python/tzdata) | 한국 시간대 | Apache-2.0 |
| [pytest](https://github.com/pytest-dev/pytest) | 테스트 | MIT |
