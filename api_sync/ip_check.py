"""目前對外 IP 查詢，供 UI 的「IP 檢查」分頁使用。"""

import json
import urllib.request


def fetch_current_ip(timeout: int = 10) -> dict:
    """回傳 {"ip", "city", "region", "country", "org"}，查詢失敗時丟出例外。"""
    with urllib.request.urlopen("https://ipinfo.io/json", timeout=timeout) as resp:
        return json.loads(resp.read().decode())
