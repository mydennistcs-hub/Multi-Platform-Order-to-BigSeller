import tkinter as tk
from tkinter import filedialog, ttk, scrolledtext, messagebox
import threading
import os
import re
from datetime import datetime
from collections import OrderedDict

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
    "price":      43,  # AQ 商品售價
}

# ── BigSeller 目標欄位 (1-based) ────────────────────────────────────────────────
BS = {
    "store":     1,    # A
    "order_no":  2,    # B
    "date":      3,    # C
    "warehouse": 5,    # E  发货仓库
    "recipient": 6,    # F
    "address":   14,   # N
    "discount":  21,   # U
    "logistics": 22,   # V
    "tracking":  23,   # W
    "sku":       27,   # AA
    "price":     29,   # AC
    "qty":       30,   # AD
}

WAREHOUSE = "樸翔初耘18號8樓 mo店+倉庫"

BS_DATA_ROW  = 5
PLATFORM_FEE = 0.235
SKU_SUFFIX   = "-mo94234570"
# 寄件人地址關鍵字（用於排除寄件人地址）
SENDER_KW = ["MOMO", "格魯維爾", "南園二路"]

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
    result = {"order_no": None, "tracking": None, "recipient": None, "address": None}

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

    # 2. 優先從「收執聯」段落取得完整收件人資訊
    collect_idx = text.find("收執聯")
    if collect_idx != -1:
        section = text[collect_idx:]
        lines = _lines_after(section, "收件人", max_lines=6)
        # lines[0] = 地址, lines[1] = 電話, lines[2] = 姓名+郵遞區號
        for line in lines:
            # 識別地址行（含 路/街/巷/弄/號 且非寄件人）
            if any(c in line for c in ["路", "街", "巷", "弄", "號"]):
                if not any(kw in line for kw in SENDER_KW):
                    if not result["address"]:
                        result["address"] = line
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

    # 4. 若還沒有地址，全文搜尋台灣地址
    if not result["address"]:
        addr_re = re.compile(
            r'((?:台北|新北|桃園|台中|台南|高雄|基隆|新竹|苗栗|彰化|南投'
            r'|雲林|嘉義|屏東|宜蘭|花蓮|台東|澎湖|金門|連江'
            r'|臺北|臺中|臺南|臺東)[市縣][^\n]{3,40}(?:路|街|巷|弄)[^\n]{1,15}號[^\n]{0,10})'
        )
        for m in addr_re.finditer(text):
            addr = m.group(1).strip()
            if not any(kw in addr for kw in SENDER_KW):
                result["address"] = addr
                break

    return result


