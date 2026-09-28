"""Multi-Platform API 管理主控台 —— 入口程式。

雙擊執行（或 `python app.py`）即可開啟。第一次使用請先複製
accounts.example.json 為 accounts.json 並填入各帳戶憑證。
"""

import sys

# ⚠️ 這一段必須放在任何 PySide6.Qt* 匯入「之前」，順序不可調換，也不要被 isort 重排。
#
# 原因（2026-08-01 實測 PySide6 6.11.1）：shiboken6 會註冊一個 import hook
# （shibokensupport.feature.feature_imported），對之後每一個新匯入的模組呼叫
# inspect.getsource() 來判斷該模組有沒有用到 PySide6 的 feature 語法。
# 但 six 是用 _SixMetaPathImporter 憑空造出 six.moves.* 這種假模組，
# 這些假模組沒有 _path 屬性，inspect 走到最後會直接噴：
#     AttributeError: '_SixMetaPathImporter' object has no attribute '_path'
#
# 本專案的匯入鏈踩得到：main_window → label_handlers → label_utils → xhtml2pdf
#                       → html5lib → six.moves
# 所以只要 PySide6 先載入，App 一啟動就會 crash（打包成 exe 也一樣）。
# 實測：`import PySide6.QtWidgets; import xhtml2pdf.pisa` → crash
#       `import xhtml2pdf.pisa; import PySide6.QtWidgets` → 正常
#
# 注意：光 `import six.moves` 不夠。six.moves.* 是 _SixMetaPathImporter 在「被存取時」
# 才即時造出來的，html5lib 稍後那句 `from six.moves import http_client, urllib`
# 仍然會現場產生新模組並觸發 hook。必須把真正的使用者（xhtml2pdf → html5lib）
# 整條鏈都先載入完，該建立的假模組才會全部在 hook 註冊前就進 sys.modules。
# 反正 label_utils 本來就在模組層級匯入 xhtml2pdf，這裡只是把它提前，不增加啟動成本。
try:  # noqa: E402
    import xhtml2pdf.pisa  # noqa: F401  (只為了搶在 PySide6 之前進 sys.modules)
except ImportError:  # 沒裝 xhtml2pdf 時交給後面 label_utils 的匯入去報明確錯誤
    pass

from PySide6.QtWidgets import QApplication  # noqa: E402

from api_sync.ui.main_window import MainWindow  # noqa: E402


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
