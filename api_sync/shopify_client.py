"""Shopify Admin API 用戶端：GraphQL，單一 endpoint，靠 access token 認證。

跟 momo/Coupang 不同，Shopify Admin API 只有一個 endpoint
（/admin/api/{version}/graphql.json），不同功能靠 GraphQL query/mutation
名稱區分。呼叫端要同時檢查回應最外層的 errors（GraphQL 層級錯誤）跟每個
mutation 自己的 userErrors（業務邏輯錯誤），不能只看 HTTP 狀態碼。
"""

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

from api_sync.config import ShopifyConfig


class ShopifyClient:
    def __init__(self, config: ShopifyConfig = None):
        self.config = config or ShopifyConfig()

    @classmethod
    def from_account(cls, account):
        return cls(ShopifyConfig.from_account(account))

    def _headers(self) -> dict:
        return {
            "X-Shopify-Access-Token": self.config.access_token,
            "Content-Type": "application/json",
        }

    def graphql(self, query: str, variables: dict = None) -> requests.Response:
        url = f"https://{self.config.store_domain}/admin/api/{self.config.api_version}/graphql.json"
        body = {"query": query}
        if variables:
            body["variables"] = variables
        return requests.post(url, headers=self._headers(), json=body, timeout=15)

    def shop_info(self) -> requests.Response:
        """最小連通性測試：query { shop { name } }（shopify_api_agent_guide.md 建議的 smoke test）。"""
        return self.graphql("{ shop { name myshopifyDomain currencyCode ianaTimezone } }")
