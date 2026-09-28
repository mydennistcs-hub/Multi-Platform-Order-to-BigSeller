"""用 QtWebEngine（Chromium）把物流寄件單 HTML 轉成可直接列印的 PDF。

為什麼不用 xhtml2pdf（2026-08-23 實測確認，兩個平台各踩一個坑）：

- **7-11 交貨便服務單**：那份 HTML 是給瀏覽器列印的實體標籤版面（巢狀表格＋窄欄位＋
  外部 CSS＋QR 圖檔），xhtml2pdf 直接噴 reportlab 內部錯誤
  （`PmlTable ... flowable given negative availWidth`）轉不出來，只能退回存 HTML。
- **全家寄取貨單**：xhtml2pdf「轉得出來」但成品是壞的——它把整張標籤圖片
  （2615x4271）嵌進 PDF 時附帶了 `/Mask [0 0 0 0 0 0]` 這個 colour-key 遮罩，
  意思是「RGB 純黑的像素一律視為透明」，於是條碼、黑底白字、粗框線這些真正是純黑的
  部分**整片被挖成透明**，只剩抗鋸齒的灰色邊緣，看起來就是使用者說的「模糊」。
  圖片本身其實是清楚的，是嵌入方式壞掉，所以不是調參數就能修好的問題。

QtWebEngine 用的就是 Chromium，跟使用者原本「在後台用瀏覽器列印成 PDF」是同一個
渲染引擎，文字保持向量、黑色就是黑色、外部 CSS/QR 圖檔照常載入，這兩個坑都不存在。

輸出格式的設計（見 `LABEL_FIT_*` 常數）：
1. 先用「A4 寬 × 超長頁面」渲染一次，避免標籤在自然尺寸下剛好跨頁被切成兩半——
   使用者原本手動流程最麻煩的一點就是「全家的會跑到第 2 頁，要在列印裡自訂第 2 頁」。
2. 再量出實際有內容的範圍（ink bbox），等比例放大後貼到一張 A4 上、靠左上角對齊。
   等比例＝不會變形，靠左上＝跟後台下載的檔案一樣方便裁切。
"""

import os
import tempfile

# A4 與版面設定（單位 mm）。使用者原本手動列印是把 7-11 標籤放大到約 174×252mm（實測
# 後台下載檔＝自然尺寸的 2 倍）並沿虛線裁切，這裡的「放大到填滿 A4 可列印範圍」等效於
# 同一個做法，差別只在不用每次自己去列印對話框調縮放比例。
A4_WIDTH_MM = 210.0
A4_HEIGHT_MM = 297.0
LABEL_FIT_MARGIN_MM = 10.0
# 內容小到不合理時（例如 API 哪天回一張只有一行字的 HTML）不要無限放大，設一個上限。
LABEL_FIT_MAX_SCALE = 3.0
# 渲染用的頁面高度：夠長就不會分頁，PDF 規格上限是 200 英吋（5080mm），取 1200mm 保守。
_RENDER_PAGE_HEIGHT_MM = 1200.0
# 內容比 A4 寬時會被 Chromium 裁掉右半邊。偵測到就用這個寬度重畫一次（之後反正會等比例縮到
# A4，畫布寬一點不影響成品，只是多花一次渲染時間）。目前已知的兩種寄件單都不會走到這條路，
# 這是給「哪天平台把標籤 HTML 改成固定大尺寸」時的保險。
_RENDER_WIDE_WIDTH_MM = 630.0
# loadFinished 之後再等一下讓外部圖片（7-11 的 QR 圖是打 epayment.7-11.com.tw 取回來的）畫完。
_SETTLE_MS = 1500
_LOAD_TIMEOUT_MS = 60000

_MM_PER_PT = 25.4 / 72.0


def _mm_to_pt(mm: float) -> float:
    return mm / _MM_PER_PT


def render_html_to_pdf(html: str, out_path: str, base_url: str = "", fit_to_a4: bool = True) -> None:
    """把 HTML 轉成 PDF 寫到 out_path。必須在 Qt 主執行緒呼叫（App 內就是主執行緒）。

    base_url 給相對路徑用；Coupang 兩家超商的 HTML 都是絕對網址，可以不給。
    fit_to_a4=False 時輸出瀏覽器自然尺寸（A4 寬 × 超長頁），只有需要原始尺寸時才用。
    """
    raw_pdf = _render_natural(html, base_url, A4_WIDTH_MM)
    if not raw_pdf:
        raise RuntimeError("QtWebEngine 沒有產出任何 PDF 內容（頁面可能載入失敗）")
    if _looks_clipped(raw_pdf):
        wider = _render_natural(html, base_url, _RENDER_WIDE_WIDTH_MM)
        if wider:
            raw_pdf = wider
    if not fit_to_a4:
        with open(out_path, "wb") as f:
            f.write(raw_pdf)
        return
    _fit_pages_to_a4(raw_pdf, out_path)


def _render_natural(html: str, base_url: str, page_width_mm: float) -> bytes:
    # 這幾個 import 放在函式內部：模組載入階段就 import QtWebEngine 會拖慢 App 啟動，
    # 而且 app.py 對「PySide6 要在 xhtml2pdf 之後 import」有嚴格的順序要求（見 CLAUDE.md），
    # 延後到真正要轉檔時才載入最安全。
    from PySide6.QtCore import QEventLoop, QMarginsF, QSizeF, QTimer, QUrl
    from PySide6.QtGui import QPageLayout, QPageSize
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:  # 測試腳本直接呼叫時（App 內一定已經有一個）
        app = QApplication([])

    # setHtml() 有約 2MB 的內容長度上限，全家那種內嵌大圖的 HTML 很容易超過，
    # 改成寫暫存檔再 load()，沒有這個限制，相對路徑也有正確的 base url 可解析。
    tmp_dir = tempfile.mkdtemp(prefix="coupang_label_")
    tmp_html = os.path.join(tmp_dir, "label.html")
    with open(tmp_html, "w", encoding="utf-8") as f:
        f.write(_with_base_url(html, base_url))

    page = QWebEnginePage()
    settings = page.settings()
    attr = QWebEngineSettings.WebAttribute
    # Chromium 列印預設可能略過背景色/背景圖，全家標籤有黑底白字的區塊，一定要打開。
    settings.setAttribute(attr.PrintElementBackgrounds, True)
    # ⚠️ 這兩個不開，用 file:// 載入的頁面會被當成本機內容、**擋掉所有遠端資源**：
    # 7-11 交貨便服務單的排版 CSS（epayment.7-11.com.tw/.../C2CQrCodePrint.css）與兩張 QR
    # 圖檔都是絕對 https 網址，被擋掉的結果是「QR 變成破圖、字級回到瀏覽器預設值而撐爆表格」
    # ——2026-08-23 實測踩過，畫面看起來像版面壞掉，其實是資源沒載到。
    settings.setAttribute(attr.LocalContentCanAccessRemoteUrls, True)
    settings.setAttribute(attr.LocalContentCanAccessFileUrls, True)

    holder: dict = {}
    loop = QEventLoop()

    def on_pdf(data):
        holder["pdf"] = bytes(data)
        loop.quit()

    def do_print():
        size = QPageSize(
            QSizeF(page_width_mm, _RENDER_PAGE_HEIGHT_MM), QPageSize.Unit.Millimeter, "LabelTall"
        )
        layout = QPageLayout(size, QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0))
        page.printToPdf(on_pdf, layout)

    def on_load(ok):
        if not ok:
            holder["error"] = "頁面載入失敗（QtWebEngine 回報 loadFinished=False）"
            loop.quit()
            return
        QTimer.singleShot(_SETTLE_MS, do_print)

    page.loadFinished.connect(on_load)
    page.load(QUrl.fromLocalFile(tmp_html))
    QTimer.singleShot(_LOAD_TIMEOUT_MS, loop.quit)
    loop.exec()

    try:
        os.remove(tmp_html)
        os.rmdir(tmp_dir)
    except OSError:
        pass

    if holder.get("error"):
        raise RuntimeError(holder["error"])
    return holder.get("pdf", b"")


def _with_base_url(html: str, base_url: str) -> str:
    """有給 base_url 時插一個 <base>，讓 HTML 裡的相對路徑照樣解析得到。
    Coupang 兩家超商的寄件單 HTML 用的都是絕對網址，實務上不需要，留著給未來別的來源用。"""
    if not base_url:
        return html
    tag = f'<base href="{base_url}">'
    lower = html.lower()
    idx = lower.find("<head>")
    if idx >= 0:
        return html[: idx + len("<head>")] + tag + html[idx + len("<head>") :]
    return tag + html


def _looks_clipped(raw_pdf: bytes) -> bool:
    """內容有沒有被畫布寬度裁掉：任何一頁的內容右緣幾乎貼齊頁面右緣就算有。"""
    import fitz

    doc = fitz.open(stream=raw_pdf, filetype="pdf")
    try:
        for page in doc:
            ink = _ink_bbox(page)
            if ink is not None and ink.x1 >= page.rect.x1 - _mm_to_pt(0.5):
                return True
    finally:
        doc.close()
    return False


def _fit_pages_to_a4(raw_pdf: bytes, out_path: str) -> None:
    """把自然尺寸的渲染結果等比例放大貼到 A4 上（靠左上、留 10mm 邊界）。

    用 PyMuPDF 的 show_pdf_page 貼上去，來源是向量內容時仍然保持向量（不是先轉成點陣圖
    再貼），所以放大不會糊掉。空白頁（例如 HTML 結尾的 page-break-after 產生的多餘一頁）
    直接略過，不要輸出一堆空白紙。
    """
    import fitz  # PyMuPDF

    src = fitz.open(stream=raw_pdf, filetype="pdf")
    out = fitz.open()
    usable_w = _mm_to_pt(A4_WIDTH_MM - 2 * LABEL_FIT_MARGIN_MM)
    usable_h = _mm_to_pt(A4_HEIGHT_MM - 2 * LABEL_FIT_MARGIN_MM)
    margin = _mm_to_pt(LABEL_FIT_MARGIN_MM)

    for pno in range(src.page_count):
        ink = _ink_bbox(src[pno])
        if ink is None:
            continue
        scale = min(usable_w / ink.width, usable_h / ink.height, LABEL_FIT_MAX_SCALE)
        target = fitz.Rect(
            margin, margin, margin + ink.width * scale, margin + ink.height * scale
        )
        new_page = out.new_page(
            width=_mm_to_pt(A4_WIDTH_MM), height=_mm_to_pt(A4_HEIGHT_MM)
        )
        new_page.show_pdf_page(target, src, pno, clip=ink)

    if out.page_count == 0:  # 整份都量不到內容：原樣輸出，不要給使用者一個 0 頁的空 PDF
        with open(out_path, "wb") as f:
            f.write(raw_pdf)
        src.close()
        out.close()
        return

    out.save(out_path)
    out.close()
    src.close()


def _ink_bbox(page):
    """量出這一頁真正有內容（文字／向量繪圖／圖片）的範圍，空白頁回 None。"""
    import fitz

    rect = fitz.Rect()
    for block in page.get_text("blocks"):
        rect |= fitz.Rect(block[:4])
    for drawing in page.get_drawings():
        rect |= drawing["rect"]
    for info in page.get_image_info():
        rect |= fitz.Rect(info["bbox"])
    if rect.is_empty or rect.width <= 0 or rect.height <= 0:
        return None
    return rect & page.rect
