"""修復舊版（xhtml2pdf 產出）的 Coupang 全家寄件單 PDF：黑色被挖成透明而看起來「模糊」。

背景（2026-08-23 查明）：
App 舊版是用 xhtml2pdf 把 Coupang 回傳的全家寄取貨單 HTML 轉成 PDF。轉出來的檔案裡，
整張標籤圖片（2615x4271）被附加了 `/Mask [0 0 0 0 0 0]` 這個 colour-key 遮罩，PDF 規格上
的意思是「RGB 等於純黑的像素一律視為透明」——於是條碼、黑底白字、粗框線這些真正是純黑的
部分整片被挖掉，只剩抗鋸齒的灰色邊緣，畫面上就是使用者看到的「模糊」。

**圖片本身是清楚的**（實測抽出來的原圖跟後台手動下載的那份逐像素同級），壞掉的只是嵌入
方式，所以把 `/Mask` 拿掉就能無損還原，不需要重新去 Coupang 下載一次寄件單。

App 目前的下載流程已改用 QtWebEngine 轉檔（見 `api_sync/qt_html_pdf.py`），不會再產生
這種檔案；這支腳本是給**已經存下來的舊檔**用的。

用法：
    python repair_invoice_pdf.py <pdf檔或資料夾> [<pdf檔或資料夾> ...]

原檔一律不覆蓋，修好的另存成 `原檔名_修復版.pdf`。
"""

import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter

SUFFIX = "_修復版"


def repair_pdf(path: Path) -> tuple[Path | None, int]:
    """回傳 (輸出路徑, 移除的遮罩數量)。沒有遮罩就不輸出檔案（回傳 (None, 0)）。"""
    reader = PdfReader(str(path))
    writer = PdfWriter()
    removed = 0
    for page in reader.pages:
        resources = page.get("/Resources") or {}
        xobjects = resources.get("/XObject")
        if xobjects:
            for obj in xobjects.get_object().values():
                target = obj.get_object()
                # /Mask 是陣列時才是 colour-key 遮罩（是 stream 時代表正常的點陣遮罩圖，不能動）
                if isinstance(target.get("/Mask"), list):
                    del target["/Mask"]
                    removed += 1
        writer.add_page(page)

    if removed == 0:
        return None, 0

    out_path = path.with_name(path.stem + SUFFIX + path.suffix)
    with open(out_path, "wb") as f:
        writer.write(f)
    return out_path, removed


def iter_targets(args):
    for arg in args:
        p = Path(arg)
        if p.is_dir():
            yield from sorted(x for x in p.glob("*.pdf") if SUFFIX not in x.stem)
        elif p.is_file():
            if p.stat().st_size == 0:  # 舊版轉檔失敗時會留下 0 byte 的空殼 PDF，直接略過
                print(f"[略過] {p.name} 是 0 byte 的空檔案")
                continue
            yield p
        else:
            print(f"[略過] 找不到：{p}")


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    any_fixed = False
    for pdf in iter_targets(argv):
        try:
            out, removed = repair_pdf(pdf)
        except Exception as e:  # noqa: BLE001 — 逐檔 best-effort，一份壞掉不影響其他份
            print(f"[錯誤] {pdf.name}：{e}")
            continue
        if out is None:
            print(f"[不需修復] {pdf.name}（沒有 colour-key 遮罩）")
        else:
            any_fixed = True
            print(f"[已修復] {pdf.name} → {out.name}（移除 {removed} 個遮罩）")
    if not any_fixed:
        print("沒有任何檔案需要修復。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
