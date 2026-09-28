"""取得寄件單／出貨確認的實際執行邏輯：呼叫 client、解析回應、把標籤存成檔案。

momo 官方文件對 printLabel 欄位的拼法前後不一致（JSON 範例寫 printLabel，
但欄位說明表又寫成 printLable），這裡對兩種拼法都做防呆查找，不只信一種。
"""

import os
from datetime import datetime

from api_sync.coupang_client import CoupangClient
from api_sync.label_utils import extract_seven_eleven_service_code, save_label_content
from api_sync.qt_html_pdf import render_html_to_pdf
from api_sync.momo_client import MomoClient
from api_sync.ui.label_panel import COUPANG_COURIERS

# momo 後台下載的寄件單檔名固定是「Logistics{類型}_{店鋪代碼}_{時間戳記}.副檔名」
# （店鋪代碼即商品編號開頭 TP+7碼，例：LogisticsLabel_TP0001949_20260721201111.pdf，
# 實測新竹物流／第三方物流一張訂單有 3 個檔案 Data/Detail/Label，7-11／全家只有 Detail/Label 2 個），
# 這裡對照我們原本的中文檔名後綴，讓有店鋪代碼可用時存檔名稱跟後台下載的一致。
_MOMO_LABEL_KIND_EN = {"標籤": "Label", "明細": "Detail", "出貨總表": "Data"}

# Coupang 寄件單檔名比照使用者原本手動整理的習慣（{日期}_coupang_{物流}），
# 拿 COUPANG_COURIERS 的中文標籤去掉「（宅配）／（超商）」後綴，跟 UI 下拉選單顯示的名稱一致。
_COUPANG_COURIER_FILE_NAMES = {code: label.split("（")[0] for code, label, _kind in COUPANG_COURIERS}


