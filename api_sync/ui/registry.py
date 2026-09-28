"""momo / Coupang / Shopify 目前開放的 API 功能清單，做為 UI 導覽的資料來源。

momo 路徑/方法逐字取自 doc_ref/mo店+ API 串接的資料/20241007001.pdf；
Coupang 逐字取自 doc_ref/coupang API 串接的資料/coupang_open_api_tw_agent_pack.md；
Shopify 取自 doc_ref/shopify API 串接的資料/shopify_api_agent_guide.md 與
shopify_api_official_sources.md（2026-07-31 核實，API 版本 2026-07）。均不是自己推測。
`implemented=True` 代表 api_sync/ 底下已經有可用的用戶端邏輯（目前 momo/Coupang 訂單查詢等
已實作，Shopify 全部尚未實作，見下方 SHOPIFY_FUNCTIONS 一律 implemented=False），其餘都還只是 UI 佔位。

Shopify 跟 momo/Coupang 不同的地方：Shopify Admin API 是 GraphQL，只有「一個」endpoint
（/admin/api/{version}/graphql.json），不同功能是靠 GraphQL query/mutation 名稱區分，不是
不同的 REST path。所以下面 SHOPIFY_FUNCTIONS 每一項的 method/path 都一樣，真正的區分資訊在
description 裡標注的 query/mutation 名稱。
"""

from dataclasses import dataclass


@dataclass
class ApiFunction:
    key: str
    name: str
    category: str
    method: str
    path: str
    description: str = ""
    implemented: bool = False
    deprecated: bool = False
    needs_date_range: bool = False  # UI 是否要顯示起訖日期選擇器
    # 這支 API 已經被合併到哪一個功能的頁面裡（填對方的 key）。
    # 填了之後左側功能樹「不會」再單獨列出這一項，因為它已經是目標頁面內建的一個動作
    # （例如 momo 各物流的出貨確認/重印標籤，全部收在「訂單」頁下半部的「動作類型」下拉選單；
    # Coupang 的①確認訂單/②安排出貨/③下載寄件單，全部收在「訂單」頁下半部的三個按鈕）。
    # 保留在這份清單裡是刻意的——它同時也是 API 盤點文件，method/path 不該因為 UI 合併而消失。
    merged_into: str | None = None


MOMO_BASE_URL = "https://api3p.momo.com.tw"

