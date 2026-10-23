"""대시보드 실행: python run.py → 브라우저에서 http://127.0.0.1:8000 이 열린다."""
import threading
import webbrowser

import uvicorn

HOST, PORT = "127.0.0.1", 8000

if __name__ == "__main__":
    url = f"http://{HOST}:{PORT}"
    print(f"대시보드: {url}  (끄려면 Ctrl+C)")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT)
