import threading
import os
import re
from datetime import datetime
from collections import OrderedDict

# 注意：tkinter 相關匯入（tk/filedialog/ttk/scrolledtext/messagebox）刻意不放在這裡，
# 而是延後到檔案最下面的 `if __name__ == "__main__":` 區塊才匯入。
# 原因：本檔案的 convert_orders() 等函式是純邏輯（只吃 log/progress callback，不碰任何 GUI
# 元件），2026-08-05 起也被 api_sync/ui/converter_panel.py 用 `import converter` 的方式直接
# 重用，改用 PySide6 元件另外重畫一份 UI（見 CLAUDE.md「訂單轉換」分頁說明）。converter.py 本身
# 邏輯完全不變，只是讓「純邏輯」跟「Tkinter 版 GUI 進入點」的匯入解耦——這樣 Phase 2 的 App
# 匯入這支檔案時就不需要連帶打包 Tkinter/Tcl-Tk 執行環境（Phase 2 的 PyInstaller spec 因此可以
# 繼續排除 tkinter，見該檔案註解）。`class App` 內部方法（_build_ui 等）仍大量用到 tk./ttk./
# filedialog./messagebox./scrolledtext.，這些是模組全域名稱、在方法「被呼叫時」才需要存在，
# 不是在 class 定義當下就要存在，所以只要在 App(root) 真正被建立之前完成這個匯入即可（見檔尾）。

# ── Auto-install dependencies ──────────────────────────────────────────────────
def _ensure(pkg, mod=None):
    import importlib, subprocess, sys
    try:
        importlib.import_module(mod or pkg)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

_ensure("openpyxl")
_ensure("xlrd")
_ensure("pdfplumber")
_ensure("pypdf")
_ensure("msoffcrypto-tool", "msoffcrypto")

import io
import openpyxl
import xlrd
import msoffcrypto
import pdfplumber
from pypdf import PdfReader, PdfWriter
from openpyxl.utils import get_column_letter

# ── mo店+ 來源欄位 (1-based) ────────────────────────────────────────────────────
MO = {
    "order_no":   1,   # A  訂單編號
    "status":     3,   # C  訂單狀態
    "order_date": 9,   # I  轉單日
    "sku":        24,  # X  商品原廠編號
    "qty":        25,  # Y  數量
    "recipient":  27,  # AA 收件人姓名
    "address":    29,  # AC 收件人地址
    "logistics":  31,  # AE 物流商
    "tracking":   32,  # AF 物流單號
    "price":      41,  # AO 商品售價（新版 mo店+ 匯出；實際以表頭定位）
}

# ── Coupang 來源欄位 (1-based) ─────────────────────────────────────────────────
COUPANG = {
    "order_no":   3,   # C  訂單編號
    "logistics":  5,   # E  快遞公司
    "tracking":   6,   # F  寄件單號
    "order_date": 11,  # K  訂購日期
    "sku":        18,  # R  公司商品代碼
    "qty":        23,  # W  數量
    "price":      24,  # X  選項價格
    "recipient":  25,  # Y  訂購人姓名
    "address":    28,  # AB 收件人地址
}

# ── BigSeller 目標欄位 (1-based) ────────────────────────────────────────────────
BS = {
    "store":     1,    # A
    "order_no":  2,    # B
    "date":      3,    # C
    "warehouse": 5,    # E  发货仓库
    "recipient": 7,    # G  收件人姓名（新版模板新增 F 客户编码；實際以表頭定位）
    "address":   15,   # O  详细地址
    "discount":  22,   # V  优惠
    "logistics": 23,   # W  物流名称
    "tracking":  24,   # X  运单号
    "sku":       28,   # AB 店铺SKU
    "price":     30,   # AD 单价
    "qty":       31,   # AE 数量
}

# mo店+ 後台匯出檔的「統編」欄是賣家自己的統編（實測 2026-11-11 匯出檔＝94234570），
# 用來檢查使用者選的公司是否正確；舊格式沒有這欄時不檢查。
MO_SELLER_TAX_ID_HEADER = "統編"

# mo店+ 後台「匯出報表」的實際入帳欄（訂單層級，同一張單每個品項列重複同一個數字）。
# 2026-11-15 實測欄名是「訂單進帳金額」；文件曾寫成「訂單入帳金額」，兩種都認。
# 舊的 API 匯出 .xlsx 沒有這兩欄，此時退回舊的 PLATFORM_FEE 估算並在 log 警告。
MO_INCOME_HEADERS = ("訂單進帳金額", "訂單入帳金額")
MO_FEE_ADJ_HEADER = "(預估)手續費_調整金額"

MO_HEADERS = {
    "order_no":   ("訂單編號",),
    "status":     ("訂單狀態",),
    "order_date": ("轉單日",),
    "sku":        ("商品原廠編號",),
    "qty":        ("數量",),
    "recipient":  ("收件人姓名",),
    "address":    ("收件人地址",),
    "logistics":  ("物流商",),
    "tracking":   ("物流單號",),
    "price":      ("商品售價",),
}

COUPANG_HEADERS = {
    "order_no":   ("訂單編號",),
    "logistics":  ("快遞公司",),
    "tracking":   ("寄件單號",),
    "order_date": ("訂購日期",),
    "sku":        ("公司商品代碼",),
    "qty":        ("數量",),
    "price":      ("選項價格",),
    "recipient":  ("訂購人姓名",),
    "address":    ("收件人地址",),
}

BS_HEADERS = {
    "store":     ("店铺",),
    "order_no":  ("订单号",),
    "date":      ("下单时间",),
    "warehouse": ("发货仓库",),
    "recipient": ("收件人姓名",),
    "address":   ("详细地址",),
    "discount":  ("优惠",),
    "logistics": ("物流名称",),
    "tracking":  ("运单号",),
    "sku":       ("店铺SKU",),
    "price":     ("单价",),
    "qty":       ("数量",),
}

MO_STORE = "mo店+"
WAREHOUSE = "樸翔初耘18號8樓 mo店+倉庫"
COUPANG_STORE = "酷澎 coupang"
COUPANG_WAREHOUSE = "樸翔初耘18號8樓 Coupang倉庫"

BS_DATA_ROW  = 5
PLATFORM_FEE = 0.235
# Coupang 优惠＝round(訂單商品金額 × 手續費率) ＋ 每張訂單代開發票費（2026-11-15 使用者拍板）。
# 14.5% 是加入免運補貼專案後的費率（格魯維爾 2025-06-04 起、丹尼書 2026-11-03 起都已加入）。
COUPANG_PLATFORM_FEE = 0.145
COUPANG_INVOICE_FEE_PER_ORDER = 2

# 公司 → 統編。兩家公司的店鋪名稱與倉庫相同（2026-11-12 使用者確認），
# 只有店鋪 SKU 後綴不同：mo店+ 為 -mo{統編}、Coupang 為 -cou{統編}。
COMPANIES = {
    "格魯維爾": "94234570",
    "丹尼書": "90154390",
}
DEFAULT_COMPANY = "格魯維爾"


def mo_sku_suffix(tax_id: str) -> str:
    return f"-mo{tax_id}"


def coupang_sku_suffix(tax_id: str) -> str:
    return f"-cou{tax_id}"


