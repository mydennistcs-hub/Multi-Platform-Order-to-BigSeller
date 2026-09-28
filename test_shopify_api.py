"""
Shopify Admin API 連通性測試：query { shop { name } }。

用途：驗證 accounts.json 裡的 store_domain / access_token 是否正確、
「App 自動化權杖」是否有效。純讀取，不會異動任何資料。

執行前：accounts.json 內要有一筆 platform="shopify" 的帳戶，
credentials 填好 store_domain（例如 awesomepo.myshopify.com）與
access_token（Shopify 後台「設定→憑證」頁「App 自動化權杖」建立的那組）。

用法：
  python test_shopify_api.py [account_id]
  [account_id] 可省略，預設抓 accounts.json 內第一筆 platform="shopify" 的帳戶。
"""

import json
import sys

from api_sync.accounts import accounts_by_platform, get_account
from api_sync.shopify_client import ShopifyClient


def main():
    if len(sys.argv) > 1:
        account = get_account(sys.argv[1])
    else:
        accounts = accounts_by_platform("shopify")
        if not accounts:
            print("accounts.json 內找不到 platform=\"shopify\" 的帳戶，請先設定。")
            return
        account = accounts[0]

    print(f"帳戶: {account.id}（{account.label}）")
    if not account.has_credentials:
        print("這個帳戶的 credentials 還沒填齊（store_domain / access_token），請先在 accounts.json 補上。")
        return

    client = ShopifyClient.from_account(account)
    resp = client.shop_info()

    print(f"POST {resp.url}")
    print(f"HTTP {resp.status_code}")

    try:
        data = resp.json()
    except ValueError:
        print("回應不是 JSON：")
        print(resp.text[:2000])
        return

    print(json.dumps(data, ensure_ascii=False, indent=2))

    if resp.status_code == 200 and "errors" not in data:
        shop = (data.get("data") or {}).get("shop") or {}
        print(f"\n連線與 access token 驗證成功。店鋪名稱：{shop.get('name')}")
    elif resp.status_code == 401:
        print("\n401：access token 錯誤或已失效，回後台「App 自動化權杖」重新建立一組。")
    elif "errors" in data:
        print(f"\n回應內有 errors，請對照訊息內容排查：{data.get('errors')}")


if __name__ == "__main__":
    main()
