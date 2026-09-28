"""把「執行」按鈕點擊事件對應到實際的 API 呼叫 + 結果整理成表格。

統一 handler 簽名（多的關鍵字參數各 handler 用不到就忽略）：
    (account, date_from=None, date_to=None, status=None,
     order_no=None, keyword=None, sku=None, limit=None) -> (columns, rows)

rows 裡的 key 要跟 columns 一一對應，main_window 會直接拿去填 QTableWidget。

**`limit` 的語意（2026-08-01 改，原本叫 page_size）**：
這次查詢最多回傳幾「列」，None 代表不限（抓到 API 沒有下一頁、或撞到 _MAX_PAGES 上限為止）。

舊版這個參數叫 `page_size`，UI 標示「每頁筆數」，但它只被拿去當「每次 API 呼叫的批次大小」
（momo maxPerPage／Coupang maxPerPage／Shopify GraphQL first），而下面每個 handler 都會用
nextToken/cursor 自動翻頁把資料全部抓完，所以不管使用者填 10 還是 250，最後表格筆數完全一樣
——使用者實測 Shopify 填 50 仍回 492 筆，等於這個欄位形同虛設。三個平台都有同樣問題。

現在拆成兩件事：
- 對外（UI）：`limit` = 真正的結果上限，達到就停止翻頁。
- 對內（API）：批次大小改由 `_batch_size()` 自己算，使用者不需要也不應該管這個技術細節。

達到上限時**不會把同一張訂單／同一個商品的明細切成兩半**——迴圈是在「處理完整筆」之後才檢查，
所以實際回傳可能略多於 limit。QueryPanel.show_table 用 `len(rows) >= limit` 判斷要不要提示
「可能還有更多」，這個「略多」的行為是刻意的，改動時請一併確認那邊的提示邏輯。
"""

import re
from datetime import datetime, timedelta

from api_sync.coupang_client import CoupangClient
from api_sync.momo_client import MomoClient
from api_sync.shopify_client import ShopifyClient
from api_sync.ui import status_labels

# 單一狀態查詢一次最多翻幾頁，避免帳戶資料量異常大時無限迴圈把畫面卡死。
_MAX_PAGES_PER_STATUS = 20


def _batch_size(limit: int | None, api_max: int, default: int = 100) -> int:
    """算出每次 API 呼叫要抓幾筆。

    使用者只設「總共最多幾筆」，每次呼叫抓多少是實作細節：能一次抓完就不要分兩次（少一次
    round-trip），但不能超過該 API 允許的單頁上限（Shopify GraphQL first 上限 250、
    Coupang maxPerPage 建議 50、momo maxPerPage 最小 100）。
    """
    if not limit:
        return default
    return max(1, min(limit, api_max))


def _reached(rows: list, limit: int | None) -> bool:
    """已經抓夠了嗎？limit 為 None（不限）時永遠是 False。"""
    return bool(limit) and len(rows) >= limit


def _money(m: dict) -> str:
    if not m:
        return ""
    units = m.get("units", 0)
    currency = m.get("currencyCode", "")
    return f"{units} {currency}".strip()


def _money_units(value):
    """取 Coupang 金額物件的 units；缺值時保留空白，不把未知金額偽裝成 0。"""
    if isinstance(value, dict):
        return value.get("units")
    return None


def _number_or_zero(value) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _flatten(d: dict, prefix: str = "") -> dict:
    """把巢狀 dict 攤平成單層（用 . 串接 key）。金額物件（含 units+currencyCode，例如 Coupang 的
    salesPrice/discountPrice/orderPrice）視為一個值用 _money() 轉字串，不繼續往下攤平成三欄；
    list 直接轉逗號分隔字串。不處理巢狀 list（訂單品項陣列由外層 for 迴圈負責展開成一列一列）。"""
    flat = {}
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            if "units" in v and "currencyCode" in v:
                flat[key] = _money(v)
            else:
                flat.update(_flatten(v, prefix=f"{key}."))
        elif isinstance(v, list):
            flat[key] = ", ".join(str(x) for x in v) if v else ""
        else:
            flat[key] = v
    return flat


def _columns_with_extras(rows: list[dict], primary: list[str]) -> list[str]:
    """欄位清單＝常用欄位（固定順序）＋其餘攤平出來的欄位（依所有列聯集、第一次出現的順序），
    確保不同列有的欄位不一樣時也不會漏掉任何一欄。

    底線開頭的 key 是給程式內部用的隱藏欄位（例如 `_raw_status` 保留未翻譯的原始狀態碼給
    出貨面板比對用），**不會**變成表格欄位。新增這類欄位時記得一律用底線開頭。
    """
    seen = set(primary)
    extra = []
    for row in rows:
        for key in row.keys():
            if key.startswith("_"):
                continue
            if key not in seen:
                seen.add(key)
                extra.append(key)
    return primary + extra


MOMO_ORDER_STATUSES = [
    "All", "Unpaid", "NotShipped", "NotRecycled", "Printed", "Shipping",
    "DoneDelivery", "AbnormalDelivery", "OrderCancelled", "ReturnCancelled", "RecycleConfirmed",
]
MOMO_GOODS_STATUSES = ["All", "StartSelling", "StopSelling"]

COUPANG_ORDER_STATUSES = ["ACCEPT", "INSTRUCT", "DEPARTURE", "DELIVERING", "FINAL_DELIVERY"]
COUPANG_PRODUCT_STATUSES = ["APPROVED", "IN_REVIEW"]

# QueryPanel 用這個 key 判斷結果表格裡哪一欄是 shipmentBoxId，右鍵選單「前往安排出貨」要用。
SHIPMENT_BOX_ID_COLUMN = "合併配送號碼"

