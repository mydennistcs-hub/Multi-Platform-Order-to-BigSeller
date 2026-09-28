# -*- mode: python ; coding: utf-8 -*-
"""app.py（momo/Coupang/Shopify API 管理主控台）的 PyInstaller 打包設定。

用法：pyinstaller --noconfirm Multi-Platform-API-Console.spec
（`打包API主控台.bat` 就是呼叫這一行，設定全部集中在這裡，不要再散落到 .bat 的命令列參數）

2026-08-01 改版，把原本自動產生的版本整個重寫。原本 280MB、要跑好幾分鐘的三個原因：

1. `collect_all('PySide6')` —— 這是體積與耗時的最大元凶。
   app.py 只用到 QtCore / QtGui / QtWidgets（見 api_sync/ui/*.py 的 import），
   但 collect_all 會無差別把整包 Qt 塞進來：QtWebEngine（光這個就 ~130MB）、
   Qt3D、QtQuick/QML、QtCharts、QtMultimedia、QtPdf、翻譯檔、QML 模組……
   PyInstaller 6.x 內建的 PySide6 hook 本來就會依實際 import 只收需要的 Qt 函式庫，
   加了 collect_all 反而是把它的智慧關掉。改成不用 collect_all + 明確 excludes。

2. `--onefile` —— 打包時要把幾百 MB 壓成單一 exe（慢），
   而且**每次啟動 exe 都要先解壓縮到 %TEMP% 才跑得起來**，開啟要等數十秒。
   改成 onedir（資料夾版）：打包快很多，啟動幾乎是秒開。
   真的需要單一檔案帶去別台電腦時，把下面 ONEFILE 改成 True 再打包一次即可。

3. `--clean` —— 每次都砍掉 build 快取全量重建，Analysis 階段（最慢的一段）無法增量。
   已從 .bat 移除；只有換 Python/套件版本或出現詭異錯誤時才需要手動加。

reportlab 的 collect_all 必須保留：xhtml2pdf 依賴的
reportlab.graphics.barcode.code128 等子模組是動態載入，PyInstaller 靜態掃描抓不到，
少了會在使用者端跳 ModuleNotFoundError（見 CLAUDE.md 已知眉角）。

2026-08-05 追記：新增「訂單轉換」分頁（api_sync/ui/converter_panel.py）直接重用
converter.py 的 convert_orders()，所以這支 App 現在也真的用得到 xlrd（讀 mo店+ 舊版 .xls）
與 pdfplumber/pdfminer（讀取裝箱明細/運單 PDF 文字），原本 _OTHER_EXCLUDES 裡排除這兩者的
理由（「Phase 1 才用得到」）不成立了，改成跟 Phase 1 自己的
Multi-Platform-Order-to-BigSeller.spec 一樣做 collect_all（pdfplumber 有動態載入子模組）。
**tkinter 仍然排除**：converter.py 已經把 `import tkinter` 相關語句延後到檔案最下面
`if __name__ == "__main__":` 區塊（只有 converter.py 被直接執行、不是被匯入時才會跑到），
這支 App 呼叫的 convert_orders() 純邏輯完全不會走到那段，所以不需要打包 Tcl/Tk 執行環境。
"""

from PyInstaller.utils.hooks import collect_all

APP_NAME = "Multi-Platform-API-Console"

# 要單一 exe 檔（方便複製到別台電腦）就改 True，代價是打包慢、每次啟動要解壓縮
ONEFILE = False

datas = []
binaries = []
hiddenimports = [
    "requests",
    "dotenv",
    "msoffcrypto",
    "pypdf",
    "openpyxl",
    "xhtml2pdf",
    "xlrd",  # converter.py 讀 mo店+ 舊版 .xls 用
    # 2026-08-23：Coupang 全家/7-11 寄件單改用 QtWebEngine 轉 PDF（api_sync/qt_html_pdf.py）。
    # 那支模組是在函式內部才 import（避免拖慢啟動、也避開 app.py 的匯入順序限制），
    # 明確列在這裡確保 PyInstaller 一定收得到。
    "PySide6.QtWebEngineCore",
    "fitz",  # PyMuPDF，把渲染結果等比例貼到 A4
]

