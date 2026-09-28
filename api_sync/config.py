"""
統一從 .env / 系統環境變數讀取 momo、Coupang 的 API 憑證。

憑證只能來自環境變數，程式碼裡永遠不寫死任何 key/secret/token。
執行機器上把 .env.example 複製成 .env 並填值即可（.env 已在 .gitignore）。
"""

import os
import sys


def _ensure(pkg, mod=None):
    import importlib
    import subprocess

    try:
        importlib.import_module(mod or pkg)
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])


_ensure("python-dotenv", "dotenv")
from dotenv import load_dotenv  # noqa: E402

from api_sync.app_paths import app_dir  # noqa: E402

load_dotenv(app_dir() / ".env")


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"缺少環境變數 {name}，請在 .env（複製自 .env.example）或系統環境變數中設定"
        )
    return value


class CoupangConfig:
    def __init__(self, vendor_id=None, access_key=None, secret_key=None, base_url=None, market=None):
        self.vendor_id = vendor_id or _require("COUPANG_VENDOR_ID")
        self.access_key = access_key or _require("COUPANG_ACCESS_KEY")
        self.secret_key = secret_key or _require("COUPANG_SECRET_KEY")
        self.base_url = base_url or os.environ.get("COUPANG_BASE_URL", "https://api-gateway.coupang.com")
        self.market = market or os.environ.get("COUPANG_MARKET", "TW")

    @classmethod
    def from_account(cls, account):
        c = account.credentials
        return cls(vendor_id=c.get("vendor_id"), access_key=c.get("access_key"), secret_key=c.get("secret_key"))


class MomoConfig:
    def __init__(self, token=None, base_url=None):
        self.token = token or _require("MOMO_TOKEN")
        self.base_url = base_url or os.environ.get("MOMO_BASE_URL", "https://api3p.momo.com.tw")

    @classmethod
    def from_account(cls, account):
        return cls(token=account.credentials.get("token"))


class ShopifyConfig:
    def __init__(self, store_domain=None, access_token=None, api_version=None):
        self.store_domain = store_domain or _require("SHOPIFY_STORE_DOMAIN")
        self.access_token = access_token or _require("SHOPIFY_ACCESS_TOKEN")
        self.api_version = api_version or os.environ.get("SHOPIFY_API_VERSION", "2026-07")

    @classmethod
    def from_account(cls, account):
        c = account.credentials
        return cls(store_domain=c.get("store_domain"), access_token=c.get("access_token"))