# momo 訂單查詢結果表格右鍵選單「前往出貨確認並自動帶入」要用這幾欄組出 order_list。
MOMO_ORDER_NO_COLUMN = "訂單編號"
MOMO_ORDER_SEQ_COLUMN = "品項流水號"
MOMO_DELIVERY_COMPANY_COLUMN = "物流商"
MOMO_ITEM_STATUS_COLUMN = "品項狀態"
# Coupang 訂單列的隱藏欄位：未翻譯的原始狀態碼。底線開頭代表不會出現在表格欄位裡。
COUPANG_RAW_STATUS_KEY = "_raw_status"
# momo 訂單查詢結果的「訂單狀態」欄——OrderQuery 回應本身沒有這個欄位（只有品項層級的
# itemStatus／MOMO_ITEM_STATUS_COLUMN），是從查詢時指定的狀態篩選條件反推回來的，
# 見 momo_order_query() 內的說明。
MOMO_ORDER_STATUS_COLUMN = "訂單狀態"
# 出貨確認（第三方物流/7-11/全家）成功＝momo 後台「印單」動作，成功後這張訂單的訂單狀態
# 會從「未出貨(未印單)」變成這個值。QueryPanel.mark_momo_order_status() 用來把查詢結果表格
# 裡對應那幾列本地樂觀更新，讓使用者不用重新查詢就能直接匯出正確狀態的 Excel（見
# main_window._on_momo_label_run_requested）。
MOMO_ORDER_STATUS_PRINTED = status_labels.MOMO_ORDER_STATUS["Printed"]

# momo 的 listItem 裡，運費是用一個「假的」品項表示（goodsName 固定叫「運費」，商品原廠編號／
# 規格都是空的，goodsNo 是 00000000 結尾的假序號），不是真正的商品。官方後台匯出根本不會把它
# 當成一列商品，是把金額折進同一張訂單真正商品那一列的「客人支付運費」欄；momo_order_query()
# 要把它從品項列表裡濾掉，改成附加欄位，不然會在匯出的 Excel／converter.py 的 BigSeller
# 匯入檔裡多出一列沒有 SKU 的空白商品（2026-08-02 使用者實測踩到）。
MOMO_SHIPPING_FEE_GOODS_NAME = "運費"
MOMO_SHIPPING_FEE_COLUMN = "客人支付運費"

# momo OrderQuery 官方欄位說明表全部欄位（doc_ref/mo店+ API 串接的資料/20241007001.pdf 第54-55頁），
# 沒對照到的 key（未來 momo 文件新增欄位時）直接用原始 key 當欄名，不會漏掉任何屬性。
MOMO_ORDER_FIELD_LABELS = {
    "orderNo": MOMO_ORDER_NO_COLUMN,
    "errorMessage": "錯誤訊息",
    "orderSeq": MOMO_ORDER_SEQ_COLUMN,
    "itemStatus": MOMO_ITEM_STATUS_COLUMN,
    "goodsNo": "商品編號",
    "goodsdtCode": "商品子貨號",
    "goodsName": "商品名稱",
    "goodsInfo1": "商品規格一",
    "goodsInfo2": "商品規格二",
    # 官方 PDF 第 54 頁（請求）與第 55 頁（回應）都寫「商品原廠編號」，不是「廠商商品編號」
    # ——舊版這裡翻錯了，2026-08-01 對照原文修正，跟商品查詢那邊的欄名／輸入框標籤統一。
    "entpGoodsNo": "商品原廠編號",
    "goodsType": "商品屬性",
    "quantity": "數量",
    "planShipDate": "預計出貨日",
    "shipDate": "出貨日期",
    "entpReturnDate": "廠商退貨日期",
    "recycleDate": "回收日期",
    "deliveryType": "配送方式",
    "customerDeliveryType": "顧客選擇配送方式",
    "deliveryCompany": MOMO_DELIVERY_COMPANY_COLUMN,
    "deliveryNo": "運單號",
    "taxable": "應稅/免稅",
    "orderAmount": "金額",
    "invoiceAmount": "開立發票金額",
    "invoiceNo": "發票號碼",
    "invoiceDate": "發票日期",
    "customerNo": "客人個人識別碼",
    "customerName": "訂購人姓名",
    "receiverName": "收件人",
    "customerDeliveryMessage": "客人配送需求",
    "storeReturnMessage": "商店退貨訊息",
    "returnReason": "退貨原因",
    "shipStatus": "商品狀態",
    "ivr": "客服IVR代碼",
    "receiverAddress": "收件地址",
    "lastProcDate": "處理時間",
    "storeReturnDeliveryType": "商店退貨配送方式",
    "outplaceSeq": "出貨回廠地址代碼",
    "outplaceAddr": "出貨回廠地址",
    "deliveryTemp": "配送層別",
    "changedAddress": "客人申請的新地址",
    "corpSIdno": "發票開立統編",
    "corpName": "發票開立公司名稱",
}

# 常用欄位固定放最前面（跟舊版欄位一致，右鍵/自動帶入邏輯依賴這幾個確切欄名），其餘攤平出來的
# momo 官方欄位接在後面（見 momo_order_query）。
MOMO_ORDER_PRIMARY_COLUMNS = [
    MOMO_ORDER_NO_COLUMN, MOMO_ORDER_SEQ_COLUMN, MOMO_ORDER_STATUS_COLUMN, MOMO_ITEM_STATUS_COLUMN,
    "商品名稱", "數量", "金額", MOMO_SHIPPING_FEE_COLUMN, "收件人", "收件地址", "處理時間",
    MOMO_DELIVERY_COMPANY_COLUMN, "運單號",
]

