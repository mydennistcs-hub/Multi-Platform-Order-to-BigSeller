"""momo店+ Vendor API 用戶端：Bearer Token + 訂單查詢。"""

import sys


def _ensure(pkg, mod=None):
    import importlib
    import subprocess

    try:
        importlib.import_module(mod or pkg)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])


_ensure("requests")
import requests  # noqa: E402

from api_sync.config import MomoConfig


class MomoClient:
    def __init__(self, config: MomoConfig = None):
        self.config = config or MomoConfig()

    @classmethod
    def from_account(cls, account):
        return cls(MomoConfig.from_account(account))

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.config.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        }

    def _post(self, path: str, body: dict) -> requests.Response:
        url = f"{self.config.base_url}{path}"
        return requests.post(url, headers=self._headers(), json=body, timeout=15)

    def query_orders(
        self,
        from_date: str,
        to_date: str,
        query_date_type: str = "OrderDate",
        delivery_type: str = "All",
        order_status: str = "All",
        page_index: int = 1,
        max_per_page: int = 100,
        list_order_no: list = None,
        store_delivery_type: str = "All",
        entp_goods_no: str = None,
    ) -> requests.Response:
        """查詢訂單。fromDate/toDate 格式 yyyy/MM/dd，區間最長 30 天。

        storeDeliveryType：文件標示非必填，但實測 deliveryType=All 或 Store
        時，momo 端仍會驗證此欄位不可為 null，故預設一律帶 "All"。
        """
        body = {
            "pageIndex": page_index,
            "maxPerPage": max_per_page,
            "queryDateType": query_date_type,
            "fromDate": from_date,
            "toDate": to_date,
            "deliveryType": delivery_type,
            "storeDeliveryType": store_delivery_type,
            "orderStatus": order_status,
        }
        if list_order_no:
            body["listOrderNo"] = list_order_no
        # entpGoodsNo（商品原廠編號）是 OrderQuery 原生支援的選填篩選條件，官方註明「支援模糊查詢」
        # ——見 doc_ref/mo店+ API 串接的資料/20241007001.pdf 第 54 頁請求欄位表。
        # 同一區塊還有 goodsNo / goodsName / customerName 也支援模糊查詢，日後要加篩選可比照。
        if entp_goods_no:
            body["entpGoodsNo"] = entp_goods_no

        return self._post("/VendorApi/OrderQuery", body)

    def query_goods(
        self,
        query_method: str = "SaleType",
        sale_status: str = "StartSelling",
        page_index: int = 1,
        max_per_page: int = 100,
        apply_date: str = None,
        list_goods: list = None,
    ) -> requests.Response:
        """商品查詢。queryMethod=All 或 Price 時，applyDate 為必填（格式 yyyy-MM-dd HH:mm:ss）。"""
        from datetime import datetime

        body = {
            "queryMethod": query_method,
            "saleStatus": sale_status,
            "pageIndex": page_index,
            "maxPerPage": max_per_page,
        }
        if query_method in ("All", "Price"):
            body["applyDate"] = apply_date or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if list_goods:
            body["listGoods"] = list_goods

        return self._post("/VendorApi/GoodsQueryByMethod", body)

    # 出貨確認：把訂單標記為已出貨，momo 當場產生寄件單（超商回 base64，第三方物流回下載網址）。
    # 這是會異動訂單狀態、無法復原的動作，呼叫前一定要在 UI 層跟使用者做二次確認。
    def confirm_third_party_delivery(
        self, order_list: list, delivery_status: str = "Shipped", delivery_note: str = "可出貨", new_box_yn: str = "1"
    ) -> requests.Response:
        """order_list: [{"orderNo":..., "orderSeq":...}, ...]，回應含 printLabel/printDetail/printAll（下載網址）。"""
        body = {
            "listItem": [
                {
                    "newBoxYn": new_box_yn,
                    "deliveryStatus": delivery_status,
                    "deliveryNote": delivery_note,
                    "orderList": order_list,
                }
            ]
        }
        return self._post("/VendorApi/OrderShippingStatusConfirmThirdPartyDelivery", body)

    def confirm_seven_store_delivery(
        self, order_list: list, dely_gb: str = "21", delivery_status: str = "Shipped",
        delivery_note: str = "可出貨", new_box_yn: str = "1",
    ) -> requests.Response:
        """dely_gb: 21 倉到店／22 店到店。回應含 printLable/printDetail（base64）。"""
        body = {
            "delyGb": dely_gb,
            "listItem": [
                {
                    "newBoxYn": new_box_yn,
                    "deliveryStatus": delivery_status,
                    "deliveryNote": delivery_note,
                    "orderList": order_list,
                }
            ],
        }
        return self._post("/VendorApi/OrderShippingStatusConfirmSevenStoreDelivery", body)

    def confirm_family_store_delivery(
        self, order_list: list, dely_gb: str = "29", delivery_status: str = "Shipped",
        delivery_note: str = "可出貨", new_box_yn: str = "1",
    ) -> requests.Response:
        """dely_gb: 29 常溫店到店／27 常溫倉到店／24 冷凍店到店／23 冷凍倉到店。回應含 printLable/printDetail（base64）。"""
        body = {
            "delyGb": dely_gb,
            "listItem": [
                {
                    "newBoxYn": new_box_yn,
                    "deliveryStatus": delivery_status,
                    "deliveryNote": delivery_note,
                    "orderList": order_list,
                }
            ],
        }
        return self._post("/VendorApi/OrderShippingStatusConfirmFamilyStoreDelivery", body)

    # 重印標籤：訂單已經出貨過，只是要補印寄件單，不會再次異動訂單狀態，屬於安全的唯讀動作。
    def reprint_third_party_label(self, order_list: list) -> requests.Response:
        body = {"listItem": [{"orderList": order_list}]}
        return self._post("/VendorApi/OrderShippingThirdPartyPrintLabel", body)

    def reprint_seven_store_label(self, order_list: list, dely_gb: str = "21") -> requests.Response:
        body = {"listItem": [{"delyGb": dely_gb, "orderList": order_list}]}
        return self._post("/VendorApi/OrderShippingSevenStorePrintLabel", body)

    def reprint_family_store_label(self, order_list: list, dely_gb: str = "29") -> requests.Response:
        body = {"listItem": [{"delyGb": dely_gb, "orderList": order_list}]}
        return self._post("/VendorApi/OrderShippingFamilyStorePrintLabel", body)
