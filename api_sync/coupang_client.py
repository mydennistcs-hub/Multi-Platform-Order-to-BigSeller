"""Coupang Open API 用戶端：HMAC-SHA256 簽章 + 訂單查詢。"""

import hashlib
import hmac
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode


def _ensure(pkg, mod=None):
    import importlib
    import subprocess

    try:
        importlib.import_module(mod or pkg)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])


_ensure("requests")
import requests  # noqa: E402

from api_sync.config import CoupangConfig

TAIPEI_TZ = timezone(timedelta(hours=8))


class CoupangClient:
    def __init__(self, config: CoupangConfig = None):
        self.config = config or CoupangConfig()

    @classmethod
    def from_account(cls, account):
        return cls(CoupangConfig.from_account(account))

    def _authorization(self, method: str, path: str, query_string: str) -> str:
        signed_date = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
        # message 組成順序、query_string 內容都必須跟實際送出的 request 一字不差
        message = f"{signed_date}{method}{path}{query_string}"
        signature = hmac.new(
            self.config.secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return (
            f"CEA algorithm=HmacSHA256, access-key={self.config.access_key}, "
            f"signed-date={signed_date}, signature={signature}"
        )

    def _headers(self, authorization: str) -> dict:
        return {
            "Authorization": authorization,
            "Content-Type": "application/json;charset=UTF-8",
            "X-Requested-By": self.config.vendor_id,
            "X-MARKET": self.config.market,
        }

    def _signed_request(
        self, method: str, path: str, query_params: list = None, json_body=None, timeout: int = 15
    ) -> requests.Response:
        # 簽章只吃 method+path+query_string，body 不參與簽章計算
        query_string = urlencode(query_params) if query_params else ""
        authorization = self._authorization(method, path, query_string)
        url = f"{self.config.base_url}{path}"
        if query_string:
            url += f"?{query_string}"
        kwargs = {"headers": self._headers(authorization), "timeout": timeout}
        if json_body is not None:
            kwargs["json"] = json_body
        return requests.request(method, url, **kwargs)

    def query_ordersheets(self, status: str = "ACCEPT", hours: int = 23) -> requests.Response:
        """查詢近 `hours` 小時內、指定狀態的訂單陣列（分鐘制查詢，官方限制最長24小時內）。"""
        now = datetime.now(TAIPEI_TZ)
        date_from = (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M") + "+08:00"
        date_to = now.strftime("%Y-%m-%dT%H:%M") + "+08:00"

        path = f"/v2/providers/openapi/apis/api/v5/vendors/{self.config.vendor_id}/ordersheets"
        query_params = [
            ("createdAtFrom", date_from),
            ("createdAtTo", date_to),
            ("searchType", "timeFrame"),
            ("status", status),
        ]
        return self._signed_request("GET", path, query_params)

    def query_ordersheets_by_day(
        self,
        status: str,
        date_from: str,
        date_to: str,
        max_per_page: int = 50,
        next_token: str = None,
    ) -> requests.Response:
        """按天分頁查詢訂單。date_from/date_to 格式 YYYY-MM-DD，官方限制最長查詢 31 天。"""
        path = f"/v2/providers/openapi/apis/api/v5/vendors/{self.config.vendor_id}/ordersheets"
        query_params = [
            ("createdAtFrom", f"{date_from}+08:00"),
            ("createdAtTo", f"{date_to}+08:00"),
            ("status", status),
            ("maxPerPage", max_per_page),
        ]
        if next_token:
            query_params.append(("nextToken", next_token))
        return self._signed_request("GET", path, query_params)

    def get_order_by_id(self, order_id: str) -> requests.Response:
        """依訂單號查單一訂單，回應結構跟 ordersheets 陣列查詢的單筆訂單物件相同。"""
        path = f"/v2/providers/openapi/apis/api/v5/vendors/{self.config.vendor_id}/{order_id}/ordersheets"
        return self._signed_request("GET", path)

    def query_products(
        self,
        status: str = "APPROVED",
        max_per_page: int = 50,
        next_token: str = None,
        seller_product_name: str = None,
    ) -> requests.Response:
        """查詢賣家商品清單（分頁）。status 常用值：APPROVED（已核准/上架）、IN_REVIEW（審核中）。
        seller_product_name：商品名稱關鍵字篩選，最多 20 字。
        """
        path = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
        query_params = [
            ("vendorId", self.config.vendor_id),
            ("status", status),
            ("maxPerPage", max_per_page),
        ]
        if seller_product_name:
            query_params.append(("sellerProductName", seller_product_name))
        if next_token:
            query_params.append(("nextToken", next_token))
        return self._signed_request("GET", path, query_params)

    def get_product_by_sku(self, external_vendor_sku_code: str) -> requests.Response:
        """依賣家自訂 SKU（externalVendorSkuCode）查商品資訊摘要。"""
        path = (
            "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
            f"/external-vendor-sku-codes/{external_vendor_sku_code}"
        )
        return self._signed_request("GET", path)

    # ---- 退貨地／發貨地清單查詢 ----
    # arrangeShipment 需要 returnCenterCode（超商）或 outboundShippingPlaceCode（宅配），
    # 這兩個代碼是 Coupang 內部代碼，賣家不會背，原本 UI 只給一個空白輸入框等使用者自己填，
    # 實務上根本填不出來（要跑去 Wing 後台翻）。這兩支就是用來把清單抓回來給使用者用選的。
    # 路徑取自 doc_ref/coupang API 串接的資料/coupang_open_api_tw_agent_pack.md 第 228/230 行與
    # 端點總表（第 324/326 行），不是自己猜的。

    def query_return_shipping_centers(self, page_num: int = 1, page_size: int = 50) -> requests.Response:
        """查詢本帳戶已建立的退貨地清單，回傳含 returnCenterCode（超商出貨要用）。
        官方文件（query-a-list-of-return-locations）pageSize 上限 50，這裡強制夾住，
        原本預設值 100 超過上限，實測會導致 Coupang 拒絕請求。"""
        path = f"/v2/providers/openapi/apis/api/v5/vendors/{self.config.vendor_id}/returnShippingCenters"
        query_params = [("pageNum", page_num), ("pageSize", min(page_size, 50))]
        return self._signed_request("GET", path, query_params)

    def query_outbound_shipping_places(self, page_num: int = 1, page_size: int = 50) -> requests.Response:
        """查詢本帳戶已建立的發貨地清單，回傳含 outboundShippingPlaceCode（宅配出貨要用，
        例如新竹物流 TWL_HCT／嘉里 TWL_KERRY 都需要指定從哪個發貨地讓物流來收件）。
        注意這支的 path 不含 vendorId，是 marketplace_openapi 那組。官方文件
        （query-a-shipping-location）pageSize 上限一樣是 50，這裡強制夾住，原本預設值 100
        超過上限——這是 2026-08-05 實測「查不到任何發貨地」誤判的根因之一，見 CLAUDE.md。"""
        path = "/v2/providers/marketplace_openapi/apis/api/v2/vendor/shipping-place/outbound"
        query_params = [("pageNum", page_num), ("pageSize", min(page_size, 50))]
        return self._signed_request("GET", path, query_params)

    def acknowledge_orders(self, shipment_box_ids: list) -> requests.Response:
        """訂單狀態變更為準備中：ACCEPT → INSTRUCT（Wing 後台「確認訂單」按鈕做的事）。
        arrangeShipment 要求訂單必須已經是 INSTRUCT，所以這支通常要先呼叫過一次。
        shipment_box_ids 最多一次 50 筆。這是會異動訂單狀態的寫入動作，UI 層要做二次確認。
        """
        path = f"/v2/providers/openapi/apis/api/v4/vendors/{self.config.vendor_id}/ordersheets/acknowledgement"
        body = {"vendorId": self.config.vendor_id, "shipmentBoxIds": shipment_box_ids}
        return self._signed_request("PATCH", path, json_body=body)

    # 台灣專屬：直接整合物流出貨安排 + 下載寄件單。這兩支都是「會異動訂單狀態」的寫入動作，
    # 不是單純查詢，呼叫前一定要在 UI 層跟使用者做二次確認。
    def arrange_shipment(
        self,
        shipment_box_id,
        delivery_company_code: str,
        return_center_code: str = None,
        outbound_shipping_place_code=None,
        remark: str = "",
    ) -> requests.Response:
        """把訂單從「商品準備中」轉成「待寄出」，momo/Coupang 當場配發 invoiceNumber（運單號）。
        CVS（TWL_FM/TWL_711）要帶 return_center_code；宅配（TWL_KERRY/TWL_HCT）要帶
        outbound_shipping_place_code。request body 是陣列，這裡固定一次只送一筆。
        """
        path = f"/v2/providers/openapi/apis/api/v1/vendors/{self.config.vendor_id}/orders/directIntegration/arrangeShipment"
        item = {
            "shipmentBoxId": shipment_box_id,
            "deliveryCompanyCode": delivery_company_code,
            "remark": remark,
        }
        if return_center_code:
            item["returnCenterCode"] = return_center_code
        if outbound_shipping_place_code:
            item["outboundShippingPlaceCode"] = outbound_shipping_place_code
        return self._signed_request("POST", path, json_body=[item])

    def download_invoices(
        self, delivery_company_code: str, shipment_box_id, invoice_number: str
    ) -> requests.Response:
        """下載真正可列印的寄件單檔案。回應不是 JSON，是檔案本體：
        TWL_KERRY/TWL_HCT 回 PDF（Content-Type: application/pdf），
        TWL_FM/TWL_711 回 HTML（Content-Type: text/html）。
        官方限制：訂單還在「付款完成」尚未安排出貨時查不到；運送完成 7 天後也會過期查不到。
        """
        path = f"/v2/providers/openapi/apis/api/v1/vendors/{self.config.vendor_id}/orders/directIntegration/downloadInvoices"
        body = {
            "deliveryCompanyCode": delivery_company_code,
            "invoicePrintDtoList": [{"shipmentBoxId": shipment_box_id, "invoiceNumber": invoice_number}],
        }
        return self._signed_request("POST", path, json_body=body)
