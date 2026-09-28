"""
單純用來測試「這支程式」目前對外連線用的是哪一個 IP。

用途：加進 Surfshark Bypasser 的 App 清單裡（不管是「繞過VPN」還是
「透過VPN選取路由」清單都可以測），用來驗證針對這支程式的規則有沒有生效，
不用再開瀏覽器去 whatismyip.com 手動比對。

雙擊執行即可，結果會停在畫面上直到按 Enter 才關閉。
"""

import json
import os
import sys
import urllib.request

if sys.platform == "win32":
    os.system("chcp 65001 >nul")
    sys.stdout.reconfigure(encoding="utf-8")


def fetch(url):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode())


def main():
    print("查詢中...\n")
    try:
        data = fetch("https://ipinfo.io/json")
        print("=" * 50)
        print(f"目前對外 IP : {data.get('ip', '?')}")
        print(f"城市       : {data.get('city', '?')}")
        print(f"地區       : {data.get('region', '?')}")
        print(f"國家       : {data.get('country', '?')}")
        print(f"ISP/組織   : {data.get('org', '?')}")
        print("=" * 50)
    except Exception as e:
        print(f"查詢失敗（{e}），改用備援服務...")
        try:
            ip = fetch("https://api.ipify.org?format=json").get("ip", "?")
            print(f"目前對外 IP : {ip}")
        except Exception as e2:
            print(f"備援服務也失敗：{e2}")
            print("（如果是連線逾時，也可能代表這支程式目前完全連不到網路）")

    input("\n按 Enter 鍵結束...")


if __name__ == "__main__":
    main()