MOMO_FUNCTIONS: list[ApiFunction] = [
    # 商品相關
    ApiFunction("momo_goods_start_selling", "商品上架", "商品相關", "POST", "/VendorApi/GoodsStartSelling"),
    ApiFunction("momo_goods_stop_selling", "商品下架", "商品相關", "POST", "/VendorApi/GoodsStopSelling"),
    ApiFunction(
        "momo_goods_price_modify", "商品價格異動", "商品相關", "POST", "/VendorApi/GoodsPriceModify",
        description="已由「商品規格(sku)價格異動」取代", deprecated=True,
    ),
    ApiFunction("momo_goodsdt_price_modify", "商品規格(sku)價格異動", "商品相關", "POST", "/VendorApi/GoodsdtPriceModify"),
    ApiFunction("momo_goods_stock_modify", "商品庫存量異動", "商品相關", "POST", "/VendorApi/GoodsStockModify"),
    ApiFunction(
        "momo_goods_query", "商品查詢", "商品相關", "POST", "/VendorApi/GoodsQueryByMethod",
        implemented=True, description="查詢目前已上架商品。api_sync/momo_client.py: MomoClient.query_goods",
    ),
    ApiFunction("momo_temp_goods_modify", "新增商品&編輯暫存商品", "商品相關", "POST", "/apiv2/VendorApi/TempGoodsmodify"),
    ApiFunction("momo_goods_modify", "已上架商品資料編輯", "商品相關", "POST", "/apiv2/VendorApi/GoodsModify"),
    ApiFunction("momo_file_upload", "圖檔上傳", "商品相關", "POST", "/apiv2/VendorApi/FileUpload"),
    ApiFunction("momo_file_detail", "使用圖檔ID查詢", "商品相關", "POST", "/apiv2/VendorApi/FileDetail"),
    ApiFunction("momo_category_tree", "商品分類清單", "商品相關", "POST", "/apiv2/VendorApi/CategoryTree"),
    ApiFunction("momo_category_setting", "商品分類屬性查詢", "商品相關", "POST", "/apiv2/VendorApi/CategorySetting"),
    ApiFunction("momo_list_web_brand", "品牌列表", "商品相關", "POST", "/apiv2/VendorApi/ListWebBrand"),
    ApiFunction("momo_list_web_brand_series", "品牌系列查詢", "商品相關", "POST", "/apiv2/VendorApi/ListWebBrandSeries"),
    ApiFunction("momo_list_category_by_entp", "商店分類列表", "商品相關", "POST", "/apiv2/VendorApi/ListCategoryByEntp"),
    ApiFunction("momo_get_toutplace_list", "第三方物流出貨地列表", "商品相關", "POST", "/apiv2/VendorApi/GetToutplaceList"),
    ApiFunction("momo_query_setting", "查詢分類是否需要填寫商品規格描述", "商品相關", "POST", "/apiv2/VendorApi/QuerySetting"),
    ApiFunction("momo_modify_sku_sale_gb", "商品規格(sku)狀態異動", "商品相關", "POST", "/apiv2/VendorApi/ModifySkuSaleGb"),
    ApiFunction("momo_file_list", "素材/圖檔列表查詢", "商品相關", "POST", "/apiv2/VendorApi/FileList"),
    ApiFunction("momo_get_customize_freight_list", "查詢自訂物流運費清單", "商品相關", "POST", "/apiv2/VendorApi/GetCustomizeFreightList"),
    ApiFunction("momo_file_quote", "查詢素材/圖檔空間大小", "商品相關", "POST", "/apiv2/VendorApi/FileQuote"),
    ApiFunction("momo_file_batch_remove", "批次刪除素材/圖檔", "商品相關", "POST", "/apiv2/VendorApi/FileBatchRemove"),
    # 訂單相關
    ApiFunction(
        "momo_order_query", "訂單", "訂單相關", "POST", "/VendorApi/OrderQuery",
        implemented=True, needs_date_range=True,
        description=(
            "查詢＋出貨確認＋重印標籤同一頁完成。上半部查訂單，點任一列自動帶入下半部，"
            "下半部的「動作類型」下拉選單涵蓋 7-11／全家／第三方物流的出貨確認與重印標籤。\n"
            "api_sync/momo_client.py: MomoClient.query_orders（官方限制起訖區間最長30天）"
        ),
    ),
    ApiFunction("momo_home_delivery_confirm", "宅配出貨確認", "訂單相關", "POST", "/VendorApi/OrderShippingStatusConfirmHomeDelivery",
                description="使用者商店未開通宅配，暫不需實作"),
    ApiFunction(
        "momo_third_party_delivery_confirm", "第三方物流出貨確認", "訂單相關", "POST",
        "/VendorApi/OrderShippingStatusConfirmThirdPartyDelivery", implemented=True,
        merged_into="momo_order_query",
        description="⚠️會將訂單標記為已出貨，無法復原。api_sync/momo_client.py: MomoClient.confirm_third_party_delivery",
    ),
    ApiFunction(
        "momo_seven_store_delivery_confirm", "7-11超商出貨確認", "訂單相關", "POST",
        "/VendorApi/OrderShippingStatusConfirmSevenStoreDelivery", implemented=True,
        merged_into="momo_order_query",
        description="⚠️會將訂單標記為已出貨，無法復原。api_sync/momo_client.py: MomoClient.confirm_seven_store_delivery",
    ),
    ApiFunction("momo_order_recover", "商品回收確認", "訂單相關", "POST", "/VendorApi/OrderRecover"),
    ApiFunction(
        "momo_seven_store_print_label", "711超商重印標籤", "訂單相關", "POST",
        "/VendorApi/OrderShippingSevenStorePrintLabel", implemented=True,
        merged_into="momo_order_query",
        description="唯讀補印，不異動訂單狀態。api_sync/momo_client.py: MomoClient.reprint_seven_store_label",
    ),
    ApiFunction(
        "momo_third_party_print_label", "第三方物流重印標籤", "訂單相關", "POST",
        "/VendorApi/OrderShippingThirdPartyPrintLabel", implemented=True,
        merged_into="momo_order_query",
        description="唯讀補印，不異動訂單狀態。api_sync/momo_client.py: MomoClient.reprint_third_party_label",
    ),
    ApiFunction(
        "momo_family_store_delivery_confirm", "全家超商出貨確認", "訂單相關", "POST",
        "/VendorApi/OrderShippingStatusConfirmFamilyStoreDelivery", implemented=True,
        merged_into="momo_order_query",
        description="⚠️會將訂單標記為已出貨，無法復原。api_sync/momo_client.py: MomoClient.confirm_family_store_delivery",
    ),
    ApiFunction(
        "momo_family_store_print_label", "全家超商重印標籤", "訂單相關", "POST",
        "/VendorApi/OrderShippingFamilyStorePrintLabel", implemented=True,
        merged_into="momo_order_query",
        description="唯讀補印，不異動訂單狀態。api_sync/momo_client.py: MomoClient.reprint_family_store_label",
    ),
    ApiFunction("momo_order_change_addr", "訂單更換地址", "訂單相關", "POST", "/VendorApi/OrderChangeAddr"),
]