# 舊常數保留（＝格魯維爾），供既有外部引用；轉檔一律改用依公司計算的後綴。
SKU_SUFFIX   = mo_sku_suffix(COMPANIES[DEFAULT_COMPANY])
COUPANG_SKU_SUFFIX   = coupang_sku_suffix(COMPANIES[DEFAULT_COMPANY])
# 寄件人地址關鍵字（用於排除寄件人地址）
SENDER_KW = ["MOMO", "格魯維爾", "丹尼書", "南園二路"]

# 台灣地址完整格式（縣市＋路街巷弄＋門牌號），extract_pdf_data() 的第 2、4 步共用。
ADDR_RE = re.compile(
    r'((?:台北|新北|桃園|台中|台南|高雄|基隆|新竹|苗栗|彰化|南投'
    r'|雲林|嘉義|屏東|宜蘭|花蓮|台東|澎湖|金門|連江'
    r'|臺北|臺中|臺南|臺東)[市縣][^\n]{3,40}(?:路|街|巷|弄)[^\n]{1,15}號[^\n]{0,10})'
)

# ── PDF 處理 ───────────────────────────────────────────────────────────────────

def decrypt_and_save(pdf_path: str, password: str) -> dict:
    """
    最佳努力移除 PDF 密碼，失敗時不拋例外。
    回傳：
      {
        "encrypted": bool,   # 是否判定為加密 PDF（或可能加密）
        "removed": bool,     # 是否成功移除密碼並覆蓋原檔
        "warning": str|None  # 非致命警告訊息（解密失敗時使用）
      }
    """
    status = {"encrypted": False, "removed": False, "warning": None}

    # 把整個 PDF 讀進記憶體，完全釋放檔案鎖
    try:
        with open(pdf_path, "rb") as f:
            raw = io.BytesIO(f.read())
    except Exception as exc:
        status["warning"] = f"無法讀取 PDF 進行解密，改為直接解析：{exc}"
        return status

    try:
        reader = PdfReader(raw)
    except Exception as exc:
        status["encrypted"] = True
        status["warning"] = f"無法初始化解密器，改為直接解析：{exc}"
        return status

    try:
        is_encrypted = reader.is_encrypted
    except Exception as exc:
        status["encrypted"] = True
        status["warning"] = f"無法判定 PDF 是否加密，改為直接解析：{exc}"
        return status

    if not is_encrypted:
        return status

    status["encrypted"] = True

    # 嘗試字串與 bytes 兩種格式
    if not password:
        status["warning"] = "PDF 已加密但未提供密碼，改為直接解析"
        return status

    decrypted = False
    last_error = None
    for pw in [password, password.encode("utf-8")]:
        raw.seek(0)
        try:
            reader = PdfReader(raw)
            if reader.decrypt(pw) != 0:
                decrypted = True
                break
        except Exception as exc:
            last_error = exc
            continue

    if not decrypted:
        if last_error:
            status["warning"] = f"PDF 解密失敗，改為直接解析：{last_error}"
        else:
            status["warning"] = "PDF 解密失敗，改為直接解析"
        return status

    # 逐頁複製（不帶入加密字典）
    writer = PdfWriter()
    try:
        for page in reader.pages:
            writer.add_page(page)
        with open(pdf_path, "wb") as f:
            writer.write(f)
    except Exception as exc:
        status["warning"] = f"PDF 已解密但移除密碼失敗，改為直接解析：{exc}"
        return status

    status["removed"] = True
    return status


def extract_pdf_text(pdf_path: str, password: str = "") -> str:
    """用 pdfplumber 擷取 PDF 全文；若有密碼則優先用密碼開啟。"""
    attempts = []
    if password:
        attempts.append({"password": password})
    attempts.append({})

    last_exc = None
    for kwargs in attempts:
        try:
            text = ""
            with pdfplumber.open(pdf_path, **kwargs) as pdf:
                for page in pdf.pages:
                    t = page.extract_text() or ""
                    text += t + "\n"
            return text
        except Exception as exc:
            last_exc = exc
            continue

    raise last_exc


def _lines_after(text: str, keyword: str, max_lines: int = 5):
    """在 text 中找到 keyword 後，回傳之後最多 max_lines 個非空行。"""
    idx = text.find(keyword)
    if idx == -1:
        return []
    after = text[idx + len(keyword):]
    result = []
    for line in after.split("\n"):
        s = line.strip()
        if s and s != keyword.strip():
            result.append(s)
            if len(result) >= max_lines:
                break
    return result


def extract_pdf_data(text: str) -> dict:
    """
    從 PDF 文字擷取：訂單號、物流單號、收件人姓名、收件地址。
    同時支援「運單」與「裝箱明細」格式。
    """
    result = {"order_no": None, "tracking": None, "recipient": None, "address": None, "store_name": None}

    # 1. 訂單號（排除「寄貨訂單編號」）
    m = re.search(r'(?<!貨)訂單編號[：:]\s*(\w+)', text)
    if m:
        result["order_no"] = m.group(1).strip()

    # 2. 物流單號（依序嘗試各種格式）
    for pattern in [
        r'配送編號[：:]\s*(\S+)',        # 裝箱明細（宅配 / 超商）
        r'交貨便服務代碼[：:]\s*(\S+)',  # 超商運單
        r'宅配單號\s*(\d+)',             # 宅配運單
        r'物流條碼[：:]\s*(\S+)',        # 其他
    ]:
        m = re.search(pattern, text)
        if m:
            result["tracking"] = m.group(1).strip()
            break

    # 2-2. 超商取件門市（超商運單標籤上的門市名稱，例如 7-11 交貨便「取件／：旺泰／門市」）。
    # 這個標籤是直書兩行標題「取件」「門市」中間夾一行「：門市名稱」，pdfplumber 抽取文字時
    # 這幾個片段的順序常被打散（實測看到「取件」「旺泰」「：」「門市」這種順序，值反而排在
    # 冒號前面），不能假設固定順序，改用「取件」與（不遠處的）「門市」之間的所有文字，
    # 去除冒號與空白後剩下的就是門市名稱。用 `(?!人)` 避免比對到後面的「取件人」欄位。
    m = re.search(r'取件(?!人)(.{0,20}?)門市', text, re.S)
    if m:
        store_name = re.sub(r'[：:\s]', '', m.group(1))
        if store_name:
            result["store_name"] = store_name

    # 2. 優先從「收執聯」段落取得完整收件人資訊
    collect_idx = text.find("收執聯")
    if collect_idx != -1:
        section = text[collect_idx:]
        lines = _lines_after(section, "收件人", max_lines=6)
        # lines[0] = 地址, lines[1] = 電話, lines[2] = 姓名+郵遞區號
        for line in lines:
            # 識別地址行：整行要能獨立比對出「縣市＋路街巷弄＋門牌號」的完整地址格式（跟第 4 步
            # 共用 ADDR_RE），不能只靠「這行含路/街/巷/弄/號其中一個字」這種寬鬆判斷——實測部份
            # 物流標籤（例如第三方物流/新竹貨運）用直書「收/件/人」欄位標籤，pdfplumber 擷取文字
            # 時會把同一段地址切成兩行（例如「...南園二路381巷18」和下一行「號8樓」），前一行因為
            # 含寄件人街名被 SENDER_KW 排除後，寬鬆判斷會誤把地址「後半截殘片」（例如「人 號8樓
            # 款」）當成收件地址存下來（2026-08-02 使用者實測踩到：BigSeller 匯入檔的詳細地址
            # 變成一段沒有意義的殘片）。改成嚴謹格式驗證後，殘片格式對不上就不會被接受，程式會
            # 改用下面第 4 步的全文搜尋 fallback（用完整字串比對，不受行內斷行影響）。
            addr_match = ADDR_RE.search(line)
            if addr_match and not any(kw in line for kw in SENDER_KW):
                if not result["address"]:
                    result["address"] = addr_match.group(1).strip()
            # 識別姓名行（中文字 + 空格 + 郵遞區號）
            nm = re.match(r'^([\u4e00-\u9fff]{2,6})\s+\d{3,6}\s*$', line)
            if nm and not result["recipient"]:
                result["recipient"] = nm.group(1)

    # 3. 裝箱明細格式：收 件 人：姓名
    if not result["recipient"]:
        m = re.search(r'收\s*件\s*人[：:]\s*([^\s\d印]{2,6})', text)
        if m and '*' not in m.group(1):
            result["recipient"] = m.group(1).strip()

    # 3-2. 運單備援：取件人（允許遮罩姓名，如 吳*翰）
    if not result["recipient"]:
        for pattern in [
            r'取\s*件\s*人[：:]\s*([\u4e00-\u9fff*]{2,8})',
            r'([\u4e00-\u9fff*]{2,8})\s*取\s*件\s*人[：:]',
        ]:
            m = re.search(pattern, text)
            if m:
                name = m.group(1).strip()
                if not any(x in name for x in ["物流", "門市", "寄件", "收件", "取件"]):
                    result["recipient"] = name
                    break

    # 4. 若還沒有地址，全文搜尋台灣地址（跟第 2 步共用 ADDR_RE，不受行內斷行影響）
    if not result["address"]:
        for m in ADDR_RE.finditer(text):
            addr = m.group(1).strip()
            if not any(kw in addr for kw in SENDER_KW):
                result["address"] = addr
                break

    return result


