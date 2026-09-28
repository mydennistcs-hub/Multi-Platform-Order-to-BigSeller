"""跨平台、跨帳戶共用的資料結構。

一個「帳戶」= 一家公司在某個平台上的一個店鋪（例如：格魯維爾 + momo）。
一張「正規化訂單」= 不管來源是 momo 或 Coupang，轉換後都長一樣，方便後續
統一寫進 BigSeller Excel、或未來接其他平台（Shopify 等）時沿用同一套邏輯。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class Account:
    id: str  # 例如 "Growell_momo"，對應 accounts.json 裡的 id
    company: str  # 格魯維爾 / 丹尼書
    tax_id: str  # 統一編號
    platform: str  # momo / coupang / shopify ...
    credentials: dict = field(default_factory=dict)
    expected_ip: Optional[str] = None  # 此帳戶登記在平台白名單裡的固定 IP
    # Shopify OAuth 一次性換 token 用的 App 憑證，跟 credentials 分開放：
    # has_credentials 只該反映「能不能呼叫 API」（store_domain+access_token 夠了），
    # client_id/secret 只有要重新走一次 OAuth 換 token 時才需要，不該卡住日常 API 呼叫。
    oauth_client_id: Optional[str] = None
    oauth_client_secret: Optional[str] = None

    @property
    def label(self) -> str:
        return f"{self.company} {self.platform}"

    @property
    def has_credentials(self) -> bool:
        return bool(self.credentials) and all(str(v).strip() for v in self.credentials.values())


@dataclass
class OrderItem:
    sku: str
    product_name: str
    quantity: int
    unit_price: float
    spec: Optional[str] = None  # 規格/選項，例如顏色、尺寸
    raw: dict = field(default_factory=dict)  # 保留該品項在原始平台回應中的原始資料


@dataclass
class NormalizedOrder:
    platform: str  # momo / coupang / shopify ...
    company: str  # 格魯維爾 / 丹尼書
    order_no: str
    order_date: Optional[datetime]
    status: str
    recipient_name: Optional[str] = None
    recipient_address: Optional[str] = None
    logistics_company: Optional[str] = None
    tracking_no: Optional[str] = None
    items: list[OrderItem] = field(default_factory=list)
    raw: Any = None  # 保留該筆訂單在原始平台回應中的原始資料，方便除錯與日後補欄位