COUPANG_BASE_URL = "https://api-gateway.coupang.com"

COUPANG_FUNCTIONS: list[ApiFunction] = [
    ApiFunction(
        "cp_arrange_shipment", "安排直接整合的快遞出貨［僅台灣］", "運輸/訂單API", "POST",
        "/v2/providers/openapi/apis/api/v1/vendors/{vendorId}/orders/directIntegration/arrangeShipment",
        implemented=True, merged_into="cp_order_query",
        description="⚠️會將訂單標記為待寄出並配發運單號，無法復原。api_sync/coupang_client.py: CoupangClient.arrange_shipment",
    ),
    ApiFunction(
        "cp_download_invoices", "下載直接整合物流發票［僅台灣］", "運輸/訂單API", "POST",
        "/v2/providers/openapi/apis/api/v1/vendors/{vendorId}/orders/directIntegration/downloadInvoices",
        implemented=True, merged_into="cp_order_query",
        description=(
            "下載寄件單，唯讀不異動狀態。訂單未安排出貨前查不到，運送完成7天後過期。"
            "api_sync/coupang_client.py: CoupangClient.download_invoices"
        ),
    ),
    ApiFunction("cp_cs_reply_call_center", "回覆酷澎客服中心諮詢", "客服/諮詢", "POST",
                "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/callCenterInquiries/{inquiryId}/replies"),
    ApiFunction("cp_cs_reply_online_inquiry", "回覆顧客商品諮詢", "客服/諮詢", "POST",
                "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/onlineInquiries/{inquiryId}/replies"),
    ApiFunction("cp_product_delete", "刪除商品", "商品API", "DELETE",
                "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}"),
    ApiFunction("cp_product_inventories", "批次查詢商品庫存資訊", "商品API", "GET",
                "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/inventories"),
    ApiFunction("cp_product_change_base_price", "更改商品等級的折扣率基準價格", "商品API", "PUT",
                "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/original-prices/{originalPrice}"),
    ApiFunction("cp_logistics_update_return_location", "更改退貨地址", "物流資訊", "PUT",
                "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/returnShippingCenters/{returnCenterCode}"),
    ApiFunction("cp_order_cancel", "取消訂單", "運輸/訂單API", "POST",
                "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/orders/{orderId}/cancel"),
    ApiFunction("cp_logistics_courier_code", "物流公司代碼（參考頁）", "物流資訊", "ETC", "(reference page)"),
    ApiFunction("cp_category_metadata", "品類元數據查詢", "品類API", "GET",
                "/v2/providers/seller_api/apis/api/v1/marketplace/meta/category-related-metas/display-category-codes/{displayCategoryCode}"),
    ApiFunction("cp_logistics_create_return_location", "建立退貨地", "物流資訊", "POST",
                "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/returnShippingCenters"),
    ApiFunction("cp_logistics_create_shipping_location", "建立發貨地址", "物流資訊", "POST",
                "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/outboundShippingCenters"),
    ApiFunction("cp_product_resume_sales", "恢復商品中單品的銷售狀態", "商品API", "PUT",
                "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/sales/resume"),
    ApiFunction("cp_cs_query_by_product", "按商品查詢顧客諮詢", "客服/諮詢", "GET",
                "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/onlineInquiries"),
    ApiFunction("cp_category_list", "查看品類列表", "品類API", "GET",
                "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories"),
    ApiFunction("cp_logistics_query_one_return_location", "查看單件退貨地址", "物流資訊", "GET",
                "/v2/providers/openapi/apis/api/v3/return/shipping-places/center-code"),
    ApiFunction(
        "cp_order_query", "訂單", "運輸/訂單API", "GET",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/ordersheets 等",
        implemented=True, needs_date_range=True,
        description=(
            "查詢＋①確認訂單＋②安排出貨＋③下載寄件單同一頁完成，點結果任一列自動帶入下半部。\n"
            "合併「分鐘為單位／按天分頁／依訂單號查詢」3 支 API 成單一入口："
            "填訂單號→直接查該筆；否則依日期區間＋狀態分頁查詢（官方限制起訖區間最長31天）。"
            "api_sync/coupang_client.py: CoupangClient.query_ordersheets_by_day / get_order_by_id"
        ),
    ),
    ApiFunction("cp_return_requests_list", "查詢退貨/取消訂單記錄", "退貨API", "GET",
                "/v2/providers/openapi/apis/api/v6/vendors/{vendorId}/returnRequests"),
    ApiFunction("cp_product_status_history", "查詢商品狀態變更紀錄", "商品API", "GET",
                "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}/histories"),
    ApiFunction("cp_product_inflow_status", "查詢商品註冊狀態", "商品API", "GET",
                "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/inflow-status"),
    ApiFunction("cp_order_by_shipmentbox", "查詢單個訂單（合併配送號碼）", "運輸/訂單API", "GET",
                "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/ordersheets/{shipmentBoxId}"),
    ApiFunction("cp_cs_call_center_list", "查詢酷澎客服中心的諮詢記錄", "客服/諮詢", "GET",
                "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/callCenterInquiries"),
    ApiFunction("cp_cs_call_center_single", "查詢聯絡中心的單項問詢", "客服/諮詢", "GET",
                "/v2/providers/openapi/apis/api/v5/vendors/callCenterInquiries/{inquiryId}"),
    ApiFunction(
        "cp_order_acknowledgement", "訂單狀態變更為準備中（＝Wing 後台的「確認訂單」）", "運輸/訂單API", "PATCH",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/ordersheets/acknowledgement",
        implemented=True, merged_into="cp_order_query",
        description=(
            "⚠️會將訂單狀態從 ACCEPT 變更為 INSTRUCT，無法復原。安排出貨(arrangeShipment)前必須先做這步。"
            "已整合進「訂單」頁下半部的①按鈕，不用另外點這裡。"
            "api_sync/coupang_client.py: CoupangClient.acknowledge_orders"
        ),
    ),
    ApiFunction("cp_product_change_quantity", "修改商品的庫存數量", "商品API", "PUT",
                "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/quantities/{quantity}"),
    ApiFunction("cp_logistics_update_shipping_location", "修改發貨地址", "物流資訊", "PUT",
                "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/outboundShippingCenters/{outboundShippingPlaceCode}"),
    ApiFunction("cp_return_approval", "退貨申請稽核", "退貨API", "PATCH",
                "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/returnRequests/{receiptId}/approval"),
    ApiFunction("cp_return_receive_confirmation", "退貨商品確認入庫", "退貨API", "PATCH",
                "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/returnRequests/{receiptId}/receiveConfirmation"),
    ApiFunction("cp_product_query_partial", "商品查詢（無需審核）", "商品API", "GET",
                "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}/partial"),
    ApiFunction("cp_product_modify", "商品修改", "商品API", "PUT",
                "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"),
    ApiFunction("cp_product_modify_partial", "商品修改（無需審核）", "商品API", "PUT",
                "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}/partial"),
    ApiFunction("cp_product_create", "商品創建", "商品API", "POST",
                "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"),
    ApiFunction("cp_product_request_approval", "商品審核申請", "商品API", "PUT",
                "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}/approvals"),
    ApiFunction(
        "cp_product_query", "商品查詢", "商品API", "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products 等",
        implemented=True,
        description=(
            "合併「產品清單分頁查詢／查詢商品資訊摘要(SKU)」成單一入口："
            "填商品貨號(SKU)→直接查該筆；否則依關鍵字/狀態分頁查詢清單。"
            "api_sync/coupang_client.py: CoupangClient.query_products / get_product_by_sku"
        ),
    ),
    ApiFunction("cp_product_list_time_frame", "產品清單區間查詢", "商品API", "GET",
                "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/time-frame"),
    ApiFunction("cp_logistics_query_return_locations", "透過賣家程式碼查詢退貨地", "物流資訊", "GET",
                "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/returnShippingCenters"),
    ApiFunction("cp_return_query_one", "單件退貨查詢", "退貨API", "GET",
                "/v2/providers/openapi/apis/api/v6/vendors/{vendorId}/returnRequests/{receiptId}"),
    ApiFunction("cp_logistics_query_shipping_location", "發貨地址查詢", "物流資訊", "GET",
                "/v2/providers/marketplace_openapi/apis/api/v2/vendor/shipping-place/outbound"),
    ApiFunction("cp_product_suspend_sales", "暫停商品中單品的銷售", "商品API", "PUT",
                "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/sales/stop"),
    ApiFunction("cp_cs_confirm_call_center", "確認酷澎客服諮詢", "客服/諮詢", "POST",
                "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/callCenterInquiries/{inquiryId}/confirms"),
    ApiFunction("cp_order_delivery_history", "檢視訂單配送狀態歷史記錄", "運輸/訂單API", "GET",
                "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/ordersheets/{shipmentBoxId}/history"),
    ApiFunction("cp_korea_city_postcode", "韓省市對照表（參考頁）", "運輸/訂單API", "ETC", "(reference page)"),
    ApiFunction("cp_product_change_price", "變更產品中各單品的價格", "商品API", "PUT",
                "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/prices/{price}"),
]