def process_pdfs(pdf_paths: list, password: str, log) -> tuple[dict, dict]:
    """
    批次處理 PDF。
    回傳 (pdf_by_order, pdf_by_tracking)：
      pdf_by_order   = {訂單號: {recipient, address, tracking}}
      pdf_by_tracking = {物流單號: {recipient, address, tracking}}  ← 無訂單號的 PDF（如超商運單）
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

            info = extract_pdf_data(text)

            order_no = info.get("order_no")
            tracking = info.get("tracking")

            if order_no:
                entry = pdf_by_order.setdefault(order_no, {})
                if info.get("recipient") and not entry.get("recipient"):
                    entry["recipient"] = info["recipient"]
                if info.get("address") and not entry.get("address"):
                    entry["address"] = info["address"]
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
                entry["tracking"] = tracking
                log(f"  {fname} → 無訂單號，物流單號: {tracking}  姓名: {info['recipient'] or '—'}")
            else:
                log(f"  {fname} → 未找到訂單號或物流單號，略過")

        except Exception as exc:
            log(f"  [錯誤] {fname}: {exc}")

    return pdf_by_order, pdf_by_tracking


# ── Excel 讀取 ─────────────────────────────────────────────────────────────────

def _cell(row, col_1based):
    return row[col_1based - 1]


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


def _read_mo_rows(path: str, password: str = "") -> list:
    ext = os.path.splitext(path)[1].lower()
    buf = _decrypt_office(path, password)   # None = 無加密

    if ext == ".xls":
        wb = xlrd.open_workbook(file_contents=buf.read()) if buf else xlrd.open_workbook(path)
        ws = wb.sheet_by_index(0)
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
        return rows
    else:
        wb = openpyxl.load_workbook(buf or path, data_only=True, read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        wb.close()
        return rows


# ── 主轉換邏輯 ─────────────────────────────────────────────────────────────────

def convert_orders(mo_path, template_path, pdf_paths, password, log, progress):
    progress(3)

    # 1. 處理 PDF，取得收件人資訊
    pdf_data = {}
    pdf_by_tracking_extra: dict = {}
    if pdf_paths:
        log(f"正在處理 {len(pdf_paths)} 個 PDF 文件...")
        pdf_data, pdf_by_tracking_extra = process_pdfs(pdf_paths, password, log)
        log(f"PDF 處理完成：{len(pdf_data)} 個訂單號配對，{len(pdf_by_tracking_extra)} 個僅物流單號配對")
    progress(20)

    # 2. 讀取 mo店+ 訂單（只取「已印單」）
    log("正在讀取 mo店+ 訂單文件...")
    all_rows = _read_mo_rows(mo_path, password)
    mo_rows = [
        r for r in all_rows
        if r[MO["order_no"] - 1] not in (None, "")
        and str(r[MO["status"] - 1]).strip() in ("已印單", "已印單待寄件")
    ]
    if not mo_rows:
        raise ValueError("找不到訂單狀態為「已印單」/「已印單待寄件」的訂單，請確認 C 欄資料")

    # 合併兩個來源的物流單號索引（供前綴比對）
    pdf_tracking_index: dict = {}
    for entry in pdf_data.values():
        if entry.get("tracking"):
            pdf_tracking_index[entry["tracking"]] = entry
    pdf_tracking_index.update(pdf_by_tracking_extra)  # 加入僅物流單號的條目

    def _lookup_pdf(order_no: str, mo_tracking: str) -> dict:
        """先以訂單號配對，找不到再以物流單號前綴比對。"""
        if order_no in pdf_data:
            return pdf_data[order_no]
        if mo_tracking:
            for pdf_track, entry in pdf_tracking_index.items():
                if pdf_track.startswith(mo_tracking) or mo_tracking.startswith(pdf_track):
                    return entry
        return {}

    # 若有上傳 PDF，只保留有對應 PDF 的訂單（無對應表示已處理，略過）
    if pdf_paths:
        before = len(mo_rows)
        mo_rows = [
            r for r in mo_rows
            if _lookup_pdf(
                str(r[MO["order_no"] - 1]).strip(),
                str(r[MO["tracking"] - 1] or "").strip()
            )
        ]
        skipped = before - len(mo_rows)
        if skipped:
            log(f"略過 {skipped} 筆無對應 PDF 的訂單（視為已處理）")
        if not mo_rows:
            raise ValueError("所有訂單皆無對應 PDF，沒有需要處理的訂單")

    log(f"篩選出 {len(mo_rows)} 筆待處理訂單行")
    progress(35)

    # 3. 讀取模板店铺名稱
    log("正在讀取 BigSeller 模板...")
    tmpl_buf = _decrypt_office(template_path, password)
    if tmpl_buf:
        log("  [已解密並移除密碼] BigSeller 模板 Excel")
    bs_wb_r = openpyxl.load_workbook(tmpl_buf or template_path, data_only=True)
    store_name = bs_wb_r.active.cell(row=BS_DATA_ROW, column=BS["store"]).value or ""
    bs_wb_r.close()
    log(f"店铺名称: {store_name or '（空白，請在輸出後補填）'}")
    progress(40)

    # 4. 整理訂單，以 (訂單號, SKU, 單價) 為 key 合併數量
    log("正在整理並合併訂單資料...")
    order_map: dict = OrderedDict()
    total = len(mo_rows)

    for i, row in enumerate(mo_rows):
        progress(40 + int(i / total * 28))

        order_no   = str(_cell(row, MO["order_no"])).strip()
        order_date = _cell(row, MO["order_date"])
        raw_sku    = str(_cell(row, MO["sku"]) or "").strip()
        qty        = _cell(row, MO["qty"]) or 0
        recipient  = _cell(row, MO["recipient"])
        address    = _cell(row, MO["address"])
        logistics  = _cell(row, MO["logistics"])
        tracking   = _cell(row, MO["tracking"])
        price      = _cell(row, MO["price"]) or 0

        # 以 PDF 資料補充（優先使用 PDF 的完整姓名 / 地址 / 物流單號）
        pdf_info = _lookup_pdf(order_no, str(tracking or "").strip())
        if pdf_info.get("recipient"):
            recipient = pdf_info["recipient"]
        if pdf_info.get("address"):
            address = pdf_info["address"]
        if pdf_info.get("tracking"):
            tracking = pdf_info["tracking"]   # 使用 PDF 的完整物流單號

        bs_sku = f"{raw_sku}{SKU_SUFFIX}"
        key = (order_no, bs_sku, price)

        if key in order_map:
            order_map[key]["qty"] += qty
        else:
            order_map[key] = {
                "store":     store_name,
                "order_no":  order_no,
                "date":      order_date,
                "recipient": recipient,
                "address":   address,
                "logistics": logistics,
                "tracking":  tracking,
                "sku":       bs_sku,
                "price":     price,
                "qty":       qty,
            }

    merged = len(order_map)
    log(f"合併後共 {merged} 筆（合併了 {total - merged} 個重複明細）")
    progress(70)

    # 5. 寫入 BigSeller 模板（直接覆蓋）
    log("正在寫入 BigSeller 模板...")
    out_wb = openpyxl.load_workbook(template_path)
    out_ws = out_wb.active

    # 清除第 5 列起的舊資料
    for row in out_ws.iter_rows(min_row=BS_DATA_ROW):
        for cell in row:
            cell.value = None

    for idx, (key, d) in enumerate(order_map.items(), start=BS_DATA_ROW):
        progress(70 + int((idx - BS_DATA_ROW) / merged * 25))
        discount = round((d["price"] or 0) * (d["qty"] or 0) * PLATFORM_FEE, 2)

        out_ws.cell(row=idx, column=BS["store"]).value     = d["store"]
        out_ws.cell(row=idx, column=BS["order_no"]).value  = d["order_no"]
        out_ws.cell(row=idx, column=BS["date"]).value      = d["date"]
        out_ws.cell(row=idx, column=BS["warehouse"]).value = WAREHOUSE
        out_ws.cell(row=idx, column=BS["recipient"]).value = d["recipient"]
        out_ws.cell(row=idx, column=BS["address"]).value   = d["address"]
        out_ws.cell(row=idx, column=BS["discount"]).value  = discount
        out_ws.cell(row=idx, column=BS["logistics"]).value = d["logistics"]
        out_ws.cell(row=idx, column=BS["tracking"]).value  = d["tracking"]
        out_ws.cell(row=idx, column=BS["sku"]).value       = d["sku"]
        out_ws.cell(row=idx, column=BS["price"]).value     = d["price"]
        out_ws.cell(row=idx, column=BS["qty"]).value       = d["qty"]

    out_wb.save(template_path)
    progress(100)
    log("─" * 60)
    log(f"✓ 完成！共寫入 {merged} 筆訂單")
    log(f"  已覆蓋: {template_path}")


# ── GUI ────────────────────────────────────────────────────────────────────────

class App:
    def __init__(self, root: tk.Tk):
        self.root          = root
        self.root.title("mo店+ → BigSeller 訂單轉換工具")
        self.root.geometry("840x700")
        self.root.minsize(720, 600)
        self.mo_file       = tk.StringVar()
        self.template_file = tk.StringVar()
        self.pdf_files     = []
        self.password      = tk.StringVar()
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
            text="mo店+  →  BigSeller  訂單格式轉換工具",
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

        # BigSeller 模板
        ttk.Label(file_frame, text="BigSeller 模板 Excel：").grid(
            row=1, column=0, sticky=tk.W, pady=6, padx=(0, 8)
        )
        ttk.Entry(file_frame, textvariable=self.template_file).grid(
            row=1, column=1, sticky=tk.EW, padx=(0, 8)
        )
        ttk.Button(file_frame, text="瀏覽…", command=self._browse_tmpl).grid(row=1, column=2)

        # PDF 多選
        ttk.Label(file_frame, text="PDF 文件（可多選）：").grid(
            row=2, column=0, sticky=tk.NW, pady=6, padx=(0, 8)
        )
        pdf_area = ttk.Frame(file_frame)
        pdf_area.grid(row=2, column=1, columnspan=2, sticky=tk.EW, pady=6)
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

    # ── 開始轉換 ──────────────────────────────────────────────────────────

    def _start(self):
        mo_path   = self.mo_file.get().strip()
        tmpl_path = self.template_file.get().strip()

        if not mo_path:
            messagebox.showwarning("提示", "請先選擇 mo店+ 訂單 Excel！")
            return
        if not tmpl_path:
            messagebox.showwarning("提示", "請先選擇 BigSeller 模板 Excel！")
            return
        for p in (mo_path, tmpl_path):
            if not os.path.exists(p):
                messagebox.showerror("錯誤", f"找不到文件：\n{p}")
                return

        pw        = self.password.get()
        pdf_paths = list(self.pdf_files)

        self.start_btn.config(state=tk.DISABLED)
        self.pbar["value"] = 0
        self._log("=" * 60)
        self._log("開始轉換...")
        self._log(f"  mo店+  : {os.path.basename(mo_path)}")
        self._log(f"  模板   : {os.path.basename(tmpl_path)}")
        self._log(f"  PDF 數 : {len(pdf_paths)} 個")
        self._log(f"  密碼   : {'已設定' if pw else '（無）'}")
        self._log("─" * 60)

        def _run():
            try:
                convert_orders(
                    mo_path, tmpl_path, pdf_paths, pw,
                    self._log, self._set_progress
                )
            except Exception as exc:
                self._log(f"✗ 轉換失敗：{exc}")
            finally:
                self.root.after(0, lambda: self.start_btn.config(state=tk.NORMAL))

        threading.Thread(target=_run, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