# momo 後台「訂單匯出」Excel 的官方表頭與順序（逐字核對
# doc_ref/OrderExport_TP0001949_20260802143315.xls 表頭列，2026-08-02），供 API 查詢結果匯出時
# 採用同一份格式，讓匯出檔案跟後台手動下載的長得一樣。
MOMO_OFFICIAL_ORDER_COLUMNS = [
    "訂單編號", "訂單編號(序號)", "訂單狀態", "銷退原因", "退貨數量", "訂單金額依品項", "訂單金額加總",
    "訂單類別", "轉單日", "最晚出貨日期", "訂單鑑賞期", "訂單結算日", "出貨/回收日期", "廠退日期",
    "超取廠退訊息", "商品貨態", "商品貨態時間", "商品屬性", "分期數", "商品編號", "商品名稱", "規格1",
    "規格2", "商品原廠編號", "數量", "優惠代碼", "收件人姓名", "收件人電話", "收件人地址", "客戶編號",
    "物流商", "物流單號", "配送方式", "自訂物流退貨地址", "三方出貨回收地址", "備註(店家自行備註)",
    "客取貨門市代碼", "客取貨門市名稱", "退貨門市代碼", "退貨門市名稱", "商品售價", "全站商店抵用券",
    "mo點/mo幣", "單品折價券(商品自折)", "行銷活動促銷(商品自折)", "單店抵用券(商品自折)", "客人支付運費",
    "平台補貼運費", "商品滿額免運費", "預估平台代扣運費(鑑賞期後:平台代扣運費)", "成交手續費",
    "預購商品服務費", "物流隱碼服務費", "金流與系統處理費", "發票處理費", "活動服務費",
    "(預估)手續費_調整時間", "(預估)手續費_調整原因", "(預估)手續費_調整金額", "退貨退款_調整時間",
    "退貨退款_調整原因", "退貨退款_調整金額", "取消訂單_調整時間", "取消訂單_調整原因",
    "取消訂單_調整金額", "累計調整金額", "訂單預估收入", "訂單進帳金額", "代收金額", "應稅(免稅)",
    "支付方式", "開立發票金額_依品項(若您是自行開立發票，請依此金額開立予消費者)",
    "開立發票金額加總(若您是自行開立發票，請依此金額開立予消費者)", "發票開立統編", "統編", "公司名稱",
    "開立發票方", "發票號碼", "發票日期",
]

# 官方欄名 -> momo_order_query() 產生的 row dict 裡對應的 key（即 MOMO_ORDER_FIELD_LABELS 的值）。
# 只放「確定對應」的欄位。官方後台匯出比 OrderQuery API 回應多出很多結算/財務明細欄位（各式優惠券、
# 手續費、調整金額、鑑賞期/結算日等）——這些 OrderQuery 完全沒有回傳，對不上的欄位維持空白，
# 不要拿其他欄位的數字去湊，跟本模組其餘「文件裡沒有就沒有，不要編」的原則一致。
# 「統編」「公司名稱」兩欄由 build_momo_official_row() 另外從帳戶設定（不是 API 回應）填入。
MOMO_OFFICIAL_ORDER_FIELD_MAP = {
    "訂單編號": MOMO_ORDER_NO_COLUMN,
    "訂單編號(序號)": MOMO_ORDER_SEQ_COLUMN,
    # 只有在查詢時指定了非「全部」的狀態篩選才會有值（見 momo_order_query 的 order_status_cn），
    # 這也是 converter.py（Phase 1）判斷「待處理訂單」的依據欄位，留空的話 converter.py 會篩出
    # 0 筆（2026-08-02 使用者實測踩到，因此補上這欄）。
    "訂單狀態": MOMO_ORDER_STATUS_COLUMN,
    # OrderQuery 的 orderAmount 是品項金額；訂單總額則在 momo_order_query() 以同一張訂單
    # 所有品項（包含運費假品項）的 orderAmount 加總後，存進隱藏欄位供官方格式匯出。
    "訂單金額依品項": "金額",
    "訂單金額加總": "_order_total_amount",
    "銷退原因": "退貨原因",
    # 官方 OrderQuery 沒有獨立的「轉單日／訂單建立時間」欄位，這裡借用「處理時間」(lastProcDate)
    # 當最佳近似值——實測與後台匯出的「轉單日」只差幾秒（同一張新訂單，處理時間幾乎等於下單/轉單
    # 時間），converter.py 讀這欄填 BigSeller 的「下单时间」（選填，不影響轉檔成功與否，但填了
    # 比空白有用）。跟「商品貨態時間」共用同一個來源值是刻意的，兩者概念本來就很接近。
    "轉單日": "處理時間",
    "最晚出貨日期": "預計出貨日",
    "出貨/回收日期": "出貨日期",
    "廠退日期": "廠商退貨日期",
    "商品貨態": MOMO_ITEM_STATUS_COLUMN,
    "商品貨態時間": "處理時間",
    "商品屬性": "商品屬性",
    "商品編號": "商品編號",
    "商品名稱": "商品名稱",
    "規格1": "商品規格一",
    "規格2": "商品規格二",
    "商品原廠編號": "商品原廠編號",
    "數量": "數量",
    # 官方沒有獨立的「商品售價」API 欄位，借用「金額」(orderAmount) 當最佳近似值。這欄不只是
    # 格式好看而已——converter.py 靠表頭「商品售價」精確定位單價欄，這裡若留空，匯出的 Excel
    # 拿去轉檔會導致單價、以及依單價算出的「優惠」（單價×數量×平台固定費率）全部變成 0
    # （2026-08-02 使用者實測踩到，見 converter.py PLATFORM_FEE）。
    "商品售價": "金額",
    "收件人姓名": "收件人",
    "收件人地址": "收件地址",
    "客戶編號": "客人個人識別碼",
    "物流商": MOMO_DELIVERY_COMPANY_COLUMN,
    "物流單號": "運單號",
    "配送方式": "配送方式",
    "三方出貨回收地址": "出貨回廠地址",
    # momo_order_query() 已經把運費這個「假品項」濾掉、折算進真正商品列的這一欄，見上面
    # MOMO_SHIPPING_FEE_COLUMN 的說明。
    "客人支付運費": MOMO_SHIPPING_FEE_COLUMN,
    "應稅(免稅)": "應稅/免稅",
    "開立發票金額_依品項(若您是自行開立發票，請依此金額開立予消費者)": "開立發票金額",
    "發票開立統編": "發票開立統編",
    "發票號碼": "發票號碼",
    "發票日期": "發票日期",
}


