"""게시용 크롬 프로필을 일반 크롬으로 열어 구글 로그인을 직접 하게 한다.

사용법:  python scripts/open_profile.py 유튜브1

자동화된 크롬에서는 구글이 로그인을 막기 때문에, 로그인만큼은 이렇게 사람이 직접 한다.
로그인을 마치면 이 크롬 창을 꼭 닫아 주세요. 열려 있으면 에이전트가 같은 프로필을 열 수 없습니다.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import profiles  # noqa: E402

CHROME_CANDIDATES = [
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
]


def main() -> None:
    names = [p["name"] for p in profiles()]
    if len(sys.argv) < 2 or sys.argv[1] not in names:
        print(f"사용법: python scripts/open_profile.py <프로필 이름>\n가능한 이름: {', '.join(names)}")
        sys.exit(1)
    profile = next(p for p in profiles() if p["name"] == sys.argv[1])
    chrome = next((c for c in CHROME_CANDIDATES if c.is_file()), None)
    if not chrome:
        print("크롬을 찾지 못했어요. Google Chrome 을 설치해 주세요.")
        sys.exit(1)

    profile["dir"].mkdir(parents=True, exist_ok=True)
    subprocess.Popen([
        str(chrome),
        f"--user-data-dir={profile['dir']}",
        "--no-first-run",
        "https://accounts.google.com/ServiceLogin?hl=ko&continue=https://www.youtube.com/?hl=ko",
    ])
    print(f"[{profile['name']}] 크롬을 열었어요 → {profile['dir']}")
    print("1. 게시용 구글 계정으로 로그인하세요.")
    print("2. 유튜브 오른쪽 위 프로필 사진이 보이면 완료예요. (채널이 없으면 유튜브에서 채널을 만들어 주세요)")
    print("3. 끝나면 이 크롬 창을 닫아 주세요. 열려 있으면 에이전트가 이 프로필을 쓸 수 없어요.")


if __name__ == "__main__":
    main()