def process_pdfs(pdf_paths: list, password: str, log) -> tuple[dict, dict]:
    """
    批次處理 PDF。
    回傳 (pdf_by_order, pdf_by_tracking)：
      pdf_by_order   = {訂單號: {recipient, address, store_name, tracking}}
      pdf_by_tracking = {物流單號: {recipient, address, store_name, tracking}}  ← 無訂單號的 PDF（如超商運單）
    """
    pdf_by_order:    dict = {}
    pdf_by_tracking: dict = {}

    for pdf_path in pdf_paths:
        fname = os.path.basename(pdf_path)
        try:
            dec = decrypt_and_save(pdf_path, password)
            if dec.get("removed"):
                log(f"  [已解密並移除密碼] {fname}")
            elif dec.get("warning"):
                log(f"  [警告] {fname}: {dec['warning']}")

            try:
                text = extract_pdf_text(pdf_path, password=password)
            except Exception as text_exc:
                log(f"  [錯誤] {fname}: 無法解析 PDF 文字：{text_exc}")
                continue

            if not text.strip():
                log(f"  {fname} → PDF 沒有可抽取文字，可能是掃描/圖片型物流標籤，無法自動讀取訂單號或物流單號")
                continue

            info = extract_pdf_data(text)

            order_no = info.get("order_no")
            tracking = info.get("tracking")

            if order_no:
                entry = pdf_by_order.setdefault(order_no, {})
                if info.get("recipient") and not entry.get("recipient"):
                    entry["recipient"] = info["recipient"]
                if info.get("address") and not entry.get("address"):
                    entry["address"] = info["address"]
                if info.get("store_name") and not entry.get("store_name"):
                    entry["store_name"] = info["store_name"]
                if tracking and not entry.get("tracking"):
                    entry["tracking"] = tracking
                log(
                    f"  {fname} → 訂單 {order_no}"
                    f"  姓名: {info['recipient'] or '—'}"
                    f"  物流單號: {tracking or '—'}"
                )
            elif tracking:
                # 超商運單等無訂單號、只有物流單號的 PDF
                entry = pdf_by_tracking.setdefault(tracking, {})
                if info.get("recipient") and not entry.get("recipient"):
                    entry["recipient"] = info["recipient"]
                if info.get("address") and not entry.get("address"):
                    entry["address"] = info["address"]
                if info.get("store_name") and not entry.get("store_name"):
                    entry["store_name"] = info["store_name"]
                entry["tracking"] = tracking
                log(f"  {fname} → 無訂單號，物流單號: {tracking}  姓名: {info['recipient'] or '—'}")
            else:
                log(f"  {fname} → 未找到訂單號或物流單號，略過")

        except Exception as exc:
            log(f"  [錯誤] {fname}: {exc}")

    return pdf_by_order, pdf_by_tracking


# ── Excel 讀取 ─────────────────────────────────────────────────────────────────

def _cell(row, col_1based):
    if not col_1based or col_1based < 1 or col_1based > len(row):
        return None
    return row[col_1based - 1]


def _normalize_header(value) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _resolve_columns(headers, aliases: dict, source_name: str) -> dict:
    header_index = {}
    for idx, value in enumerate(headers, start=1):
        key = _normalize_header(value)
        if key and key not in header_index:
            header_index[key] = idx

    resolved = {}
    missing = []
    for field, names in aliases.items():
        found = None
        for name in names:
            found = header_index.get(_normalize_header(name))
            if found:
                break
        if found:
            resolved[field] = found
        else:
            missing.append(" / ".join(names))

    if missing:
        raise ValueError(f"{source_name} 欄位格式不符：找不到「{'、'.join(missing)}」欄位")

    return resolved


def _optional_column(headers, name: str) -> int | None:
    """找選填欄位（找不到回 None，不報錯）；以正規化後的完整欄名比對，「發票開立統編」不會誤中「統編」。"""
    target = _normalize_header(name)
    for idx, value in enumerate(headers, start=1):
        if _normalize_header(value) == target:
            return idx
    return None


def _format_col_map(cols: dict, fields: list[str]) -> str:
    return ", ".join(f"{field}={get_column_letter(cols[field])}" for field in fields)


def _as_number(value, default=0):
    if value in (None, ""):
        return default
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).replace(",", "").strip())
    except Exception:
        return default


def _format_order_datetime(value):
    """BigSeller accepts yyyy/mm/dd hh:mm or dd/mm/yyyy hh:mm."""
    if value in (None, ""):
        return value
    if isinstance(value, datetime):
        return value.strftime("%Y/%m/%d %H:%M")

    s = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y/%m/%d %H:%M")
        except ValueError:
            pass

    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::\d{2})?)?$", s)
    if m:
        yyyy, mm, dd, hh, minute = m.groups()
        return f"{int(yyyy):04d}/{int(mm):02d}/{int(dd):02d} {int(hh or 0):02d}:{int(minute or 0):02d}"

    return s