def build_momo_official_row(row: dict, account=None) -> dict:
    """把 momo_order_query() 產出的一列（Chinese label 為 key）轉成官方匯出格式的一列
    （key＝MOMO_OFFICIAL_ORDER_COLUMNS 裡的欄名）。「統編」「公司名稱」是店鋪自己的固定資料，
    來自 accounts.json 設定（不是 API 回應），比 API 裡語意不確定的欄位可靠。"""
    result = {col: row.get(key, "") for col, key in MOMO_OFFICIAL_ORDER_FIELD_MAP.items()}
    if account is not None:
        result["統編"] = account.tax_id
        result["公司名稱"] = account.company
    return result


_MOMO_STORE_CODE_RE = re.compile(r"^(TP\d{7})")


def momo_store_code_from_goods_no(goods_no) -> str | None:
    """從商品編號（例如 TP00019490000024）取出店鋪代碼（TP0001949）。momo 後台下載的寄件單／
    訂單匯出檔名都是用「這個代碼＋時間戳記」命名（例：LogisticsLabel_TP0001949_...pdf、
    OrderExport_TP0001949_...xls）——不是憑空編的，是從商品編號固定格式
    （TP + 7 碼店鋪代碼 + 8 碼商品序號，已用官方匯出檔案與商品編號實際比對確認）反推出來的。"""
    if not goods_no:
        return None
    m = _MOMO_STORE_CODE_RE.match(str(goods_no))
    return m.group(1) if m else None

# Coupang doc_ref 是工程摘要不是官方逐欄位全文，這裡涵蓋目前已知欄位；沒對照到的 key（Coupang
# 未來新增欄位時）一樣直接用原始 key 當欄名，「抓取任何屬性」的需求不會因為文件沒寫就漏掉。
COUPANG_ORDER_FIELD_LABELS = {
    "orderId": MOMO_ORDER_NO_COLUMN,  # 借用同一個中文欄名「訂單編號」，跟 momo 對齊
    "shipmentBoxId": SHIPMENT_BOX_ID_COLUMN,
    "status": "狀態",
    "orderedAt": "下單時間",
    "paidAt": "付款時間",
    "deliveryCompanyName": "物流商",
    "invoiceNumber": "運單號",
    "remotenessDelivery": "偏遠地區配送",
    "splitShipping": "是否為分批出貨",
    "parcelPrintMessage": "包裹列印訊息",
    "receiver.name": "收件人",
    "receiver.addr1": "收件地址1",
    "receiver.addr2": "收件地址2",
    "receiver.postCode": "收件郵遞區號",
    "receiver.safeNumber": "收件人安心號碼",
    "orderer.name": "訂購人",
    "orderer.email": "訂購人Email",
    "orderer.safeNumber": "訂購人安心號碼",
    "vendorItemId": "單品ID",
    "vendorItemName": "商品名稱(vendorItemName)",
    "sellerProductId": "賣家商品ID",
    "sellerProductName": "商品名稱",
    "sellerProductItemName": "賣家商品品項名稱",
    "externalVendorSkuCode": "賣家SKU",
    "shippingCount": "數量",
    "salesPrice": "單價",
    "discountPrice": "優惠",
    "orderPrice": "應付金額",
}

COUPANG_ORDER_PRIMARY_COLUMNS = [
    MOMO_ORDER_NO_COLUMN, SHIPMENT_BOX_ID_COLUMN, "狀態", "收件人", "收件地址", "下單時間",
    "商品名稱", "賣家SKU", "數量", "單價", "優惠", "應付金額", "物流商", "運單號",
]


