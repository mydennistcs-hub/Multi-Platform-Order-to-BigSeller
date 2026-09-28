"""
momo店+ Vendor API 連通性測試：查詢近 7 天訂單。

用途：驗證固定 IP 是否已在 momo A103 白名單生效、TOKEN 是否正確。
純讀取，不會異動任何訂單狀態。

執行前：
  1. 目前對外 IP 必須是已登記在 momo A103「IP位址申請/查詢」的那組固定 IP。
  2. 複製 .env.example 為 .env，填入 MOMO_TOKEN（後台「寄送Token」寄到信箱的那組）。

用法：
  python test_momo_api.py [orderStatus]
  [orderStatus] 可省略，預設 All；也可用 Printed / Shipping / DoneDelivery 等。
"""

import json
import sys
from datetime import datetime, timedelta

from api_sync.momo_client import MomoClient


def main():
    order_status = sys.argv[1] if len(sys.argv) > 1 else "All"

    today = datetime.now()
    from_date = (today - timedelta(days=7)).strftime("%Y/%m/%d")
    to_date = today.strftime("%Y/%m/%d")

    client = MomoClient()
    resp = client.query_orders(
        from_date=from_date,
        to_date=to_date,
        order_status=order_status,
        # 使用者目前只開通超商、第三方物流，未開通宅配
        delivery_type="All",
    )

    print(f"POST {resp.url}")
    print(f"查詢區間: {from_date} ~ {to_date}，orderStatus={order_status}\n")
    print(f"HTTP {resp.status_code}")

    try:
        data = resp.json()
    except ValueError:
        print("回應不是 JSON，以下是回應 headers（不含憑證，可以直接貼給我）：")
        for k, v in resp.headers.items():
            print(f"  {k}: {v}")
        print("\n回應內容：")
        print(resp.text[:2000])
        return

    print(json.dumps(data, ensure_ascii=False, indent=2))

    if resp.status_code == 200 and not data.get("errorMessage"):
        total = data.get("totalOrders", "?")
        print(f"\n連線與 TOKEN 驗證成功，共 {total} 筆符合條件的訂單（0 筆也正常）。")
    elif resp.status_code in (401, 403):
        print("\n401/403：多半是固定 IP 還沒生效，或跟後台登記的 IP 不一致，先確認目前對外 IP。")
    elif data.get("errorMessage"):
        print(f"\n回應內有 errorMessage，請對照訊息內容排查：{data.get('errorMessage')}")


if __name__ == "__main__":
    main()