def _validate_big_seller_rows(rows: list[dict]) -> None:
    """在覆蓋模板前檢查 BigSeller 明確標示為必填的資料。

    地址、物流、幣種等欄位在目前模板屬選填，不在這裡硬擋；訂單號、收件人、店鋪 SKU、
    單價與數量若缺漏，則即使成功存成 Excel 也無法可靠匯入 BigSeller，應先停止並指出來源列。
    """
    problems = []
    empty_skus = {mo_sku_suffix(t) for t in COMPANIES.values()} | {
        coupang_sku_suffix(t) for t in COMPANIES.values()
    }
    for index, row in enumerate(rows, start=1):
        missing = []
        if not str(row.get("store") or "").strip():
            missing.append("店铺")
        if not str(row.get("order_no") or "").strip():
            missing.append("订单号")
        if not str(row.get("recipient") or "").strip():
            missing.append("收件人姓名")
        sku = str(row.get("sku") or "").strip()
        if not sku or sku in empty_skus:
            missing.append("店铺SKU")
        if row.get("price") is None or _as_number(row.get("price"), default=-1) < 0:
            missing.append("单价")
        if _as_number(row.get("qty"), default=0) <= 0:
            missing.append("数量")
        if missing:
            source = row.get("source") or "未知來源"
            order_no = row.get("order_no") or "無訂單號"
            problems.append(f"第 {index} 筆（{source} / {order_no}）：{', '.join(missing)}")

    if problems:
        preview = "；".join(problems[:10])
        more = f"；另有 {len(problems) - 10} 筆" if len(problems) > 10 else ""
        raise ValueError(f"BigSeller 必填資料不完整，尚未覆蓋模板：{preview}{more}")


def _decrypt_office(path: str, password: str) -> io.BytesIO | None:
    """若 Office 檔案有加密，解密後移除密碼覆蓋原檔，並回傳解密內容 BytesIO；否則回傳 None。"""
    with open(path, "rb") as f:
        of = msoffcrypto.OfficeFile(f)
        if not of.is_encrypted():
            return None
        if not password:
            raise ValueError("Excel 文件已加密，請在密碼欄輸入密碼")
        of.load_key(password=password)
        buf = io.BytesIO()
        of.decrypt(buf)

    # 移除密碼後覆蓋原檔
    buf.seek(0)
    tmp = path + "._tmp"
    with open(tmp, "wb") as f:
        f.write(buf.read())
    os.replace(tmp, path)

    buf.seek(0)
    return buf


def _add_mo_optional_columns(headers, columns: dict) -> None:
    """mo店+ 選填欄位：賣家統編、訂單進帳金額、(預估)手續費_調整金額（找不到就不放進 columns）。"""
    tax_col = _optional_column(headers, MO_SELLER_TAX_ID_HEADER)
    if tax_col:
        columns["seller_tax_id"] = tax_col
    for name in MO_INCOME_HEADERS:
        income_col = _optional_column(headers, name)
        if income_col:
            columns["income"] = income_col
            break
    fee_col = _optional_column(headers, MO_FEE_ADJ_HEADER)
    if fee_col:
        columns["fee_adj"] = fee_col


def _read_mo_rows(path: str, password: str = "") -> tuple[list, dict]:
    ext = os.path.splitext(path)[1].lower()
    buf = _decrypt_office(path, password)   # None = 無加密

    if ext == ".xls":
        wb = xlrd.open_workbook(file_contents=buf.read()) if buf else xlrd.open_workbook(path)
        ws = wb.sheet_by_index(0)
        headers = ws.row_values(0)
        columns = _resolve_columns(headers, MO_HEADERS, "mo店+ 訂單 Excel")
        _add_mo_optional_columns(headers, columns)
        rows = []
        for r in range(1, ws.nrows):
            vals  = ws.row_values(r)
            types = ws.row_types(r)
            processed = []
            for v, t in zip(vals, types):
                if t == xlrd.XL_CELL_DATE:
                    try:
                        v = xlrd.xldate_as_datetime(v, wb.datemode)
                    except Exception:
                        pass
                processed.append(v)
            rows.append(tuple(processed))
        return rows, columns
    else:
        wb = openpyxl.load_workbook(buf or path, data_only=True, read_only=True)
        ws = wb.active
        headers = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
        columns = _resolve_columns(headers, MO_HEADERS, "mo店+ 訂單 Excel")
        _add_mo_optional_columns(headers, columns)
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        wb.close()
        return rows, columns


def _read_coupang_rows(path: str) -> tuple[list, dict]:
    ext = os.path.splitext(path)[1].lower()
    if ext != ".xlsx":
        raise ValueError("Coupang 訂單文件目前需使用 .xlsx 格式")

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb.active
    headers = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())

    # 2026-08-05 實測踩過的坑：Phase 2 API 主控台「Coupang → 訂單」查詢頁的「匯出 Excel」
    # 產生的檔案，欄名（物流商/運單號/下單時間/賣家SKU/單價…）跟這裡要找的 Coupang Wing 後台
    # 手動下載「DeliveryList」欄名（快遞公司/寄件單號/訂購日期/公司商品代碼/選項價格…）完全不同，
    # 而且「單價」欄還是 "599 TWD" 這種帶幣別的字串（不是純數字），就算硬把欄名對上，優惠金額也會
    # 被 _as_number() 悄悄算成 0——比報錯還危險。與其讓使用者看到語意不明的「找不到欄位」，
    # 先用幾個該匯出檔獨有、DeliveryList 絕不會有的欄名組合偵測出來，直接講清楚原因與正確做法。
    _APP_EXPORT_MARKERS = {"物流商", "運單號", "賣家SKU"}
    _normalized_headers = {_normalize_header(h) for h in headers if h}
    if _APP_EXPORT_MARKERS <= _normalized_headers:
        raise ValueError(
            "這份檔案看起來是「Multi-Platform API 管理主控台」Coupang 分頁「訂單」查詢結果的匯出檔，"
            "不是 Coupang Wing 後台手動下載的「DeliveryList」——兩者欄位名稱與格式不同，無法直接轉換"
            "（查詢結果只用來查看/核對資料）。請到 Coupang Wing 後台重新下載 DeliveryList Excel 再匯入。"
        )

    columns = _resolve_columns(headers, COUPANG_HEADERS, "Coupang 訂單 Excel")
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    wb.close()
    return rows, columns


# ── 主轉換邏輯 ─────────────────────────────────────────────────────────────────

def _coupang_order_discounts(order_map) -> dict:
    """算 Coupang 每一列的「优惠」，回傳 {order_map 的 key: 金額}。

    整張訂單的优惠＝round(商品金額合計 × COUPANG_PLATFORM_FEE) ＋ COUPANG_INVOICE_FEE_PER_ORDER。
    代開發票費是每張訂單一次，所以先以訂單為單位算總額，再依各列小計（單價×數量）比例分攤，
    四捨五入到整數，尾差放在該訂單最後一列，確保各列加總剛好等於整張訂單的优惠。
    """
    by_order: dict = OrderedDict()
    for key, d in order_map.items():
        if d["source"] != "Coupang":
            continue
        by_order.setdefault(d["order_no"], []).append(key)

    result: dict = {}
    for keys in by_order.values():
        order_total = sum(_subtotal(order_map[k]) for k in keys)
        order_discount = round(order_total * COUPANG_PLATFORM_FEE) + COUPANG_INVOICE_FEE_PER_ORDER
        result.update(_allocate_order_discount(order_map, keys, order_discount))
    return result


