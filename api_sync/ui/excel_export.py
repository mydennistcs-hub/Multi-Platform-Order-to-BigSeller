"""把查詢結果表格（columns/rows）匯出成 Excel，供結果表格的「匯出 Excel」按鈕使用。"""

import sys


def _ensure(pkg, mod=None):
    import importlib
    import subprocess

    try:
        importlib.import_module(mod or pkg)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])


_ensure("openpyxl")
import openpyxl  # noqa: E402


def _fit_columns(ws):
    for col_cells in ws.columns:
        width = max((len(str(c.value)) for c in col_cells if c.value is not None), default=8)
        ws.column_dimensions[col_cells[0].column_letter].width = min(width + 2, 50)


def _raw_columns(rows: list[dict]) -> list[str]:
    """依查詢結果第一次出現的順序保留全部可見欄位；底線開頭是程式內部欄位。"""
    seen = set()
    columns = []
    for row in rows:
        for key in row:
            if key.startswith("_") or key in seen:
                continue
            seen.add(key)
            columns.append(key)
    return columns


def _add_raw_sheet(wb, rows: list[dict]):
    """官方格式維持第一張工作表；第二張保留 API 回應的完整攤平欄位供核對。"""
    ws = wb.create_sheet("API原始欄位")
    columns = _raw_columns(rows)
    ws.append(columns)
    for row in rows:
        ws.append([row.get(col, "") for col in columns])
    _fit_columns(ws)


def export_to_excel(path: str, columns: list[str], rows: list[dict]):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(columns)
    for row in rows:
        ws.append([row.get(col, "") for col in columns])
    _fit_columns(ws)
    wb.save(path)


def export_momo_order_excel(path: str, rows: list[dict], account=None):
    """把 momo 訂單查詢結果匯出成跟 mo店+ 後台「訂單匯出」相同表頭／欄位順序的 Excel，
    方便直接比對、或銜接原本依賴後台匯出格式的既有流程。欄位對照見 handlers.py 的
    MOMO_OFFICIAL_ORDER_COLUMNS / build_momo_official_row（API 沒回傳的欄位一律留空，
    不編造數字）。第一張工作表維持官方格式，第二張「API原始欄位」保留查詢回應的完整攤平欄位。"""
    from api_sync.ui.handlers import MOMO_OFFICIAL_ORDER_COLUMNS, build_momo_official_row

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(MOMO_OFFICIAL_ORDER_COLUMNS)
    for row in rows:
        official_row = build_momo_official_row(row, account=account)
        ws.append([official_row.get(col, "") for col in MOMO_OFFICIAL_ORDER_COLUMNS])
    _fit_columns(ws)
    _add_raw_sheet(wb, rows)
    wb.save(path)


def export_coupang_order_excel(path: str, rows: list[dict]):
    """把 Coupang 訂單查詢結果匯出成跟 Coupang Wing 後台「DeliveryList」相同表頭／欄位順序的
    Excel，方便直接比對、或銜接原本依賴後台下載格式的既有流程（例如「訂單轉換」分頁／
    converter.py——它認的就是 DeliveryList 這份格式，不是本 App 通用查詢匯出的欄名）。
    欄位對照見 handlers.py 的 COUPANG_OFFICIAL_ORDER_COLUMNS / build_coupang_official_row
    （API 沒回傳、或語意不確定的欄位一律留空，不編造數字）。第一張工作表維持官方格式，
    第二張「API原始欄位」保留查詢回應的完整攤平欄位。"""
    from api_sync.ui.handlers import COUPANG_OFFICIAL_ORDER_COLUMNS, build_coupang_official_row

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(COUPANG_OFFICIAL_ORDER_COLUMNS)
    for sequence, row in enumerate(rows, start=1):
        official_row = build_coupang_official_row(row, sequence=sequence)
        ws.append([official_row.get(col, "") for col in COUPANG_OFFICIAL_ORDER_COLUMNS])
    _fit_columns(ws)
    _add_raw_sheet(wb, rows)
    wb.save(path)