def _coupang_orders_to_rows(data: dict, fallback_status: str, remaining: int | None = None) -> list[dict]:
    """把一頁訂單攤平成表格列。

    `remaining` 是「這一頁最多還能再產生幾列」（None＝不限）。有值時會在**訂單邊界**中斷，
    所以同一張訂單的品項不會被切成兩半，實際回傳可能略多於 remaining——這點跟 momo/Shopify
    的處理方式一致，見本模組開頭關於 `limit` 的說明。
    """
    rows = []
    for order in data.get("data", []):
        if remaining is not None and len(rows) >= remaining:
            break
        receiver = order.get("receiver") or {}
        address = " ".join(filter(None, [receiver.get("addr1"), receiver.get("addr2")]))
        order_flat = _flatten({k: v for k, v in order.items() if k != "orderItems"})
        for item in order.get("orderItems", []):
            merged = {**order_flat, **_flatten(item)}
            row = {COUPANG_ORDER_FIELD_LABELS.get(k, k): v for k, v in merged.items()}
            # 這幾欄有 fallback / 組合邏輯，攤平後的原始值要覆寫成跟舊版一致的結果：
            raw_status = order.get("status") or fallback_status
            row["狀態"] = status_labels.translate(status_labels.COUPANG_ORDER_STATUS, raw_status)
            # 出貨面板要靠原始狀態碼（ACCEPT/INSTRUCT/…）判斷該提示做①還是③，
            # 中文化之後就不能再從「狀態」欄反推，所以另外保留一份未翻譯的。
            # 底線開頭 = 隱藏欄位，不會出現在表格上（見 _columns_with_extras）。
            row[COUPANG_RAW_STATUS_KEY] = raw_status
            row["收件地址"] = address
            row["商品名稱"] = item.get("sellerProductName") or item.get("vendorItemName")
            # 「單價」欄（見 COUPANG_ORDER_FIELD_LABELS）是給人看的格式化字串（"599 TWD"），
            # 官方格式匯出（build_coupang_official_row）的「選項價格」欄需要純數字，直接從
            # 還沒被 _money() 轉成字串前的原始 item 取，不要事後解析格式化字串（見底下說明）。
            # 底線開頭 = 隱藏欄位，不會出現在表格上（見 _columns_with_extras）。
            row["_sales_price_units"] = (item.get("salesPrice") or {}).get("units")
            row["_discount_price_units"] = _money_units(item.get("discountPrice"))
            row["_order_price_units"] = _money_units(item.get("orderPrice"))
            row["_shipping_price_units"] = _money_units(order.get("shippingPrice"))
            rows.append(row)
    return rows


# Coupang Wing 後台手動下載「DeliveryList」的官方表頭與順序（最初核對
# DeliveryList(2026-07-30)_(0).xlsx；2026-09-28 再以新版真實下載檔確認末欄新增「統一編號」），
# 供 API 查詢結果匯出時採用同一份格式，
# 讓匯出檔案跟後台手動下載的長得一樣，也能直接餵給 converter.py（訂單轉換）——原本 App 自己的
# 匯出格式（COUPANG_ORDER_PRIMARY_COLUMNS 那份，欄名如「物流商」「運單號」「賣家SKU」）跟
# DeliveryList 欄名完全不同，且「單價」欄是帶幣別的字串，converter.py 讀了會把優惠算成 0
# （使用者實測踩到，詳見開發記錄.md 2026-08-05 條目）。
COUPANG_OFFICIAL_ORDER_COLUMNS = [
    "編號", "捆綁配送編號", "訂單編號", "配送渠道", "快遞公司", "寄件單號", "是否分批配送",
    "預計分批配送日期", "訂購時預計發貨日期", "實際發貨日期", "訂購日期", "註冊商品名稱",
    "註冊選項名稱", "顯示產品名稱", "顯示產品ID", "選項ID", "首次註冊商品名稱/選項名稱",
    "公司商品代碼", "條碼", "應開立予買家之發票金額", "應開立予酷澎之發票金額", "銷售價格",
    "運費類型", "運費", "數量", "選項價格", "訂購人姓名", "聯繫方式(安心碼)", "郵遞區號",
    "收件人地址", "配送訊息", "配送完成日期", "購買者確認日期", "附加資訊", "統一編號",
]

# 官方欄名 -> coupang_order_query() 產生的 row dict 裡對應的 key。只放「確定對應」的直接欄位；
# 需格式化的日期、金額物件、分箱狀態與運費類型由 build_coupang_official_row() 處理。API 沒有回傳或
# 語意不確定的欄位（例如「配送渠道」的 TWL_711 代碼只出現在安排出貨請求，不在訂單查詢回應）
# 一律留空，不拿相近欄位湊值；完整 API 回應另由 excel_export.py 保留在「API原始欄位」工作表。
#
# 「訂購人姓名」刻意對應 API 的 orderer.name（本模組欄名「訂購人」）而不是 receiver.name
# （欄名「收件人」）：已用使用者提供的真實轉換結果反查驗證過；實際訂單識別資訊與姓名不寫入原始碼。
# Wing DeliveryList 的「訂購人姓名」遮罩格式，與 BigSeller 轉換結果的「收件人姓名」遮罩格式可對應，
# 證實 Coupang 這個「訂購人姓名」欄實際存的就是取貨人姓名（超商取貨常見：訂購人＝取貨人，
# 需身分核對），不是收件地址欄位旁看起來像地址接收人的欄位。
COUPANG_OFFICIAL_ORDER_FIELD_MAP = {
    "捆綁配送編號": SHIPMENT_BOX_ID_COLUMN,
    "訂單編號": MOMO_ORDER_NO_COLUMN,
    "快遞公司": MOMO_DELIVERY_COMPANY_COLUMN,
    "寄件單號": "運單號",
    "選項ID": "單品ID",
    "公司商品代碼": "賣家SKU",
    "數量": "數量",
    "訂購人姓名": "訂購人",
    "郵遞區號": "收件郵遞區號",
    "收件人地址": "收件地址",
    "配送訊息": "包裹列印訊息",
    "註冊商品名稱": "商品名稱",
    "註冊選項名稱": "賣家商品品項名稱",
    "顯示產品名稱": "商品名稱(vendorItemName)",
    "顯示產品ID": "productId",
}


def _coupang_order_datetime_to_delivery_format(value) -> str:
    """把 orderedAt 的 ISO8601 格式（例："2026-08-05T04:23:05+08:00"）轉成跟 DeliveryList
    「訂購日期」欄一樣的 "yyyy-mm-dd hh:mm:ss"（converter.py 的 _format_order_datetime()
    認得這個格式；ISO8601 帶 T 與時區偏移反而解析不了，會整串原樣塞進 BigSeller）。
    轉換失敗（格式非預期）時 best-effort 原樣回傳，不中斷匯出流程。"""
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value)).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(value)