def _subtotal(d: dict):
    return (d["price"] or 0) * (d["qty"] or 0)


def _allocate_order_discount(order_map, keys: list, order_discount) -> dict:
    """把整張訂單的优惠依各列小計比例分攤（四捨五入到整數），尾差放最後一列。"""
    subtotals = [_subtotal(order_map[k]) for k in keys]
    order_total = sum(subtotals)
    result: dict = {}
    allocated = 0
    for i, (k, sub) in enumerate(zip(keys, subtotals)):
        if i == len(keys) - 1:
            share = order_discount - allocated
        else:
            share = round(order_discount * sub / order_total) if order_total else 0
            allocated += share
        result[k] = share
    return result


def _mo_order_discounts(order_map, log=lambda *_: None) -> dict:
    """算 mo店+ 每一列的「优惠」，回傳 {order_map 的 key: 金額}（2026-11-15 使用者要求寫進程式）。

    整張訂單的优惠＝商品售價×數量合計 −（訂單進帳金額 − |(預估)手續費_調整金額|）。
    進帳與手續費是訂單層級、每個品項列重複的數字，只取一次，再依小計比例分攤、尾差放最後一列。
    匯出檔沒有這兩欄（例如舊的 API 匯出 .xlsx）或該單欄位空白時，該單不放進結果，
    由呼叫端退回舊的 PLATFORM_FEE 估算。
    """
    by_order: dict = OrderedDict()
    for key, d in order_map.items():
        if d["source"] != "mo店+":
            continue
        by_order.setdefault(d["order_no"], []).append(key)

    result: dict = {}
    for order_no, keys in by_order.items():
        first = order_map[keys[0]]
        income, fee_adj = first.get("mo_income"), first.get("mo_fee_adj")
        if income is None or fee_adj is None:
            log(f"  [警告] mo店+ {order_no}：匯出檔沒有「訂單進帳金額」或「(預估)手續費_調整金額」，"
                f"优惠改用舊的 {PLATFORM_FEE:.1%} 估算，請到後台訂單詳情確認後手動修正")
            continue
        order_total = sum(_subtotal(order_map[k]) for k in keys)
        order_discount = round(order_total - (income - abs(fee_adj)))
        if order_discount < 0:
            log(f"  [警告] mo店+ {order_no}：算出的优惠是負數（{order_discount}），請到後台核對入帳金額")
        result.update(_allocate_order_discount(order_map, keys, order_discount))
    return result


