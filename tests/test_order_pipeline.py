import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import openpyxl

import converter
from api_sync.ui.excel_export import export_coupang_order_excel, export_momo_order_excel
from api_sync.ui import handlers
from api_sync.ui.handlers import build_coupang_official_row, build_momo_official_row


class OrderPipelineTests(unittest.TestCase):
    def test_store_names_match_current_bigseller_shops(self):
        self.assertEqual(converter.MO_STORE, "mo店+")
        self.assertEqual(converter.COUPANG_STORE, "酷澎 coupang")

    def test_coupang_discount_is_rate_plus_invoice_fee_per_order(self):
        # 單品：599 → round(599×14.5%)＋2＝89
        single = {("Coupang", "A", "x"): {"source": "Coupang", "order_no": "A", "price": 599, "qty": 1}}
        self.assertEqual(converter._coupang_order_discounts(single), {("Coupang", "A", "x"): 89})
        # 多 SKU：599×2＋149＝1347 → round(195.315)＋2＝197，依小計分攤、尾差放最後一列；mo店+ 不受影響
        multi = {
            ("Coupang", "B", "x"): {"source": "Coupang", "order_no": "B", "price": 599, "qty": 2},
            ("Coupang", "B", "y"): {"source": "Coupang", "order_no": "B", "price": 149, "qty": 1},
            ("mo店+", "C", "z"): {"source": "mo店+", "order_no": "C", "price": 100, "qty": 1},
        }
        result = converter._coupang_order_discounts(multi)
        self.assertEqual(result[("Coupang", "B", "x")] + result[("Coupang", "B", "y")], 197)
        self.assertEqual(result[("Coupang", "B", "x")], 175)
        self.assertNotIn(("mo店+", "C", "z"), result)

    def test_coupang_official_row_uses_available_api_fields(self):
        row = {
            "訂單編號": "ORDER1",
            "合併配送號碼": "BOX1",
            "物流商": "新竹物流",
            "運單號": "TRACK1",
            "是否為分批出貨": False,
            "下單時間": "2026-09-28T10:20:30+08:00",
            "estimatedShippingDate": "2026-09-29+08:00",
            "商品名稱": "商品 A",
            "賣家商品品項名稱": "1 入",
            "商品名稱(vendorItemName)": "商品 A, 1 入",
            "productId": "PRODUCT1",
            "單品ID": "ITEM1",
            "firstSellerProductItemName": "1 入",
            "賣家SKU": "SKU1",
            "數量": 2,
            "訂購人": "王小明",
            "收件人安心號碼": "0500000000",
            "收件郵遞區號": "100001",
            "收件地址": "測試地址",
            "包裹列印訊息": "門口",
            "deliveryChargeTypeName": "free",
            "_sales_price_units": 599,
            "_shipping_price_units": 0,
        }

        result = build_coupang_official_row(row, sequence=1)

        self.assertEqual(result["編號"], 1)
        self.assertEqual(result["是否分批配送"], "不支持分箱")
        self.assertEqual(result["訂購時預計發貨日期"], "2026-09-29")
        self.assertEqual(result["訂購日期"], "2026-09-28 10:20:30")
        self.assertEqual(result["註冊商品名稱"], "商品 A")
        self.assertEqual(result["註冊選項名稱"], "1 入")
        self.assertEqual(result["顯示產品名稱"], "商品 A, 1 入")
        self.assertEqual(result["首次註冊商品名稱/選項名稱"], "商品 A,1 入")
        self.assertEqual(result["銷售價格"], 599)
        self.assertEqual(result["選項價格"], 599)
        self.assertEqual(result["運費類型"], "免費")
        self.assertEqual(result["聯繫方式(安心碼)"], "0500000000")

    def test_momo_official_row_includes_available_amounts(self):
        result = build_momo_official_row(
            {"金額": 219, "_order_total_amount": 503},
        )
        self.assertEqual(result["訂單金額依品項"], 219)
        self.assertEqual(result["訂單金額加總"], 503)

    def test_momo_query_calculates_order_total_including_shipping_item(self):
        class Response:
            @staticmethod
            def json():
                return {
                    "listOrder": [
                        {
                            "orderNo": "MO1",
                            "receiverName": "測試收件人",
                            "listItem": [
                                {"orderSeq": "1", "goodsName": "商品 A", "orderAmount": 219, "quantity": 2},
                                {"orderSeq": "2", "goodsName": "運費", "orderAmount": 65, "quantity": 1},
                            ],
                        }
                    ]
                }

        class Client:
            @staticmethod
            def query_orders(**_kwargs):
                return Response()

        with patch.object(handlers.MomoClient, "from_account", return_value=Client()):
            _columns, rows = handlers.momo_order_query(object(), status="Printed")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["_order_total_amount"], 284)
        self.assertEqual(rows[0][handlers.MOMO_SHIPPING_FEE_COLUMN], 65)

    def test_coupang_api_response_populates_numeric_export_fields(self):
        data = {
            "data": [
                {
                    "orderId": 123,
                    "shipmentBoxId": 456,
                    "orderedAt": "2026-09-28T10:20:30+08:00",
                    "shippingPrice": {"units": 67, "currencyCode": "TWD"},
                    "splitShipping": False,
                    "receiver": {"name": "測試收件人", "addr1": "測試地址", "postCode": "100001"},
                    "orderer": {"name": "測試收件人"},
                    "orderItems": [
                        {
                            "vendorItemId": 789,
                            "sellerProductName": "商品 A",
                            "sellerProductItemName": "1 入",
                            "vendorItemName": "商品 A, 1 入",
                            "externalVendorSkuCode": "SKU1",
                            "shippingCount": 1,
                            "salesPrice": {"units": 229, "currencyCode": "TWD"},
                            "discountPrice": {"units": 229, "currencyCode": "TWD"},
                            "orderPrice": {"units": 229, "currencyCode": "TWD"},
                            "deliveryChargeTypeName": "not_free",
                            "estimatedShippingDate": "2026-09-29+08:00",
                        }
                    ],
                }
            ]
        }

        rows = handlers._coupang_orders_to_rows(data, "INSTRUCT")
        result = build_coupang_official_row(rows[0])

        self.assertEqual(result["銷售價格"], 229)
        self.assertEqual(result["選項價格"], 229)
        self.assertEqual(result["運費"], 67)
        self.assertEqual(result["運費類型"], "已付費")
        self.assertEqual(result["訂購時預計發貨日期"], "2026-09-29")

    def test_order_exports_keep_official_sheet_first_and_raw_sheet_second(self):
        rows = [{"訂單編號": "ORDER1", "額外欄位": "保留", "_internal": "不匯出"}]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name, exporter in (
                ("momo.xlsx", export_momo_order_excel),
                ("coupang.xlsx", export_coupang_order_excel),
            ):
                path = tmp_path / name
                exporter(str(path), rows)
                wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
                self.assertEqual(wb.sheetnames, ["Sheet", "API原始欄位"])
                raw = wb["API原始欄位"]
                headers = [cell.value for cell in raw[1]]
                self.assertIn("額外欄位", headers)
                self.assertNotIn("_internal", headers)
                wb.close()

    def test_converter_writes_both_current_store_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mo_path = tmp_path / "mo.xlsx"
            coupang_path = tmp_path / "coupang.xlsx"
            template_path = tmp_path / "template.xlsx"

            self._write_source(
                mo_path,
                [
                    "訂單編號", "訂單狀態", "轉單日", "商品原廠編號", "數量", "收件人姓名",
                    "收件人地址", "物流商", "物流單號", "商品售價",
                ],
                ["MO1", "已印單", "2026-09-28 10:00:00", "SKU-M", 1, "測試收件人", "測試地址", "新竹物流", "MTRACK", 100],
            )
            self._write_source(
                coupang_path,
                ["訂單編號", "快遞公司", "寄件單號", "訂購日期", "公司商品代碼", "數量", "選項價格", "訂購人姓名", "收件人地址"],
                ["CP1", "新竹物流", "CTRACK", "2026-09-28 11:00:00", "SKU-C", 2, 200, "測試收件人", "測試地址"],
            )
            self._write_template(template_path)

            converter.convert_orders(
                str(mo_path), str(template_path), [], "", lambda _message: None, lambda _value: None,
                coupang_path=str(coupang_path),
            )

            wb = openpyxl.load_workbook(template_path, data_only=True, read_only=True)
            ws = wb.active
            headers = [cell.value for cell in ws[1]]
            store_col = headers.index("店铺") + 1
            self.assertEqual(ws.cell(5, store_col).value, "mo店+")
            self.assertEqual(ws.cell(6, store_col).value, "酷澎 coupang")
            wb.close()

    def test_two_sheet_api_exports_remain_converter_compatible(self):
        momo_rows = [
            {
                "訂單編號": "MO-API-1",
                "訂單編號(序號)": "1",
                "訂單狀態": "已印單",
                "處理時間": "2026-09-28 10:00:00",
                "商品原廠編號": "SKU-M",
                "數量": 1,
                "收件人": "測試收件人",
                "收件地址": "測試地址",
                "物流商": "新竹物流",
                "運單號": "MTRACK",
                "金額": 100,
                "_order_total_amount": 100,
                "未映射但需保留": "momo raw",
            }
        ]
        coupang_rows = [
            {
                "訂單編號": "CP-API-1",
                "合併配送號碼": "BOX1",
                "下單時間": "2026-09-28T11:00:00+08:00",
                "物流商": "新竹物流",
                "運單號": "CTRACK",
                "單品ID": "ITEM1",
                "賣家SKU": "SKU-C",
                "數量": 2,
                "訂購人": "測試收件人",
                "收件地址": "測試地址",
                "_sales_price_units": 200,
                "未映射但需保留": "coupang raw",
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mo_path = tmp_path / "momo_api.xlsx"
            coupang_path = tmp_path / "coupang_api.xlsx"
            template_path = tmp_path / "template.xlsx"
            export_momo_order_excel(str(mo_path), momo_rows)
            export_coupang_order_excel(str(coupang_path), coupang_rows)
            self._write_template(template_path)

            converter.convert_orders(
                str(mo_path), str(template_path), [], "", lambda _message: None, lambda _value: None,
                coupang_path=str(coupang_path),
            )

            wb = openpyxl.load_workbook(template_path, data_only=True, read_only=True)
            ws = wb.active
            headers = [cell.value for cell in ws[1]]
            store_col = headers.index("店铺") + 1
            self.assertEqual(ws.cell(5, store_col).value, "mo店+")
            self.assertEqual(ws.cell(6, store_col).value, "酷澎 coupang")
            wb.close()

    _MO_HEADERS_WITH_TAX = [
        "訂單編號", "訂單狀態", "轉單日", "商品原廠編號", "數量", "收件人姓名",
        "收件人地址", "物流商", "物流單號", "商品售價", "發票開立統編", "統編",
    ]

    def _convert_for_company(self, company: str, mo_tax_id: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        tmp_path = Path(tmp.name)
        mo_path = tmp_path / "mo.xlsx"
        coupang_path = tmp_path / "coupang.xlsx"
        template_path = tmp_path / "template.xlsx"
        self._write_source(
            mo_path, self._MO_HEADERS_WITH_TAX,
            ["MO1", "已印單", "2026-11-11 10:00:00", "0619", 1, "測試收件人", "測試地址",
             "7-11店到店", "MTRACK", 149, "", mo_tax_id],
        )
        self._write_source(
            coupang_path,
            ["訂單編號", "快遞公司", "寄件單號", "訂購日期", "公司商品代碼", "數量", "選項價格", "訂購人姓名", "收件人地址"],
            ["CP1", "新竹物流", "CTRACK", "2026-11-11 11:00:00", "SKU-C", 1, 200, "測試收件人", "測試地址"],
        )
        self._write_template(template_path)
        converter.convert_orders(
            str(mo_path), str(template_path), [], "", lambda _m: None, lambda _v: None,
            coupang_path=str(coupang_path), company=company,
        )
        wb = openpyxl.load_workbook(template_path, data_only=True)
        ws = wb.active
        headers = [cell.value for cell in ws[1]]
        col = {h: headers.index(h) + 1 for h in ("店铺", "发货仓库", "店铺SKU")}
        rows = [{h: ws.cell(r, c).value for h, c in col.items()} for r in (5, 6)]
        wb.close()
        return rows

    def test_dennis_su_orders_use_own_suffix_same_store_and_warehouse(self):
        mo, cp = self._convert_for_company("丹尼書", "90154390")
        self.assertEqual(mo["店铺SKU"], "0619-mo90154390")
        self.assertEqual(cp["店铺SKU"], "SKU-C-cou90154390")
        self.assertEqual(mo["店铺"], "mo店+")
        self.assertEqual(cp["店铺"], "酷澎 coupang")
        self.assertEqual(mo["发货仓库"], "樸翔初耘18號8樓 mo店+倉庫")
        self.assertEqual(cp["发货仓库"], "樸翔初耘18號8樓 Coupang倉庫")

    def test_growell_is_default_suffix(self):
        mo, cp = self._convert_for_company("格魯維爾", "94234570")
        self.assertEqual(mo["店铺SKU"], "0619-mo94234570")
        self.assertEqual(cp["店铺SKU"], "SKU-C-cou94234570")

    def test_mo_file_tax_id_must_match_selected_company(self):
        with self.assertRaisesRegex(ValueError, "不符"):
            self._convert_for_company("丹尼書", "94234570")

    @staticmethod
    def _write_source(path: Path, headers: list[str], values: list):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(headers)
        ws.append(values)
        wb.save(path)

    @staticmethod
    def _write_template(path: Path):
        headers = [
            "店铺", "订单号", "下单时间", "买家指定物流", "发货仓库", "客户编码", "收件人姓名",
            "收件人手机号", "邮政编号", "国区号", "收件人国家/地区", "收件人省地址", "收件人市地址",
            "收件人区地址", "详细地址", "买家留言", "支付方式", "转账方式", "转账账号", "定金",
            "卖家支付运费", "优惠", "物流名称", "运单号", "寄件人姓名", "寄件人电话号码", "寄件地址",
            "店铺SKU", "币种", "单价", "数量",
        ]
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(headers)
        for _ in range(3):
            ws.append([""] * len(headers))
        wb.save(path)


if __name__ == "__main__":
    unittest.main()