def _coupang_date_to_delivery_format(value) -> str:
    """DeliveryList 的純日期欄只保留 yyyy-mm-dd；無法辨識時原樣保留。"""
    if not value:
        return ""
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", str(value))
    return match.group(1) if match else str(value)


def _coupang_split_shipping_label(value) -> str:
    if value in (True, "true", "True", 1, "1"):
        return "支持分箱"
    if value in (False, "false", "False", 0, "0"):
        return "不支持分箱"
    return "" if value in (None, "") else str(value)


def _coupang_delivery_charge_label(value) -> str:
    labels = {
        "free": "免費",
        "not_free": "已付費",
        "paid": "已付費",
        "conditional_free": "條件免運",
    }
    if value in (None, ""):
        return ""
    text = str(value).strip()
    return labels.get(text.lower(), text)


def build_coupang_official_row(row: dict, sequence: int | None = None) -> dict:
    """把 coupang_order_query() 產出的一列（Chinese label 為 key）轉成跟 Coupang Wing 後台
    「DeliveryList」相同表頭的一列（API 沒回傳、或語意不確定的欄位一律留空，不編造數字）。"""
    result = {col: row.get(key, "") for col, key in COUPANG_OFFICIAL_ORDER_FIELD_MAP.items()}
    if sequence is not None:
        result["編號"] = sequence
    result["訂購日期"] = _coupang_order_datetime_to_delivery_format(row.get("下單時間"))
    result["訂購時預計發貨日期"] = _coupang_date_to_delivery_format(row.get("estimatedShippingDate"))
    result["配送完成日期"] = _coupang_order_datetime_to_delivery_format(row.get("deliveredDate"))
    result["購買者確認日期"] = _coupang_order_datetime_to_delivery_format(row.get("confirmDate"))
    result["是否分批配送"] = _coupang_split_shipping_label(row.get("是否為分批出貨"))

    first_item_name = row.get("firstSellerProductItemName")
    seller_product_name = row.get("商品名稱")
    if seller_product_name and first_item_name:
        result["首次註冊商品名稱/選項名稱"] = f"{seller_product_name},{first_item_name}"

    units = row.get("_sales_price_units")
    result["選項價格"] = units if units is not None else ""
    result["銷售價格"] = units if units is not None else ""
    result["運費"] = row.get("_shipping_price_units", "")
    result["運費類型"] = _coupang_delivery_charge_label(row.get("deliveryChargeTypeName"))
    safe_number = row.get("收件人安心號碼") or row.get("訂購人安心號碼")
    result["聯繫方式(安心碼)"] = safe_number or ""
    return result


def momo_order_query(account, date_from=None, date_to=None, status=None, order_no=None,
                     entp_goods_no=None, limit=None, **_):
    client = MomoClient.from_account(account)
    if not date_from or not date_to:
        today = datetime.now()
        date_from = (today - timedelta(days=7)).strftime("%Y/%m/%d")
        date_to = today.strftime("%Y/%m/%d")

    resp = client.query_orders(
        from_date=date_from,
        to_date=date_to,
        order_status=status or "All",
        list_order_no=[order_no] if order_no else None,
        # 商品原廠編號是 API 原生篩選條件（支援模糊查詢），交給 momo 端過濾，不用整批抓回來自己比對
        entp_goods_no=entp_goods_no,
        # momo 這支沒有 nextToken 之類的續查機制，一次就把該區間全部回來，
        # 所以 maxPerPage 給大一點（官方規定最小 100），上限改由下面的迴圈自己控。
        max_per_page=max(limit or 100, 100),
    )
    data = resp.json()
    if data.get("errorMessage"):
        raise RuntimeError(data["errorMessage"])

    # OrderQuery 回應本身不含訂單層級的「訂單狀態」欄位（只有品項層級的 itemStatus），但 momo 的
    # 訂單狀態篩選是 API 端做的——查詢時指定了非 All 的狀態，回來的每一筆就保證符合那個狀態，
    # 所以可以把篩選條件反推回填到「訂單狀態」欄，不是編造資料。這一步也是為了跟
    # converter.py（Phase 1 手動匯入流程）相容：它靠「訂單狀態」欄的文字（"已印單"/"已印單待寄件"）
    # 篩選待處理訂單，官方後台匯出的 Excel 本來就有這欄，這裡的匯出格式若留空，
    # converter.py 會直接篩出 0 筆（2026-08-02 使用者實測踩到）。查 All／不指定狀態時無法反推
    # （回來的訂單可能各種狀態都有），維持空白，不要亂填。
    # 注意：這裡故意不用 status_labels.translate()——那支回傳「中文（原碼）」格式（例如
    # "已印單（Printed）"），但 converter.py 是用純中文字串精確比對（"已印單"／"已印單待寄件"），
    # 帶了括號原碼反而會比對不到，所以直接查表拿純中文。
    order_status_cn = status_labels.MOMO_ORDER_STATUS.get(status) if status and status != "All" else None

    rows = []
    for order in data.get("listOrder", []):
        if _reached(rows, limit):
            break  # 在「訂單」層級中斷，同一張訂單的品項不會被切成兩半
        order_flat = _flatten({k: v for k, v in order.items() if k != "listItem"})
        items = order.get("listItem", [])
        # 運費是假品項（goodsName 固定叫「運費」），不是真正的商品，先算出這張訂單的運費總額，
        # 底下建立品項列時要濾掉它、改成附加欄位（見 MOMO_SHIPPING_FEE_GOODS_NAME 的說明）。
        shipping_fee = sum(
            _number_or_zero(item.get("orderAmount"))
            for item in items
            if item.get("goodsName") == MOMO_SHIPPING_FEE_GOODS_NAME
        )
        order_total_amount = sum(_number_or_zero(item.get("orderAmount")) for item in items)
        for item in items:
            if item.get("goodsName") == MOMO_SHIPPING_FEE_GOODS_NAME:
                continue
            merged = {**order_flat, **_flatten(item)}
            row = {MOMO_ORDER_FIELD_LABELS.get(k, k): v for k, v in merged.items()}
            if order_status_cn:
                row[MOMO_ORDER_STATUS_COLUMN] = order_status_cn
            if shipping_fee:
                row[MOMO_SHIPPING_FEE_COLUMN] = shipping_fee
            row["_order_total_amount"] = order_total_amount
            rows.append(row)

    columns = _columns_with_extras(rows, MOMO_ORDER_PRIMARY_COLUMNS)
    return columns, rows


