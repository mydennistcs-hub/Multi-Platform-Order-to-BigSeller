"""
Shopify 一次性 OAuth 授權碼流程：換取可長期使用的 Admin API access token。

背景：新版 Shopify Dev Dashboard 建立的 App，不管是開發者後台還是商店後台的
「App 詳細資訊」頁，都不會再像舊版「自訂應用程式」一樣直接顯示一串固定的
access token 讓你複製。「App 自動化權杖」是給 Shopify CLI 在 CI/CD 環境登入用
的，不是給呼叫 Admin API 用（實測會被拒絕，HTTP 401）。要拿到真正能放進
`X-Shopify-Access-Token` header 呼叫 Admin GraphQL API 的 access token，
目前確認唯一路徑是走一次標準 OAuth Authorization Code Grant——這支程式就是
自動化這個流程：印出授權網址、你在瀏覽器用商店擁有人帳號登入按同意、程式接住
回呼的 code、換成 access_token，直接寫回 accounts.json（不印在畫面上）。

執行前必做：
  到 Dev Dashboard（dev.shopify.com）→ 你的 App → 設定/組態(Configuration)
  找「允許的重新導向網址 (Allowed redirection URL(s))」，加入：
      http://localhost:8765/callback
  （沒加這個，Shopify 會拒絕整個授權流程，回呼不會成功）。

用法：
  python shopify_oauth_helper.py <account_id>
  例如：python shopify_oauth_helper.py awesome_po_shopify
  Client ID / Client Secret 優先讀 accounts.json 該帳戶的 oauth_client_id /
  oauth_client_secret（跟 credentials 分開放，先手動貼進去就不用每次重打）；
  沒填的話才會互動輸入，Client Secret 用 getpass 不會顯示在畫面/歷史紀錄。
"""

import argparse
import getpass
import http.server
import json
import threading
import urllib.parse
import webbrowser

import requests

from api_sync.accounts import ACCOUNTS_FILE, get_account

REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"

# 最小權限原則：先只要訂單/商品/庫存/發貨地讀取權限即可涵蓋查詢用途，
# 之後真的要寫入/出貨再另外重跑一次要更大的 scopes。
DEFAULT_SCOPES = "read_orders,read_products,read_inventory,read_locations"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("account_id", help="accounts.json 內的帳戶 id，例如 awesome_po_shopify")
    parser.add_argument("--scopes", default=DEFAULT_SCOPES)
    args = parser.parse_args()

    account = get_account(args.account_id)
    store_domain = account.credentials.get("store_domain")
    if not store_domain:
        raise SystemExit(f"帳戶 {args.account_id} 尚未設定 credentials.store_domain")

    # 先看 accounts.json 裡有沒有先存好 oauth_client_id/oauth_client_secret，沒有才互動輸入。
    client_id = account.oauth_client_id or input("用戶端ID (Client ID)：").strip()
    client_secret = account.oauth_client_secret or getpass.getpass(
        "用戶端密碼 (Client Secret，輸入時不會顯示)："
    ).strip()
    if not client_id or not client_secret:
        raise SystemExit("Client ID / Client Secret 不能空白")

    code_holder = {}
    got_request = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(qs)
            if "code" in params:
                code_holder["code"] = params["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("授權成功，可以關閉這個分頁，回終端機看結果。".encode("utf-8"))
            else:
                code_holder["error"] = qs
                self.send_response(400)
                self.end_headers()
            got_request.set()

        def log_message(self, format, *a):  # noqa: A002 — 不印 request log，避免 query string 留在終端機捲動紀錄
            pass

    httpd = http.server.HTTPServer(("localhost", REDIRECT_PORT), Handler)
    server_thread = threading.Thread(target=httpd.handle_request, daemon=True)
    server_thread.start()

    auth_url = f"https://{store_domain}/admin/oauth/authorize?" + urllib.parse.urlencode(
        {"client_id": client_id, "scope": args.scopes, "redirect_uri": REDIRECT_URI}
    )
    print("\n請在瀏覽器開啟以下網址（用商店擁有人帳號登入並按同意）：\n")
    print(auth_url)
    print(f"\n等待授權回呼中（localhost:{REDIRECT_PORT}，5 分鐘內完成）...")
    webbrowser.open(auth_url)

    got_request.wait(timeout=300)
    server_thread.join(timeout=5)

    code = code_holder.get("code")
    if not code:
        raise SystemExit(
            "沒有收到授權碼，請確認 Dev Dashboard 的「允許的重新導向網址」是否已加入 " + REDIRECT_URI
            + f"\n（回呼收到的內容：{code_holder.get('error')}）"
        )

    resp = requests.post(
        f"https://{store_domain}/admin/oauth/access_token",
        json={"client_id": client_id, "client_secret": client_secret, "code": code},
        timeout=15,
    )
    if resp.status_code != 200:
        raise SystemExit(f"換取 access token 失敗：HTTP {resp.status_code} {resp.text[:300]}")

    token_data = resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise SystemExit(f"回應內沒有 access_token：{token_data}")

    # Shopify 傳統文件說 offline access token 不會過期，但不同管道給的說法不一致，
    # 用回應裡實際有沒有 expires_in/refresh_token 這兩個欄位來判斷，不要用猜的。
    expires_in = token_data.get("expires_in")
    refresh_token = token_data.get("refresh_token")

    data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    for item in data["accounts"]:
        if item["id"] == args.account_id:
            item["credentials"]["access_token"] = access_token
            if refresh_token:
                item["credentials"]["refresh_token"] = refresh_token
            if expires_in:
                item["credentials"]["expires_in"] = expires_in
            break
    else:
        raise SystemExit(f"accounts.json 內找不到 id={args.account_id}（換到的 token 沒有寫入，請自行手動貼上）")
    ACCOUNTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n成功！access token 已直接寫入 accounts.json（帳戶 {args.account_id}），沒有印在畫面上。")
    if expires_in or refresh_token:
        print(
            f"⚠️ 回應內帶了 expires_in={expires_in!r} / refresh_token={'有' if refresh_token else '無'}，"
            "代表這組 token 確實會過期，需要之後補寫自動 refresh 邏輯（先記錄下來，還沒實作）。"
        )
    else:
        print("回應內沒有 expires_in/refresh_token 欄位，符合 Shopify 傳統 offline token 不過期的說法。")
    print(f"接下來可以執行: python test_shopify_api.py {args.account_id}")


if __name__ == "__main__":
    main()
