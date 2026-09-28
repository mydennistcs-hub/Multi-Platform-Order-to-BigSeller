"""多帳戶設定：從 accounts.json 讀取所有平台帳戶。

同一間公司在同一個平台只會有一個帳戶條目；一間公司要開 momo + Coupang，
就是兩筆 id 不同、company 相同的條目。accounts.json 不進 git（見
.gitignore），複製 accounts.example.json 改名為 accounts.json 後填入
實際憑證即可。
"""

import json

from api_sync.app_paths import app_dir
from api_sync.models import Account

ACCOUNTS_FILE = app_dir() / "accounts.json"


def load_accounts() -> list[Account]:
    if not ACCOUNTS_FILE.exists():
        raise RuntimeError(
            f"找不到 {ACCOUNTS_FILE}，請複製 accounts.example.json 為 accounts.json 並填入帳戶資料"
        )
    data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
    return [Account(**item) for item in data["accounts"]]


def get_account(account_id: str) -> Account:
    for acc in load_accounts():
        if acc.id == account_id:
            return acc
    raise KeyError(f"找不到帳戶 id={account_id}")


def accounts_by_platform(platform: str) -> list[Account]:
    return [a for a in load_accounts() if a.platform == platform]


def accounts_by_company(company: str) -> list[Account]:
    return [a for a in load_accounts() if a.company == company]