def _coupang_invoice_base_path(folder: str, account, delivery_company_code: str) -> str:
    """{日期}_{時間}_{統編}_coupang_{物流}：2026-08-05 起格魯維爾／丹尼書兩家公司共用同一個
    下載資料夾，原本檔名沒有統編分不出是哪家公司；原本手動命名用「_1」「_2」數字區分同一天
    多筆下載，改成精確到秒的時間戳記後天然不會撞名，不需要再手動編號。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    courier_name = _COUPANG_COURIER_FILE_NAMES.get(delivery_company_code, delivery_company_code)
    return os.path.join(folder, f"{ts}_{account.tax_id}_coupang_{courier_name}")


def _momo_label_base_path(folder: str, label_id: str, kind_cn: str, store_code: str | None) -> str:
    if store_code:
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        return os.path.join(folder, f"Logistics{_MOMO_LABEL_KIND_EN[kind_cn]}_{store_code}_{ts}")
    # 沒有店鋪代碼（例如手動輸入訂單編號、不是從查詢結果點選進來）時，退回舊版命名，不影響功能。
    return os.path.join(folder, f"{label_id}_{kind_cn}")


def _first(item: dict, *keys):
    for k in keys:
        v = item.get(k)
        if v:
            return v
    return None


def _is_falsy_momo_flag(value) -> bool:
    """momo 的 success 欄位有時是 boolean false，有時（例如重印標籤失敗時實測看到）是字串 "false"。"""
    if isinstance(value, str):
        return value.strip().lower() == "false"
    return not value


def momo_run_label_action(account, client_method: str, folder: str, tax_id_for_decrypt: str = None,
                          store_code: str = None, **kwargs):
    client = MomoClient.from_account(account)
    resp = getattr(client, client_method)(**kwargs)
    data = resp.json()
    if _is_falsy_momo_flag(data.get("success", True)) and data.get("errorMessage"):
        raise RuntimeError(data["errorMessage"])

    results = data.get("confirmDeliveryDetailResList") or data.get("orderPrintLabelResList") or []
    if not results:
        raise RuntimeError(f"回應內沒有可解析的結果：{data}")

    saved_files = []
    messages = []
    for item in results:
        order_list = item.get("orderList", [])
        label_id = "_".join(f"{o.get('orderNo')}_{o.get('orderSeq')}" for o in order_list) or "label"
        if not item.get("success", True):
            messages.append(f"{label_id}：失敗 - {item.get('message', '')}")
            continue

        label_content = _first(item, "printLabel", "printLable")
        detail_content = _first(item, "printDetail")
        all_content = _first(item, "printAll")

        # tax_id_for_decrypt 是 None 時（使用者沒勾「自動解密」checkbox）就不嘗試解密，直接原樣存檔；
        # 有值時三種檔案都嘗試 best-effort 解密（不是只有 printDetail——UI 那邊的 checkbox 語意是
        # 「匯出/下載時，若偵測到密碼就自動解密」，沒有理由只套用在明細檔）。save_label_content 的
        # 解密邏輯本來就是 best-effort，格式不符或內容根本沒加密時會原樣寫檔，不會中斷流程。
        if label_content:
            saved_files.append(
                save_label_content(
                    label_content, _momo_label_base_path(folder, label_id, "標籤", store_code),
                    password=tax_id_for_decrypt,
                )
            )
        if detail_content:
            saved_files.append(
                save_label_content(
                    detail_content, _momo_label_base_path(folder, label_id, "明細", store_code),
                    password=tax_id_for_decrypt,
                )
            )
        if all_content:
            saved_files.append(
                save_label_content(
                    all_content, _momo_label_base_path(folder, label_id, "出貨總表", store_code),
                    password=tax_id_for_decrypt,
                )
            )

        messages.append(f"{label_id}：成功 - {item.get('message', '')}")

    return saved_files, messages


def _parse_coupang_json(resp, action: str):
    """先看 HTTP 狀態碼，非 200 一律連原始內容一起丟出來當例外，不要讓它流進 _first_list
    被當成「查詢成功但 0 筆」。這是 2026-08-05 實測「查不到任何發貨地」的根因之一：
    marketplace_openapi 家族（例如發貨地清單查詢）的錯誤回應格式不保證跟 openapi 家族
    （訂單那組）的 {code, message} 一致，_raise_if_coupang_error 認不出來就會被 _first_list
    吞成空清單，把「請求本身被拒絕」誤導成「這個帳戶沒建發貨地」。連 JSON 都解析不出來
    （例如回傳 HTML 錯誤頁）也在這裡一併攔下來，附上原始內容方便排查。
    """
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"{action}失敗，HTTP {resp.status_code}：{resp.text[:300]}")
    if resp.status_code != 200:
        detail = data.get("message") if isinstance(data, dict) else None
        raise RuntimeError(detail or f"{action}失敗，HTTP {resp.status_code}：{str(data)[:300]}")
    return data


def _raise_if_coupang_error(data, action: str):
    """HTTP 200 但 body 帶 {code, message} 的錯誤（例如 IP 不在白名單），
    不會用 HTTP 狀態碼表示錯誤，要另外檢查 body。沒有這道檢查的話，下面的 _first_list
    會找不到清單而回空陣列，UI 就會顯示「查不到任何發貨地，請先去 Wing 建立」——把「IP 沒過」
    誤導成「資料沒建」，使用者會白跑一趟後台。非 200 狀態碼的錯誤由 _parse_coupang_json 先攔。
    """
    if not isinstance(data, dict):
        return
    code = str(data.get("code", ""))
    if code and code not in ("200", "SUCCESS", "OK"):
        raise RuntimeError(data.get("message") or f"{action}失敗（code={code}）")
    message = data.get("message")
    if message and not data.get("data") and not data.get("content"):
        raise RuntimeError(message)


def _first_list(data, keys):
    """從回應裡撈出清單。Coupang 各支 API 把資料放在哪個 key 不一致（有的 data、有的 content），
    而且這兩支的回應格式沒有官方逐欄位全文可對照（doc_ref 是工程摘要），所以逐一嘗試常見位置，
    找不到就回空清單，不要讓 UI 直接炸掉。"""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for inner in ("content", "data", "items"):
                if isinstance(value.get(inner), list):
                    return value[inner]
    return []


def coupang_fetch_return_centers(account):
    """回傳 [(code, 顯示文字), ...]，給「選擇退貨地」對話框用。"""
    client = CoupangClient.from_account(account)
    data = _parse_coupang_json(client.query_return_shipping_centers(), "查詢退貨地")
    _raise_if_coupang_error(data, "查詢退貨地")
    rows = []
    for c in _first_list(data, ("data", "content", "result")):
        code = c.get("returnCenterCode") or c.get("returnCenterId")
        if not code:
            continue
        name = c.get("shippingPlaceName") or c.get("returnCenterName") or c.get("placeName") or ""
        addr = c.get("placeAddresses") or c.get("returnAddress") or ""
        if isinstance(addr, list):  # placeAddresses 實際是陣列，取第一筆的地址字串
            first = addr[0] if addr else {}
            addr = f"{first.get('returnAddress', '')} {first.get('returnAddressDetail', '')}".strip()
        rows.append((str(code), f"{name}｜{addr}｜{code}".strip("｜ ")))
    return rows


def coupang_fetch_outbound_places(account):
    """回傳 [(code, 顯示文字), ...]，給「選擇發貨地」對話框用（宅配才需要）。"""
    client = CoupangClient.from_account(account)
    data = _parse_coupang_json(client.query_outbound_shipping_places(), "查詢發貨地")
    _raise_if_coupang_error(data, "查詢發貨地")
    rows = []
    for c in _first_list(data, ("data", "content", "result")):
        code = c.get("outboundShippingPlaceCode") or c.get("outboundShippingPlaceId")
        if not code:
            continue
        name = c.get("shippingPlaceName") or c.get("placeName") or ""
        addr = c.get("placeAddresses") or ""
        if isinstance(addr, list):
            first = addr[0] if addr else {}
            addr = f"{first.get('returnAddress', '')} {first.get('returnAddressDetail', '')}".strip()
        rows.append((str(code), f"{name}｜{addr}｜{code}".strip("｜ ")))
    return rows


def coupang_run_acknowledge(account, shipment_box_id):
    client = CoupangClient.from_account(account)
    resp = client.acknowledge_orders([shipment_box_id])
    data = resp.json()
    if resp.status_code != 200:
        message = data.get("message") if isinstance(data, dict) else None
        raise RuntimeError(message or f"確認訂單失敗，HTTP {resp.status_code}")

    # code 這支實測是字串 "200"（不是 ordersheets 那種數字 200），統一轉字串比對比較保險
    if str(data.get("code")) not in ("200", "OK"):
        raise RuntimeError(data.get("message") or "確認訂單失敗")

    response_list = (data.get("data") or {}).get("responseList") or []
    item = next((r for r in response_list if str(r.get("shipmentBoxId")) == str(shipment_box_id)), None)
    if item is None and response_list:
        item = response_list[0]
    if item is None:
        raise RuntimeError(f"無法解析回應內容：{data}")
    if not item.get("succeed"):
        raise RuntimeError(item.get("resultMessage") or "確認訂單失敗")
    return item.get("resultMessage") or "確認訂單成功"


def coupang_run_arrange_shipment(
    account, shipment_box_id, delivery_company_code, return_center_code=None,
    outbound_shipping_place_code=None, remark="",
):
    client = CoupangClient.from_account(account)
    resp = client.arrange_shipment(
        shipment_box_id, delivery_company_code, return_center_code, outbound_shipping_place_code, remark
    )
    data = resp.json()
    if resp.status_code != 200:
        # IP 白名單/認證錯誤等，回的是標準 {code, message} 錯誤格式，不是 shipmentBoxId 包裝格式
        message = data.get("message") if isinstance(data, dict) else None
        raise RuntimeError(message or f"安排出貨失敗，HTTP {resp.status_code}")

    # 實測（2026-08-05）：成功時整包回應是 {code, message, data: {shipmentBoxId: {...}}}，
    # shipmentBoxId 當 key 包起來的物件是在 data 這層底下，不是最外層——CLAUDE.md 原本記錄的
    # 「成功格式就是最外層 {shipmentBoxId:{...}}」是根據文件推測，跟真實回應對不上，這裡改成
    # 優先看 data["data"]，找不到才退回最外層（防呆，避免哪天真的遇到沒包 data 的格式）。
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    result = payload.get(str(shipment_box_id))
    if result is None:
        raise RuntimeError(f"無法解析回應內容：{data}")
    if not result.get("success"):
        raise RuntimeError(result.get("errorMessage") or result.get("errorKey") or "安排出貨失敗")
    return result


def coupang_run_download_invoice(account, shipment_box_id, delivery_company_code, invoice_number, folder):
    """回傳 (path, note, full_invoice_number)。

    - note 非空代表有需要使用者注意的狀況（例如轉檔失敗改存 HTML）。
    - full_invoice_number 非空代表「從寄件單內容補齊到的完整運單號」，目前只有 7-11 會有：
      Coupang API 回的 `invoiceNumber` 只有前 8 碼，7-11／Wing 後台實際認的是完整 12 碼的
      交貨便服務代碼，少的 4 碼只能從寄件單 HTML 撈（見 extract_seven_eleven_service_code）。

    嘉里／新竹物流回的是 PDF 本體，直接存檔；全家／7-11 回的是 HTML，用 QtWebEngine
    （Chromium，跟使用者原本在後台用瀏覽器列印是同一個引擎）轉成 PDF——舊版用的 xhtml2pdf
    對這兩種版面各壞一種，細節見 api_sync/qt_html_pdf.py 的模組說明。
    """
    client = CoupangClient.from_account(account)
    resp = client.download_invoices(delivery_company_code, shipment_box_id, invoice_number)

    if resp.status_code != 200:
        try:
            data = resp.json()
            raise RuntimeError(data.get("message", f"下載失敗，HTTP {resp.status_code}"))
        except ValueError:
            raise RuntimeError(f"下載失敗，HTTP {resp.status_code}：{resp.text[:300]}")

    content_type = resp.headers.get("Content-Type", "")
    base_path = _coupang_invoice_base_path(folder, account, delivery_company_code)
    if "pdf" in content_type:
        path = base_path + ".pdf"
        with open(path, "wb") as f:
            f.write(resp.content)
        return path, "", ""
    if "html" in content_type:
        html = resp.text
        full_invoice_number = _full_invoice_number_from_html(html, delivery_company_code, invoice_number)
        pdf_path = base_path + ".pdf"
        try:
            render_html_to_pdf(html, pdf_path)
            return pdf_path, "", full_invoice_number
        except Exception as e:  # noqa: BLE001 — 轉檔失敗不能卡住整個下載流程，至少要讓使用者拿到 HTML
            # 轉檔失敗時可能已經留下一個 0 byte 的空殼 PDF，清掉免得使用者誤點開空檔。
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) == 0:
                os.remove(pdf_path)
            html_path = base_path + ".html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            return html_path, (
                f"PDF 轉檔失敗（{e}），已改存 HTML 檔，請用瀏覽器開啟後直接列印或另存為 PDF。"
            ), full_invoice_number
    # 未知格式：原樣存檔，讓使用者自行檢查，不要假裝知道格式
    path = base_path + ".bin"
    with open(path, "wb") as f:
        f.write(resp.content)
    return path, "", ""


def _full_invoice_number_from_html(html: str, delivery_company_code: str, invoice_number: str) -> str:
    """只針對 7-11：從寄件單 HTML 補齊完整運單號；抓不到或看起來對不上就回空字串（不亂補）。

    驗證條件是「完整碼要以 API 給的運單號開頭、而且比它長」——實測 API 回 `E8966792`、
    寄件單上是 `E89667925349`，剛好是前 8 碼加後 4 碼。對不上時代表 7-11 改了格式或這張單
    根本不是同一筆，寧可不補也不要把錯的號碼寫進匯出的 Excel。
    """
    if delivery_company_code != "TWL_711":
        return ""
    code = extract_seven_eleven_service_code(html)
    if not code:
        return ""
    api_no = str(invoice_number or "").strip()
    if api_no and not (code.startswith(api_no) and len(code) > len(api_no)):
        return ""
    return code