SHOPIFY_BASE_URL = "https://{store_domain}"
SHOPIFY_GRAPHQL_PATH = "/admin/api/2026-07/graphql.json"

SHOPIFY_FUNCTIONS: list[ApiFunction] = [
    # 訂單相關
    ApiFunction(
        "shopify_orders_query", "訂單查詢（含增量游標分頁）", "訂單相關", "POST", SHOPIFY_GRAPHQL_PATH,
        needs_date_range=True,
        description=(
            "GraphQL query: orders。可用 query 篩選字串＋updated_at 做增量同步，"
            "巢狀含 lineItems/fulfillments/fulfillmentOrders/shippingAddress。"
            "⚠️預設僅回最近60天訂單，需完整歷史須另外在 Partner Dashboard 申請 read_all_orders scope。"
        ),
    ),
    ApiFunction(
        "shopify_node_query", "依全域ID查詢單一物件", "訂單相關", "POST", SHOPIFY_GRAPHQL_PATH,
        description="GraphQL query: node(id)。用途例如輪詢 shippingLabelPurchase 非同步結果。",
    ),
    # 商品與庫存相關
    ApiFunction(
        "shopify_products_query", "商品查詢（含游標分頁）", "商品與庫存相關", "POST", SHOPIFY_GRAPHQL_PATH,
        implemented=True,
        description=(
            "GraphQL query: products。可用 SKU 精準查（sku:）、狀態篩選（ACTIVE/ARCHIVED/DRAFT）、"
            "關鍵字（比對標題等欄位），每個商品的 variants 展開成一列一個 SKU。"
            "api_sync/ui/handlers.py: shopify_products_query"
        ),
    ),
    ApiFunction(
        "shopify_product_query", "查詢單一商品", "商品與庫存相關", "POST", SHOPIFY_GRAPHQL_PATH,
        description="GraphQL query: product(id)。",
    ),
    ApiFunction(
        "shopify_product_set", "建立/更新商品（Full-state upsert）", "商品與庫存相關", "POST", SHOPIFY_GRAPHQL_PATH,
        description=(
            "⚠️GraphQL mutation: productSet。未列在 list 欄位（例如 variants 清單）裡的既有項目"
            "可能被視為要刪除，動工前必須先確認同步策略是 full-state replace 還是 partial update。"
        ),
    ),
    ApiFunction(
        "shopify_product_variants_bulk_create", "批次新增商品規格(variant)", "商品與庫存相關", "POST",
        SHOPIFY_GRAPHQL_PATH, description="GraphQL mutation: productVariantsBulkCreate。",
    ),
    ApiFunction(
        "shopify_product_variants_bulk_update", "批次更新商品規格(variant)", "商品與庫存相關", "POST",
        SHOPIFY_GRAPHQL_PATH, description="GraphQL mutation: productVariantsBulkUpdate。",
    ),
    ApiFunction(
        "shopify_inventory_set_quantities", "設定庫存數量", "商品與庫存相關", "POST", SHOPIFY_GRAPHQL_PATH,
        description="⚠️會直接覆寫庫存數量，無法復原。GraphQL mutation: inventorySetQuantities。",
    ),
    # 出貨與物流相關
    ApiFunction(
        "shopify_fulfillment_create", "建立出貨(fulfillment)", "出貨與物流相關", "POST", SHOPIFY_GRAPHQL_PATH,
        description="⚠️會將訂單（或部分品項）標記為已出貨，無法復原。GraphQL mutation: fulfillmentCreate。",
    ),
    ApiFunction(
        "shopify_fulfillment_tracking_update", "更新出貨追蹤資訊", "出貨與物流相關", "POST", SHOPIFY_GRAPHQL_PATH,
        description="GraphQL mutation: fulfillmentTrackingInfoUpdate。",
    ),
    ApiFunction(
        "shopify_shipping_label_purchase", "購買 Shopify Shipping 寄件標籤", "出貨與物流相關", "POST",
        SHOPIFY_GRAPHQL_PATH,
        description=(
            "⚠️會實際扣款購買物流標籤，無法復原。GraphQL mutation: shippingLabelPurchase（2026-07 新增）。"
            "需要 write_orders ＋ 對應 fulfillment order write scope ＋ 使用者具 buy_shipping_labels 權限 ＋ "
            "店鋪已接受 Shopify Shipping 條款；FedEx 不支援此功能，需先確認店鋪是否可用 Shopify Shipping。"
        ),
    ),
    ApiFunction(
        "shopify_shipping_label_query", "查詢已存在的寄件標籤", "出貨與物流相關", "POST", SHOPIFY_GRAPHQL_PATH,
        description="唯讀，不異動狀態。GraphQL query: shippingLabel(id)，含 shippingDocuments.url 可下載檔案。",
    ),
    # Webhook 相關
    ApiFunction(
        "shopify_webhook_subscription_create", "建立 Webhook 訂閱", "Webhook相關", "POST", SHOPIFY_GRAPHQL_PATH,
        description=(
            "GraphQL mutation: webhookSubscriptionCreate。建議訂閱 orders/create、orders/updated、"
            "orders/fulfilled、orders/cancelled、products/create、products/update、products/delete、"
            "inventory_levels/update、fulfillment_orders/* 等主題。⚠️官方提醒送達與順序都不保證，"
            "仍須搭配定期 reconciliation（用 updated_at 補漏）。"
        ),
    ),
    # 批次作業
    ApiFunction(
        "shopify_bulk_operation_run_query", "批次匯出大量資料(Bulk Operation)", "批次作業", "POST",
        SHOPIFY_GRAPHQL_PATH,
        description=(
            "適合首次匯入全部商品/大量歷史訂單/定期完整校對，不適合即時小更新或需要立即結果的流程。"
            "詳細語法見官方「Bulk operation queries」頁面（doc_ref 已下載原始 HTML）。"
        ),
    ),
]


def categories_for(functions: list[ApiFunction]) -> list[str]:
    seen = []
    for fn in functions:
        if fn.category not in seen:
            seen.append(fn.category)
    return seen
