"""
Coupang Open API 連通性測試：查詢近期訂單陣列（分鐘制）。

用途：驗證固定 IP 是否已在 Coupang Wing 白名單生效、accessKey/secretKey 與
HMAC 簽章邏輯是否正確。純讀取，不會異動任何訂單狀態。

執行前：
  1. 目前對外 IP 必須是已登記在 Coupang Wing OpenAPI Key 的那組固定 IP。
  2. 複製 .env.example 為 .env，填入 COUPANG_VENDOR_ID / COUPANG_ACCESS_KEY /
     COUPANG_SECRET_KEY。

用法：
  python test_coupang_api.py [status]
  [status] 可省略，預設 ACCEPT；查不到資料可換
  INSTRUCT / DEPARTURE / DELIVERING / FINAL_DELIVERY 再試。
"""

import json
import sys

from api_sync.coupang_client import CoupangClient


def main():
    status = sys.argv[1] if len(sys.argv) > 1 else "ACCEPT"

    client = CoupangClient()
    resp = client.query_ordersheets(status=status)

    print(f"GET {resp.url}")
    print(f"status={status}\n")
    print(f"HTTP {resp.status_code}")

    try:
        data = resp.json()
    except ValueError:
        print("回應不是 JSON：")
        print(resp.text[:2000])
        return

    print(json.dumps(data, ensure_ascii=False, indent=2))

    if resp.status_code == 200:
        print("\n連線與簽章驗證成功（0 筆資料是正常的，代表這個狀態/時間區間內剛好沒有訂單）。")
    elif resp.status_code == 403:
        print("\n403：多半是固定 IP 還沒生效，或跟 Wing 登記的 IP 不一致，先確認目前對外 IP。")
    elif resp.status_code == 401:
        print("\n401：多半是 accessKey/secretKey 錯誤，或簽章時間與系統時間有落差，先確認系統時間是否正確。")


if __name__ == "__main__":
    main()