def convert_orders(mo_path, template_path, pdf_paths, password, log, progress, coupang_path="",
                   company=DEFAULT_COMPANY):
    if company not in COMPANIES:
        raise ValueError(f"未知的公司：{company}（可選：{'、'.join(COMPANIES)}）")
    tax_id = COMPANIES[company]
    mo_suffix = mo_sku_suffix(tax_id)
    cou_suffix = coupang_sku_suffix(tax_id)
    log(f"公司：{company}（統編 {tax_id}），SKU 後綴 mo店+ {mo_suffix}／Coupang {cou_suffix}")
    progress(3)
    empty_source_notes: list[str] = []

    # 1. 處理 PDF（mo店+ 和 Coupang 共用）
    pdf_data = {}
    pdf_by_tracking_extra: dict = {}
    if pdf_paths:
        log(f"正在處理 {len(pdf_paths)} 個 PDF 文件...")
        pdf_data, pdf_by_tracking_extra = process_pdfs(pdf_paths, password, log)
        log(f"PDF 處理完成：{len(pdf_data)} 個訂單號配對，{len(pdf_by_tracking_extra)} 個僅物流單號配對")
    progress(20)

    # 合併物流單號索引（mo店+ 和 Coupang 共用）
    pdf_tracking_index: dict = {}
    for entry in pdf_data.values():
        if entry.get("tracking"):
            pdf_tracking_index[entry["tracking"]] = entry
    pdf_tracking_index.update(pdf_by_tracking_extra)

    def _lookup_pdf(order_no: str, excel_tracking: str) -> dict:
        """先以訂單號配對，找不到再以物流單號前綴或包含比對（容忍截斷與前置字母差異）。

        找到訂單號配對後，**還會再用物流單號補查一次**並合併缺的欄位進來，不會直接回傳、
        錯過另一份 PDF 才有的資料——實測裝箱明細（用訂單號配對）只有姓名、沒有取件門市，
        超商運單（沒有訂單號、只能用物流單號配對）才有取件門市、但姓名是遮罩過的，兩份
        PDF 各自缺一半資料，只挑一份回傳會漏掉另一份才有的欄位（例如門市名稱）。"""
        result: dict = {}
        if order_no in pdf_data:
            result.update(pdf_data[order_no])

        tracking = (result.get("tracking") or excel_tracking or "").strip()
        if tracking:
            for pdf_track, entry in pdf_tracking_index.items():
                if (pdf_track.startswith(tracking) or tracking.startswith(pdf_track)
                        or (len(tracking) >= 6 and tracking in pdf_track)
                        or (len(pdf_track) >= 6 and pdf_track in tracking)):
                    for field, value in entry.items():
                        if value and not result.get(field):
                            result[field] = value
                    break
        return result

    source_rows: list[dict] = []

    if mo_path:
        log("正在讀取 mo店+ 訂單文件...")
        all_rows, mo_cols = _read_mo_rows(mo_path, password)
        log(f"mo店+ 欄位定位：{_format_col_map(mo_cols, ['order_no', 'status', 'sku', 'price', 'qty'])}")
        if "seller_tax_id" in mo_cols:
            file_tax_ids = {
                str(_cell(r, mo_cols["seller_tax_id"]) or "").strip()
                for r in all_rows
                if _cell(r, mo_cols["order_no"]) not in (None, "")
            } - {""}
            wrong = sorted(file_tax_ids - {tax_id})
            if wrong:
                names = {v: k for k, v in COMPANIES.items()}
                found = "、".join(f"{t}（{names.get(t, '未知公司')}）" for t in wrong)
                raise ValueError(
                    f"mo店+ 訂單 Excel 的「統編」是 {found}，跟選擇的公司「{company}」（{tax_id}）不符。"
                    "請確認公司選擇或訂單檔是否放錯，尚未寫入模板。"
                )
            if file_tax_ids:
                log(f"  mo店+ 訂單檔統編 {tax_id} 與選擇的公司一致")
        else:
            log("  mo店+ 訂單檔沒有「統編」欄，無法自動核對公司，請自行確認公司選擇正確")
        mo_rows = [
            r for r in all_rows
            if _cell(r, mo_cols["order_no"]) not in (None, "")
            and str(_cell(r, mo_cols["status"])).strip() in ("已印單", "已印單待寄件")
        ]

        # 若有上傳 PDF，只保留有對應 PDF 的 mo店+ 訂單（無對應表示已處理，略過）
        if pdf_paths:
            before = len(mo_rows)
            mo_rows = [
                r for r in mo_rows
                if _lookup_pdf(
                    str(_cell(r, mo_cols["order_no"])).strip(),
                    str(_cell(r, mo_cols["tracking"]) or "").strip()
                )
            ]
            skipped = before - len(mo_rows)
            if skipped:
                log(f"略過 {skipped} 筆無對應 PDF 的 mo店+ 訂單（視為已處理）")

        for row in mo_rows:
            order_no = str(_cell(row, mo_cols["order_no"])).strip()
            tracking = _cell(row, mo_cols["tracking"])
            recipient = _cell(row, mo_cols["recipient"])
            address = _cell(row, mo_cols["address"])

            pdf_info = _lookup_pdf(order_no, str(tracking or "").strip())
            if pdf_info.get("recipient"):
                recipient = pdf_info["recipient"]
            if pdf_info.get("address"):
                address = pdf_info["address"]
            elif pdf_info.get("store_name") and address and "○" in str(address):
                # 超商取貨訂單沒有街道地址，mo店+ 匯出的地址欄只會是「郵遞區號 超取 ○○○○○」
                # 這種遮罩門市名稱的格式；用運單 PDF 抽到的「取件門市」把遮罩片段換成真實門市名稱。
                address = re.sub(r"○+", pdf_info["store_name"], str(address))
            if pdf_info.get("tracking"):
                tracking = pdf_info["tracking"]

            source_rows.append({
                "source": "mo店+",
                "store": MO_STORE,
                "warehouse": WAREHOUSE,
                "fee": PLATFORM_FEE,
                "order_no": order_no,
                "date": _cell(row, mo_cols["order_date"]),
                "recipient": recipient,
                "address": address,
                "logistics": _cell(row, mo_cols["logistics"]),
                "tracking": tracking,
                "sku": f"{str(_cell(row, mo_cols['sku']) or '').strip()}{mo_suffix}",
                "price": _as_number(_cell(row, mo_cols["price"])),
                "qty": _as_number(_cell(row, mo_cols["qty"])),
                # 訂單層級的實際入帳，用來算优惠；沒有欄位或空白時為 None
                "mo_income": _as_number(_cell(row, mo_cols["income"]), None) if "income" in mo_cols else None,
                "mo_fee_adj": _as_number(_cell(row, mo_cols["fee_adj"]), None) if "fee_adj" in mo_cols else None,
            })

        log(f"mo店+ 篩選出 {len(mo_rows)} 筆待處理訂單行")

    if coupang_path:
        log("正在讀取 Coupang 訂單文件...")
        coupang_all_rows, coupang_cols = _read_coupang_rows(coupang_path)
        log(f"Coupang 欄位定位：{_format_col_map(coupang_cols, ['order_no', 'logistics', 'tracking', 'sku', 'price', 'qty'])}")
        if not coupang_all_rows:
            empty_source_notes.append("Coupang Excel 只有標題列，沒有訂單資料")
            log("Coupang 訂單 Excel 只有標題列，沒有任何訂單資料；請重新匯出含訂單明細的 DeliveryList")
        coupang_rows = [
            r for r in coupang_all_rows
            if _cell(r, coupang_cols["order_no"]) not in (None, "")
        ]
        if coupang_all_rows and not coupang_rows:
            empty_source_notes.append("Coupang Excel 的訂單編號欄皆為空")
            log("Coupang 訂單 Excel 有資料列，但訂單編號欄皆為空，未產生 Coupang 訂單")

        for row in coupang_rows:
            raw_sku = str(_cell(row, coupang_cols["sku"]) or "").strip()
            order_no = str(_cell(row, coupang_cols["order_no"])).strip()
            tracking = _cell(row, coupang_cols["tracking"])

            # 嘗試從 PDF 補充或修正物流單號
            if pdf_data or pdf_by_tracking_extra:
                pdf_info = _lookup_pdf(order_no, str(tracking or "").strip())
                if pdf_info.get("tracking"):
                    new_tracking = pdf_info["tracking"]
                    if new_tracking != str(tracking or "").strip():
                        log(f"  Coupang {order_no}：運單號由 [{tracking or '空'}] 補全為 [{new_tracking}]")
                    tracking = new_tracking

            source_rows.append({
                "source": "Coupang",
                "store": COUPANG_STORE,
                "warehouse": COUPANG_WAREHOUSE,
                "fee": COUPANG_PLATFORM_FEE,
                "order_no": order_no,
                "date": _cell(row, coupang_cols["order_date"]),
                "recipient": _cell(row, coupang_cols["recipient"]),
                "address": _cell(row, coupang_cols["address"]),
                "logistics": _cell(row, coupang_cols["logistics"]),
                "tracking": tracking,
                "sku": f"{raw_sku}{cou_suffix}",
                "price": _as_number(_cell(row, coupang_cols["price"])),
                "qty": _as_number(_cell(row, coupang_cols["qty"])),
            })

        log(f"Coupang 篩選出 {len(coupang_rows)} 筆待處理訂單行")

    if not source_rows:
        details = "；".join(empty_source_notes)
        if pdf_paths and not (pdf_data or pdf_by_tracking_extra):
            pdf_note = "PDF 未抽到可配對的訂單號或物流單號"
            details = f"{details}；{pdf_note}" if details else pdf_note
        if details:
            raise ValueError(f"沒有可處理的訂單：{details}")
        raise ValueError("沒有可處理的訂單，請至少選擇 mo店+ 或 Coupang 訂單 Excel")

    log(f"總計 {len(source_rows)} 筆待處理訂單行")
    progress(35)

    # 3. 確認 BigSeller 模板可讀取；店鋪名稱依來源平台固定指定
    log("正在讀取 BigSeller 模板...")
    tmpl_buf = _decrypt_office(template_path, password)
    if tmpl_buf:
        log("  [已解密並移除密碼] BigSeller 模板 Excel")
    bs_wb_r = openpyxl.load_workbook(tmpl_buf or template_path, data_only=True)
    bs_wb_r.close()
    if mo_path:
        log(f"mo店+ 店铺名称: {MO_STORE}")
    if coupang_path:
        log(f"Coupang 店铺名称: {COUPANG_STORE}")
    progress(40)

    # 4. 整理訂單，以 (訂單號, SKU) 為 key 合併數量。
    #    同一 key 若單價不同（例如優惠拆算導致同一 SKU 的兩個品項行單價出現 1 元誤差），
    #    以「加總金額 ÷ 加總數量」算出加權平均單價——等同把兩筆分開的金額（單價×數量）
    #    直接加總，再除以合併後的總數量，寫入 BigSeller 的「優惠」欄（單價×數量×平台費率）
    #    才不會因為原始資料被拆成兩筆而算出跟實際營收不一致的金額。
    log("正在整理並合併訂單資料...")
    order_map: dict = OrderedDict()
    amount_totals: dict = {}
    total = len(source_rows)

    for i, d in enumerate(source_rows):
        progress(40 + int(i / total * 28))

        key = (d["source"], d["order_no"], d["sku"])
        amount = (d["price"] or 0) * (d["qty"] or 0)

        if key in order_map:
            order_map[key]["qty"] += d["qty"]
            amount_totals[key] += amount
        else:
            order_map[key] = dict(d)
            amount_totals[key] = amount

    for key, d in order_map.items():
        if d["qty"]:
            d["price"] = round(amount_totals[key] / d["qty"], 2)

    _validate_big_seller_rows(list(order_map.values()))

    merged = len(order_map)
    log(f"合併後共 {merged} 筆（合併了 {total - merged} 個重複明細）")
    progress(70)

    # 5. 寫入 BigSeller 模板（直接覆蓋）
    log("正在寫入 BigSeller 模板...")
    out_wb = openpyxl.load_workbook(template_path)
    out_ws = out_wb.active
    bs_headers = [out_ws.cell(row=1, column=c).value for c in range(1, out_ws.max_column + 1)]
    bs_cols = _resolve_columns(bs_headers, BS_HEADERS, "BigSeller 模板")
    log(f"BigSeller 欄位定位：{_format_col_map(bs_cols, ['store', 'order_no', 'recipient', 'address', 'discount', 'tracking', 'sku', 'price', 'qty'])}")

    # 清除第 5 列起的舊資料
    for row in out_ws.iter_rows(min_row=BS_DATA_ROW):
        for cell in row:
            cell.value = None

    order_discounts = _coupang_order_discounts(order_map)
    order_discounts.update(_mo_order_discounts(order_map, log))

    for idx, (key, d) in enumerate(order_map.items(), start=BS_DATA_ROW):
        progress(70 + int((idx - BS_DATA_ROW) / merged * 25))
        if key in order_discounts:
            discount = order_discounts[key]
        else:
            discount = round((d["price"] or 0) * (d["qty"] or 0) * d["fee"], 2)

        out_ws.cell(row=idx, column=bs_cols["store"]).value     = d["store"]
        out_ws.cell(row=idx, column=bs_cols["order_no"]).value  = d["order_no"]
        out_ws.cell(row=idx, column=bs_cols["date"]).value      = _format_order_datetime(d["date"])
        out_ws.cell(row=idx, column=bs_cols["warehouse"]).value = d["warehouse"]
        out_ws.cell(row=idx, column=bs_cols["recipient"]).value = d["recipient"]
        out_ws.cell(row=idx, column=bs_cols["address"]).value   = d["address"]
        out_ws.cell(row=idx, column=bs_cols["discount"]).value  = discount
        out_ws.cell(row=idx, column=bs_cols["logistics"]).value = d["logistics"]
        out_ws.cell(row=idx, column=bs_cols["tracking"]).value  = d["tracking"]
        out_ws.cell(row=idx, column=bs_cols["sku"]).value       = d["sku"]
        out_ws.cell(row=idx, column=bs_cols["price"]).value     = d["price"]
        out_ws.cell(row=idx, column=bs_cols["qty"]).value       = d["qty"]

    out_wb.save(template_path)
    progress(100)
    log("─" * 60)
    log(f"✓ 完成！共寫入 {merged} 筆訂單")
    log(f"  已覆蓋: {template_path}")


