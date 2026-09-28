"""判斷「應用程式所在資料夾」，讓 accounts.json / .env 這類使用者資料檔案
不管是用 `python app.py` 跑，還是打包成 .exe 後執行，都能在同一個地方找到。

PyInstaller 打包後 `__file__` 指向的是執行時解壓縮的暫存資料夾，不是 exe
實際的位置，所以「凍結」狀態下要改用 sys.executable 所在目錄。
"""

import sys
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