def momo_goods_query(account, sku=None, status=None, entp_goods_no=None, limit=None, **_):
    """momo 商品查詢。

    `entp_goods_no`（商品原廠編號）是**本地過濾**，不是 API 篩選——
    `GoodsQueryByMethod` 的 request body 只有 queryMethod / saleStatus / pageIndex /
    maxPerPage / applyDate / listGoods(goodsCode + listGoodsdtCode)，沒有 entpGoodsNo 這個參數；
    entpGoodsNo 只出現在 **回應** 的 listGoodsdt 裡（見 doc_ref/mo店+ API 串接的資料/
    20241007001.pdf 第 16-17 頁）。訂單那支 OrderQuery 反而原生支援 entpGoodsNo 模糊查詢，
    兩支不一樣，不要看到訂單能查就以為商品也能直接丟給 API。

    因為是先抓回來才過濾，`limit`（查詢上限）套用在**過濾後**的列數上：抓一批、濾一批、
    夠了就停，避免使用者填了商品原廠編號卻因為前幾頁剛好都不符合而回 0 筆。
    """
    client = MomoClient.from_account(account)
    sale_status = status or "StartSelling"
    list_goods = [{"goodsCode": sku}] if sku else None
    # queryMethod=All 才會連庫存(quantity)、商品原廠編號(entpGoodsNo)、規格(goodsdtInfo)一起回來；
    # 原本用 SaleType 只查上下架狀態，這些欄位都是 null。
    resp = client.query_goods(
        query_method="All",
        sale_status=sale_status,
        max_per_page=max(limit or 100, 100),
        list_goods=list_goods,
    )
    data = resp.json()

    columns = ["商品編號", "商品名稱", "上架狀態", "單品編號", "商品原廠編號", "規格", "庫存量", "售價", "市價"]
    # 商品原廠編號比對比照 momo API 的行為做「模糊查詢」＋不分大小寫，使用者才不用打完整編號
    entp_keyword = (entp_goods_no or "").strip().lower()

    def _match_entp(value) -> bool:
        if not entp_keyword:
            return True
        return entp_keyword in str(value or "").lower()

    rows = []
    for g in data.get("result", []):
        if _reached(rows, limit):
            break  # 在「商品」層級中斷，同一個商品的規格(listGoodsdt)不會被切成兩半
        if not g.get("success", True):
            continue
        sale_status_text = status_labels.translate(status_labels.MOMO_GOODS_STATUS_DISPLAY, g.get("saleStatus"))
        goodsdt_list = g.get("listGoodsdt") or []
        if not goodsdt_list:
            # 沒有子品項資訊時，還是至少列出商品本身這一列，不要整筆消失。
            # 但有指定商品原廠編號時就不能列——這一列根本沒有商品原廠編號可比對，列出來等於沒篩選。
            if entp_keyword:
                continue
            rows.append(
                {
                    "商品編號": g.get("goodsCode"),
                    "商品名稱": g.get("goodsName"),
                    "上架狀態": sale_status_text,
                }
            )
            continue
        for dt in goodsdt_list:
            if not _match_entp(dt.get("entpGoodsNo")):
                continue
            rows.append(
                {
                    "商品編號": g.get("goodsCode"),
                    "商品名稱": g.get("goodsName"),
                    "上架狀態": sale_status_text,
                    "單品編號": dt.get("goodsdtCode"),
                    "商品原廠編號": dt.get("entpGoodsNo"),
                    "規格": dt.get("goodsdtInfo"),
                    "庫存量": dt.get("quantity"),
                    "售價": dt.get("salePrice"),
                    "市價": dt.get("custPrice"),
                }
            )
    return columns, rows


