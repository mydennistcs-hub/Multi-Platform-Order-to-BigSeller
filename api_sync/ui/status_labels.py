"""各平台「狀態」代碼 → 繁體中文顯示名稱的集中對照表。

query_panel（下拉選單顯示中文、送 API 時送回英文代碼）與 handlers（把查詢結果的狀態欄
翻成中文）都從這裡取，避免兩邊各寫一份翻譯而不一致。放獨立模組是為了不讓 handlers 反過來
import query_panel 造成循環相依。

**譯名來源分級**（改動前請先確認自己要改的是哪一種）：

1. momo：**官方文件原文**，逐字取自 `doc_ref/mo店+ API 串接的資料/20241007001.pdf`
   第 54 頁（orderStatus 對照表）與第 18 頁（saleStatus 說明）。
   例如 `NotShipped` 官方就是寫「未出貨(未印單)」、`DoneDelivery` 是「配送結束」而不是
   「配送完成」——不要自己改成看起來比較順的講法，這樣才跟賣家在 mo店+ 後台看到的一致。
2. Coupang：doc_ref 是工程摘要，**沒有官方逐欄位中文對照**。這裡沿用本專案既有的講法
   （跟 `ui/label_panel.py` 的 `_STATUS_HINTS`、CLAUDE.md 的出貨三步驟表一致），
   語意正確但用詞不保證跟 Wing 後台逐字相同，日後若對照到官方中文可再校正。
3. Shopify：同樣沒有官方中文對照檔，採 Shopify 繁中後台商品狀態的常見用語。
   ⚠️ 尚未跟實際後台畫面逐字核對過。
"""

# ---- momo（官方 PDF 原文）----
# 20241007001.pdf 第 54 頁 orderStatus 對照表
MOMO_ORDER_STATUS = {
    "All": "全部",
    "Unpaid": "未付款",
    "NotShipped": "未出貨(未印單)",
    "NotRecycled": "未回收",
    "Printed": "已印單",
    "Shipping": "配送中",
    "DoneDelivery": "配送結束",
    "AbnormalDelivery": "配送異常",
    "OrderCancelled": "取消訂單",
    "ReturnCancelled": "取消退貨",
    "RecycleConfirmed": "回收確認",
}

# 20241007001.pdf 第 18 頁 saleStatus 說明
MOMO_GOODS_STATUS = {
    # 官方原文是「All：查詢上架與下架的所有商品」，這裡取「全部」即可——
    # 顯示格式是「中文（原碼）」，譯名裡再加一組括號會變成「全部（上架與下架）（All）」很難讀。
    "All": "全部",
    "StartSelling": "上架中",
    "StopSelling": "已下架",
}

# 官方文件在請求端寫 "StartSelling"、回應端的欄位說明卻寫成 "Startselling"（第 18 頁兩行並列，
# 大小寫不一致），所以顯示用的對照表要多收這個別名。下拉選單只用上面那份，免得出現兩個「上架中」。
MOMO_GOODS_STATUS_DISPLAY = {**MOMO_GOODS_STATUS, "Startselling": "上架中"}

# 商品子品項(listGoodsdt)的 dtSaleStatus
MOMO_GOODSDT_STATUS = {"on": "上架中", "off": "已下架"}

# ---- Coupang（本專案既有講法，非官方逐字）----
# 譯名裡不要再放括號——顯示格式已經是「中文（原碼）」，會變成兩層括號很難讀。
COUPANG_ORDER_STATUS = {
    "ACCEPT": "訂單確認",
    "INSTRUCT": "商品準備中",
    "DEPARTURE": "待寄出",
    "DELIVERING": "配送中",
    "FINAL_DELIVERY": "配送完成",
    "NONE_TRACKING": "無配送追蹤",
}

COUPANG_PRODUCT_STATUS = {
    "APPROVED": "已核准銷售中",
    "IN_REVIEW": "審核中",
}

# ---- Shopify（繁中後台常見用語，尚未逐字核對）----
SHOPIFY_PRODUCT_STATUS = {
    "ACTIVE": "有效",
    "ARCHIVED": "已封存",
    "DRAFT": "草稿",
}


def translate(mapping: dict, code) -> str:
    """把狀態代碼換成中文顯示字串。

    對照不到就原樣回傳（平台日後新增狀態時不會變成空白或報錯，至少看得到原始代碼）；
    空值回空字串。顯示格式固定為「中文（原碼）」，保留原碼是刻意的——排查問題、對照官方
    文件、跟客服溝通時都需要那組英文代碼。
    """
    if code is None or code == "":
        return ""
    text = mapping.get(code)
    if text is None:
        return str(code)
    return f"{text}（{code}）"


def options(mapping: dict, include_blank: bool = False) -> list:
    """給 QComboBox 用：回傳 [(顯示文字, API 代碼), ...]。

    include_blank=True 時最前面加一個空白項，代表「不指定狀態」（Coupang/Shopify 用；
    momo 是用 "All" 這個明確代碼表示全部，不需要空白項）。
    """
    items = [("（全部）", "")] if include_blank else []
    items += [(f"{label}（{code}）", code) for code, label in mapping.items()]
    return items