# 只對「有動態載入子模組」的套件做 collect_all，PySide6 交給內建 hook 自己判斷。
# pdfplumber/pdfminer 跟 Phase 1 自己的 .spec 一樣需要 collect_all（converter.py 讀 PDF 用）。
for _pkg in ("xhtml2pdf", "reportlab", "pdfplumber", "pdfminer"):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# app.py 完全沒用到的 Qt 子模組。排除它們可省下大量體積與 Analysis 時間。
# 注意：QtNetwork / QtPrintSupport / QtSvg / QtOpenGL 沒有列在這裡是刻意的，
# 它們體積小且常被 QtWidgets 間接需要，排掉可能導致執行期缺 DLL。
# ⚠️ 2026-08-23 起 QtWebEngineCore（連帶 QtWebChannel / QtQml / QtQuick / QtPositioning）
# **不能再排除**：Coupang 全家/7-11 的寄件單是 HTML，改用 QtWebEngine（Chromium）轉 PDF，
# 這是唯一能正確轉出這兩種標籤版面的方式（xhtml2pdf 對 7-11 直接轉不出來、對全家會把黑色
# 挖成透明，見 api_sync/qt_html_pdf.py）。代價是打包體積會明顯變大（QtWebEngine 約 130MB＋
# 資源檔），這是為了功能正確性刻意付出的成本，不要為了縮小體積把它加回 excludes。
# 日常自用建議還是用 `啟動API主控台.bat` 直接跑原始碼，不受打包體積影響。
_QT_EXCLUDES = [
    "PySide6.QtQuick3D",
    "PySide6.QtQuickTest",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtGraphsWidgets",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtSpatialAudio",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    # QtPositioning 不能排除：QtWebEngineCore 會相依它（Geolocation API），排掉打包後
    # 會在使用者端缺 DLL。QtLocation 是另一個模組，QtWebEngine 用不到，維持排除。
    "PySide6.QtLocation",
    "PySide6.QtSerialPort",
    "PySide6.QtSerialBus",
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",
    "PySide6.QtHelp",
    "PySide6.QtTest",
    "PySide6.QtSql",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSensors",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech",
    "PySide6.QtNetworkAuth",
    "PySide6.QtHttpServer",
    "PySide6.QtNfc",
]

# 這支 App 完全用不到的東西
#
# tkinter：converter.py 裡的 `import tkinter` 相關語句已延後到檔案最下面
# `if __name__ == "__main__":` 區塊（見上方 2026-08-05 追記），這支 App 只呼叫
# convert_orders() 這個純邏輯函式，永遠不會走到那段，所以還是能安全排除、省下 Tcl/Tk
# 執行環境的體積。pdfplumber/pdfminer 已改為「訂單轉換」分頁的真實相依，不能再排除
# （見上方 hiddenimports/collect_all）。
#
# numpy 說明：它不是我們直接用的，是 PIL 的「選用」相依——PIL.Image 內部用
# try: import numpy 來支援 Image.fromarray()，PyInstaller 的模組圖就把整包
# numpy + numpy.libs（含 20MB 的 openblas DLL）一起收進來，合計約 26MB。
# 實測（用 meta_path 攔截 numpy 後匯入）xhtml2pdf / reportlab.graphics.barcode
# / PIL.Image 全部正常，本 App 也沒有任何地方走 fromarray，所以排除掉是安全的。
_OTHER_EXCLUDES = [
    "tkinter",
    "numpy",
    "matplotlib",
    "scipy",
    "pandas",
    "IPython",
    "pytest",
    "PyQt5",
    "PyQt6",
    "PySide2",
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_QT_EXCLUDES + _OTHER_EXCLUDES,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,  # UPX 逐一壓縮上百個 Qt DLL 非常慢，省下的體積對本機使用沒意義
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )
