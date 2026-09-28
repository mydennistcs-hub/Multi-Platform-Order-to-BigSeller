"""物流寄件單/標籤相關的檔案處理：base64 存檔、HTML 轉 PDF、URL 下載、best-effort 解密。

momo/Coupang 回傳寄件單的格式不統一（base64 字串、下載網址、PDF 本體、HTML 本體），
這裡統一封裝成「輸入什麼格式 → 一律存成看得到的檔案」，呼叫端不用管細節。
"""

import base64
import io
import re
import sys


def _ensure(pkg, mod=None):
    import importlib
    import subprocess

    try:
        importlib.import_module(mod or pkg)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])


_ensure("requests")
_ensure("xhtml2pdf")
_ensure("msoffcrypto-tool", "msoffcrypto")
_ensure("pypdf")

import requests  # noqa: E402
import msoffcrypto  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402
from xhtml2pdf import pisa  # noqa: E402


def save_base64(data_b64: str, out_path: str):
    """momo 超商出貨確認/重印標籤回傳的 base64 字串，解碼後直接存檔（副檔名由呼叫端決定）。"""
    raw = base64.b64decode(data_b64)
    with open(out_path, "wb") as f:
        f.write(raw)


def download_url_to_file(url: str, out_path: str, timeout: int = 30):
    """momo 第三方物流出貨確認回傳的是下載網址，直接下載存檔。"""
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(resp.content)


def html_to_pdf(html_content: str, out_path: str):
    """⚠️ 已不用於 Coupang 寄件單（2026-08-23 起改用 `api_sync/qt_html_pdf.py` 的 QtWebEngine）。

    xhtml2pdf 對兩家超商的寄件單各壞一種：7-11 直接轉不出來（reportlab 噴
    `PmlTable ... negative availWidth`），全家轉得出來但整張標籤的純黑像素被
    `/Mask [0 0 0 0 0 0]` colour-key 遮罩挖成透明（＝使用者看到的「模糊」）。
    這支函式保留給其他來源的簡單 HTML 用，也維持 `xhtml2pdf` 的模組層級匯入
    （`app.py` 的匯入順序依賴它，見 CLAUDE.md）。
    """
    with open(out_path, "wb") as f:
        result = pisa.CreatePDF(io.StringIO(html_content), dest=f)
    if result.err:
        raise RuntimeError(f"HTML 轉 PDF 失敗（xhtml2pdf 回報 {result.err} 個錯誤）")


def guess_extension(raw: bytes) -> str:
    """momo 回傳的 base64 內容沒說是 PDF 還是圖片，用檔頭魔數猜副檔名。"""
    if raw[:4] == b"%PDF":
        return ".pdf"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if raw[:2] == b"\xff\xd8":
        return ".jpg"
    if raw[:2] == b"PK":  # docx/xlsx 等 OOXML 也是 zip 開頭，無法細分，先當 zip 存
        return ".zip"
    return ".bin"


def save_label_content(content: str, out_path_without_ext: str, password: str = None) -> str:
    """content 可能是下載網址（momo 第三方物流）或 base64 字串（momo 超商），自動判斷處理。
    password 有給時，會對內容嘗試 best-effort 解密（給可能加密的 printDetail 欄位用，
    沒有加密或格式不符時原樣寫檔，不會噴例外中斷流程）。回傳實際寫入的完整檔案路徑。
    """
    if content.startswith("http://") or content.startswith("https://"):
        resp = requests.get(content, timeout=30)
        resp.raise_for_status()
        raw = resp.content
    else:
        raw = base64.b64decode(content)

    if password:
        raw = try_decrypt_office_bytes(raw, password)

    out_path = out_path_without_ext + guess_extension(raw)
    with open(out_path, "wb") as f:
        f.write(raw)
    return out_path


def try_decrypt_office_bytes(raw: bytes, password: str) -> bytes:
    """momo 重印標籤文件提到 printDetail「字串流，請用統編解密」，但沒說是哪種加密格式。
    Best-effort：先試 Office(CFB/OOXML) 加密格式，再試 PDF 密碼保護；都不是就原樣回傳，
    不強制成功（呼叫端應該把回傳內容存檔讓使用者自行確認能不能打開）。
    """
    try:
        of = msoffcrypto.OfficeFile(io.BytesIO(raw))
        if of.is_encrypted():
            of.load_key(password=password)
            buf = io.BytesIO()
            of.decrypt(buf)
            return buf.getvalue()
    except Exception:
        pass

    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            reader.decrypt(password)
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            buf = io.BytesIO()
            writer.write(buf)
            return buf.getvalue()
    except Exception:
        pass

    return raw


# 7-11 交貨便服務單 HTML 裡「交貨便服務代碼」的欄位 id（ASP.NET 產生的固定 id）。
_SEVEN_PIN_CODE_RE = re.compile(
    r'id="ctl00_Bill1_lblC2BPinCode"[^>]*>\s*([A-Za-z0-9]+)\s*<', re.IGNORECASE
)
# 備援：萬一哪天 7-11 改了 id，改用畫面上的中文標籤抓。
_SEVEN_PIN_CODE_FALLBACK_RE = re.compile(r"交貨便服務代碼[：:]\s*(?:<[^>]+>\s*)?([A-Za-z0-9]{8,20})")


def extract_seven_eleven_service_code(html: str) -> str | None:
    """從 7-11 交貨便服務單 HTML 抓出完整的「交貨便服務代碼」（例：E89667925349）。

    為什麼需要這支：Coupang `arrangeShipment` 回的 `invoiceNumber` 只有**前 8 碼**
    （例：E8966792），但 7-11 實際認的、Wing 後台 DeliveryList 匯出的「寄件單號」是
    **完整 12 碼**（E89667925349）——少的那 4 碼只出現在寄件單本身，API 任何欄位都拿不到
    （2026-08-23 比對使用者的真實訂單確認：HTML 裡的 QR 內容 `E89667927000001`、物流條碼
    `89B001E896679246` 都不含那 4 碼，只有 `lblC2BPinCode` 這個欄位有）。
    所以只能在下載寄件單時順手從 HTML 裡撈出來補齊。

    抓不到時回 None（呼叫端要維持原本的運單號，不要自己湊）。
    """
    if not html:
        return None
    for pattern in (_SEVEN_PIN_CODE_RE, _SEVEN_PIN_CODE_FALLBACK_RE):
        m = pattern.search(html)
        if m:
            return m.group(1).strip()
    return None