def coupang_order_query(account, date_from=None, date_to=None, status=None, order_no=None, limit=None, **_):
    client = CoupangClient.from_account(account)

    if order_no:
        resp = client.get_order_by_id(order_no)
        data = resp.json()
        if data.get("code") != 200:
            raise RuntimeError(data.get("message", "查詢失敗"))
        rows = _coupang_orders_to_rows(data, status or "")
        return _columns_with_extras(rows, COUPANG_ORDER_PRIMARY_COLUMNS), rows

    if not date_from or not date_to:
        today = datetime.now()
        date_from = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        date_to = today.strftime("%Y-%m-%d")
    statuses = [status] if status else COUPANG_ORDER_STATUSES
    max_per_page = _batch_size(limit, api_max=50, default=50)

    rows = []
    errors = []
    for st in statuses:
        if _reached(rows, limit):
            break  # 已經抓夠了，剩下的狀態就不用再查（沒選狀態時會逐一查 6 種狀態）
        next_token = None
        for _page in range(_MAX_PAGES_PER_STATUS):
            resp = client.query_ordersheets_by_day(
                status=st, date_from=date_from, date_to=date_to,
                max_per_page=max_per_page, next_token=next_token,
            )
            data = resp.json()
            if data.get("code") != 200:
                errors.append(f"{st}: {data.get('message', '查詢失敗')}")
                break
            remaining = (limit - len(rows)) if limit else None
            rows.extend(_coupang_orders_to_rows(data, st, remaining=remaining))
            next_token = data.get("nextToken")
            if not next_token or _reached(rows, limit):
                break

    if not rows and errors:
        raise RuntimeError("；".join(errors))
    return _columns_with_extras(rows, COUPANG_ORDER_PRIMARY_COLUMNS), rows


def coupang_product_query(account, keyword=None, sku=None, status=None, limit=None, **_):
    client = CoupangClient.from_account(account)
    columns = ["賣家商品ID", "商品名稱", "狀態", "上架時間"]

    if sku:
        resp = client.get_product_by_sku(sku)
        data = resp.json()
        if data.get("code") != "SUCCESS":
            raise RuntimeError(data.get("message") or "查詢失敗（回應內容異常，請檢查 API 是否有變動）")
        rows = [
            {
                "賣家商品ID": p.get("sellerProductId"),
                "商品名稱": p.get("sellerProductName"),
                "狀態": p.get("statusName"),
                "上架時間": p.get("createdAt"),
            }
            for p in data.get("data", [])
        ]
        return columns, rows

    rows = []
    next_token = None
    for _page in range(_MAX_PAGES_PER_STATUS):
        resp = client.query_products(
            status=status or "APPROVED",
            max_per_page=_batch_size(limit, api_max=50, default=50),
            next_token=next_token,
            seller_product_name=keyword,
        )
        data = resp.json()
        if data.get("code") != "SUCCESS":
            raise RuntimeError(data.get("message") or "查詢失敗（回應內容異常，請檢查 API 是否有變動）")
        rows.extend(
            {
                "賣家商品ID": p.get("sellerProductId"),
                "商品名稱": p.get("sellerProductName"),
                "狀態": p.get("statusName"),
                "上架時間": p.get("createdAt"),
            }
            for p in data.get("data", [])
        )
        next_token = data.get("nextToken")
        if not next_token or _reached(rows, limit):
            break
    return columns, rows


SHOPIFY_PRODUCTS_QUERY = """
query ProductsQuery($first: Int!, $after: String, $query: String) {
  products(first: $first, after: $after, query: $query, sortKey: UPDATED_AT) {
    nodes {
      id
      title
      status
      vendor
      productType
      tags
      totalInventory
      updatedAt
      variants(first: 50) {
        nodes { id title sku barcode price }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def shopify_products_query(account, keyword=None, sku=None, status=None, limit=None, **_):
    client = ShopifyClient.from_account(account)
    columns = [
        "商品ID", "商品名稱", "狀態", "供應商", "商品類型", "標籤", "總庫存", "更新時間",
        "規格", "SKU", "條碼", "價格",
    ]

    # Shopify 商品搜尋語法：sku:/status: 是官方支援的篩選 key，裸關鍵字預設會比對標題等欄位。
    filters = []
    if sku:
        filters.append(f"sku:{sku}")
    if status:
        filters.append(f"status:{status}")
    if keyword:
        filters.append(keyword)
    query_filter = " AND ".join(filters) if filters else None

    rows = []
    after = None
    # Shopify GraphQL products(first:) 單頁上限 250。注意這裡的 first 是「商品」數，
    # 但每個商品會展開成多列（一個 variant 一列），所以列數通常會多於商品數——
    # limit 是用來限制「列數」的，實際中斷判斷在下面的迴圈裡做。
    max_per_page = _batch_size(limit, api_max=250, default=50)
    truncated = False
    for _page in range(_MAX_PAGES_PER_STATUS):
        resp = client.graphql(
            SHOPIFY_PRODUCTS_QUERY, {"first": max_per_page, "after": after, "query": query_filter}
        )
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(str(data["errors"]))

        products = (data.get("data") or {}).get("products") or {}
        for p in products.get("nodes", []):
            if _reached(rows, limit):
                truncated = True
                break  # 在「商品」層級中斷，同一個商品的 variants 不會被切成兩半
            base = {
                "商品ID": p.get("id"),
                "商品名稱": p.get("title"),
                "狀態": status_labels.translate(status_labels.SHOPIFY_PRODUCT_STATUS, p.get("status")),
                "供應商": p.get("vendor"),
                "商品類型": p.get("productType"),
                "標籤": ",".join(p.get("tags") or []),
                "總庫存": p.get("totalInventory"),
                "更新時間": p.get("updatedAt"),
            }
            variants = (p.get("variants") or {}).get("nodes") or []
            if not variants:
                rows.append(base)
                continue
            for v in variants:
                rows.append(
                    {**base, "規格": v.get("title"), "SKU": v.get("sku"), "條碼": v.get("barcode"), "價格": v.get("price")}
                )

        page_info = products.get("pageInfo") or {}
        if truncated or not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")

    return columns, rows


RUN_HANDLERS = {
    "momo_order_query": momo_order_query,
    "momo_goods_query": momo_goods_query,
    "cp_order_query": coupang_order_query,
    "cp_product_query": coupang_product_query,
    "shopify_products_query": shopify_products_query,
}