# ── GUI ────────────────────────────────────────────────────────────────────────

class App:
    # 型別註記故意不寫成 `root: tk.Tk`：函式參數註記在 `class App:` 被定義（也就是模組匯入）當下
    # 就會被求值，但這時 tk 還沒被匯入（見檔案開頭說明），會直接 NameError。
    def __init__(self, root):
        self.root          = root
        self.root.title("Multi-Platform Order → BigSeller 訂單轉換工具")
        self.root.geometry("880x740")
        self.root.minsize(720, 600)
        self.mo_file       = tk.StringVar()
        self.coupang_file  = tk.StringVar()
        self.template_file = tk.StringVar()
        self.pdf_files     = []
        self.password      = tk.StringVar()
        self.company       = tk.StringVar(value=DEFAULT_COMPANY)
        self._build_ui()

    def _build_ui(self):
        try:
            ttk.Style().theme_use("vista")
        except Exception:
            pass

        root_frame = ttk.Frame(self.root, padding=16)
        root_frame.pack(fill=tk.BOTH, expand=True)

        # 標題
        ttk.Label(
            root_frame,
            text="多平台訂單  →  BigSeller  訂單格式轉換工具",
            font=("Microsoft JhengHei UI", 15, "bold"),
        ).pack(pady=(0, 12))

        # ── 按鈕（先 pack 固定在最底部）──────────────────────────────────
        btn_frame = ttk.Frame(root_frame)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))
        self.start_btn = ttk.Button(
            btn_frame, text="▶  開始轉換", command=self._start, width=18
        )
        self.start_btn.pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="清除日誌", command=self._clear_log).pack(
            side=tk.LEFT, padx=8
        )

        # ── 進度條 ────────────────────────────────────────────────────────
        prog_frame = ttk.LabelFrame(root_frame, text="  執行進度  ", padding=10)
        prog_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 6))
        self.pbar = ttk.Progressbar(prog_frame, mode="determinate", maximum=100)
        self.pbar.pack(fill=tk.X, pady=(0, 4))
        self.plabel = ttk.Label(prog_frame, text="就緒，等待開始...")
        self.plabel.pack(anchor=tk.W)

        # ── 公司（決定店鋪 SKU 後綴）────────────────────────────────────
        company_frame = ttk.LabelFrame(
            root_frame, text="  訂單所屬公司（決定 SKU 後綴）  ", padding=10
        )
        company_frame.pack(fill=tk.X, pady=(0, 8))
        self.company_combo = ttk.Combobox(
            company_frame, textvariable=self.company, state="readonly", width=14,
            values=list(COMPANIES),
        )
        self.company_combo.pack(side=tk.LEFT)
        self.company_hint = ttk.Label(company_frame, foreground="#555")
        self.company_hint.pack(side=tk.LEFT, padx=10)
        self.company_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_company_hint())
        self._refresh_company_hint()

        # ── 文件選擇 ──────────────────────────────────────────────────────
        file_frame = ttk.LabelFrame(root_frame, text="  文件選擇  ", padding=12)
        file_frame.pack(fill=tk.X, pady=(0, 8))
        file_frame.columnconfigure(1, weight=1)

        # mo店+ Excel
        ttk.Label(file_frame, text="mo店+ 訂單 Excel：").grid(
            row=0, column=0, sticky=tk.W, pady=6, padx=(0, 8)
        )
        ttk.Entry(file_frame, textvariable=self.mo_file).grid(
            row=0, column=1, sticky=tk.EW, padx=(0, 8)
        )
        ttk.Button(file_frame, text="瀏覽…", command=self._browse_mo).grid(row=0, column=2)

        # Coupang Excel
        ttk.Label(file_frame, text="Coupang 訂單 Excel：").grid(
            row=1, column=0, sticky=tk.W, pady=6, padx=(0, 8)
        )
        ttk.Entry(file_frame, textvariable=self.coupang_file).grid(
            row=1, column=1, sticky=tk.EW, padx=(0, 8)
        )
        ttk.Button(file_frame, text="瀏覽…", command=self._browse_coupang).grid(row=1, column=2)

        # BigSeller 模板
        ttk.Label(file_frame, text="BigSeller 模板 Excel：").grid(
            row=2, column=0, sticky=tk.W, pady=6, padx=(0, 8)
        )
        ttk.Entry(file_frame, textvariable=self.template_file).grid(
            row=2, column=1, sticky=tk.EW, padx=(0, 8)
        )
        ttk.Button(file_frame, text="瀏覽…", command=self._browse_tmpl).grid(row=2, column=2)

        # PDF 多選
        ttk.Label(file_frame, text="PDF 文件（可多選）：").grid(
            row=3, column=0, sticky=tk.NW, pady=6, padx=(0, 8)
        )
        pdf_area = ttk.Frame(file_frame)
        pdf_area.grid(row=3, column=1, columnspan=2, sticky=tk.EW, pady=6)
        pdf_area.columnconfigure(0, weight=1)

        self.pdf_label = ttk.Label(pdf_area, text="（尚未選擇）", foreground="gray")
        self.pdf_label.grid(row=0, column=0, sticky=tk.W)

        pdf_btns = ttk.Frame(pdf_area)
        pdf_btns.grid(row=0, column=1, padx=(8, 0))
        ttk.Button(pdf_btns, text="選擇 PDF", command=self._browse_pdf).pack(side=tk.LEFT)
        ttk.Button(pdf_btns, text="清除", command=self._clear_pdf).pack(
            side=tk.LEFT, padx=4
        )

        # ── PDF / Excel 密碼 ───────────────────────────────────────────────
        pw_frame = ttk.LabelFrame(
            root_frame, text="  PDF / Excel 解密密碼（若無加密請留空）  ", padding=10
        )
        pw_frame.pack(fill=tk.X, pady=(0, 8))

        self._pw_entry = ttk.Entry(
            pw_frame, textvariable=self.password, show="●", width=32
        )
        self._pw_entry.pack(side=tk.LEFT)

        self._show_pw = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            pw_frame, text="顯示密碼",
            variable=self._show_pw, command=self._toggle_pw
        ).pack(side=tk.LEFT, padx=10)

        # ── 執行日誌 ──────────────────────────────────────────────────────
        log_frame = ttk.LabelFrame(root_frame, text="  執行日誌  ", padding=12)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        self.logbox = scrolledtext.ScrolledText(
            log_frame, height=8, state=tk.DISABLED,
            font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4"
        )
        self.logbox.pack(fill=tk.BOTH, expand=True)

    # ── 瀏覽 helpers ──────────────────────────────────────────────────────

    def _browse_mo(self):
        p = filedialog.askopenfilename(
            title="選擇 mo店+ 訂單 Excel",
            filetypes=[("Excel", "*.xlsx *.xls"), ("所有文件", "*.*")]
        )
        if p:
            self.mo_file.set(p)

    def _browse_coupang(self):
        p = filedialog.askopenfilename(
            title="選擇 Coupang 訂單 Excel",
            filetypes=[("Excel", "*.xlsx"), ("所有文件", "*.*")]
        )
        if p:
            self.coupang_file.set(p)

    def _browse_tmpl(self):
        p = filedialog.askopenfilename(
            title="選擇 BigSeller 模板 Excel（轉換後將直接覆蓋此檔）",
            filetypes=[("Excel", "*.xlsx *.xls"), ("所有文件", "*.*")]
        )
        if p:
            self.template_file.set(p)

    def _browse_pdf(self):
        paths = filedialog.askopenfilenames(
            title="選擇裝箱明細 / 運單 PDF（可多選）",
            filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")]
        )
        if paths:
            for p in paths:
                if p not in self.pdf_files:
                    self.pdf_files.append(p)
            self._refresh_pdf_label()

    def _clear_pdf(self):
        self.pdf_files.clear()
        self._refresh_pdf_label()

    def _refresh_pdf_label(self):
        if self.pdf_files:
            self.pdf_label.config(
                text=f"已選 {len(self.pdf_files)} 個 PDF 文件", foreground="black"
            )
        else:
            self.pdf_label.config(text="（尚未選擇）", foreground="gray")

    def _refresh_company_hint(self):
        tax_id = COMPANIES[self.company.get()]
        self.company_hint.config(
            text=f"統編 {tax_id}　→　mo店+ {mo_sku_suffix(tax_id)}　Coupang {coupang_sku_suffix(tax_id)}"
        )

    def _toggle_pw(self):
        self._pw_entry.config(show="" if self._show_pw.get() else "●")

    # ── 日誌 ─────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        self.root.after(0, self.__append_log, msg)

    def __append_log(self, msg: str):
        self.logbox.config(state=tk.NORMAL)
        ts = datetime.now().strftime("%H:%M:%S")
        self.logbox.insert(tk.END, f"[{ts}]  {msg}\n")
        self.logbox.see(tk.END)
        self.logbox.config(state=tk.DISABLED)

    def _clear_log(self):
        self.logbox.config(state=tk.NORMAL)
        self.logbox.delete("1.0", tk.END)
        self.logbox.config(state=tk.DISABLED)

    def _set_progress(self, v: float):
        self.root.after(0, self.__set_progress, v)

    def __set_progress(self, v: float):
        self.pbar["value"] = v
        self.plabel.config(text=f"進度：{v:.0f}%")

    def _show_error(self, title: str, message: str):
        self.root.after(0, lambda: messagebox.showerror(title, message))

    # ── 開始轉換 ──────────────────────────────────────────────────────────

    def _start(self):
        mo_path   = self.mo_file.get().strip()
        coupang_path = self.coupang_file.get().strip()
        tmpl_path = self.template_file.get().strip()

        if not mo_path and not coupang_path:
            messagebox.showwarning("提示", "請至少選擇 mo店+ 或 Coupang 訂單 Excel！")
            return
        if not tmpl_path:
            messagebox.showwarning("提示", "請先選擇 BigSeller 模板 Excel！")
            return
        for p in (mo_path, coupang_path, tmpl_path):
            if not p:
                continue
            if not os.path.exists(p):
                messagebox.showerror("錯誤", f"找不到文件：\n{p}")
                return

        pw        = self.password.get()
        pdf_paths = list(self.pdf_files)
        company   = self.company.get()

        self.start_btn.config(state=tk.DISABLED)
        self.pbar["value"] = 0
        self._log("=" * 60)
        self._log("開始轉換...")
        self._log(f"  mo店+   : {os.path.basename(mo_path) if mo_path else '（未選）'}")
        self._log(f"  Coupang : {os.path.basename(coupang_path) if coupang_path else '（未選）'}")
        self._log(f"  公司    : {company}（統編 {COMPANIES[company]}）")
        self._log(f"  模板    : {os.path.basename(tmpl_path)}")
        self._log(f"  PDF 數  : {len(pdf_paths)} 個")
        self._log(f"  密碼    : {'已設定' if pw else '（無）'}")
        self._log("─" * 60)

        def _run():
            try:
                convert_orders(
                    mo_path, tmpl_path, pdf_paths, pw,
                    self._log, self._set_progress, coupang_path,
                    company=company,
                )
            except Exception as exc:
                self._log(f"✗ 轉換失敗：{exc}")
                self._set_progress(0)
                self._show_error("轉換失敗", str(exc))
            finally:
                self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))

        threading.Thread(target=_run, daemon=True).start()


if __name__ == "__main__":
    import tkinter as tk
    from tkinter import filedialog, ttk, scrolledtext, messagebox  # noqa: F401 — App 內部方法會用到

    root = tk.Tk()
    App(root)
    root.mainloop()
