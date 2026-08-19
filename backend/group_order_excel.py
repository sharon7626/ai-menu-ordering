"""以 Python 內建模組產生團購訂單 Excel（XLSX）檔。"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree as ET


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
ET.register_namespace("", MAIN_NS)
ET.register_namespace("r", REL_NS)


def _column_name(number: int) -> str:
    name = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _string_cell(row: ET.Element, column: int, row_number: int, value: object, style: int = 0) -> None:
    cell = ET.SubElement(
        row,
        f"{{{MAIN_NS}}}c",
        {"r": f"{_column_name(column)}{row_number}", "t": "inlineStr", "s": str(style)},
    )
    inline = ET.SubElement(cell, f"{{{MAIN_NS}}}is")
    text = ET.SubElement(inline, f"{{{MAIN_NS}}}t")
    text.text = "" if value is None else str(value)


def _number_cell(row: ET.Element, column: int, row_number: int, value: int, style: int = 0) -> None:
    cell = ET.SubElement(
        row,
        f"{{{MAIN_NS}}}c",
        {"r": f"{_column_name(column)}{row_number}", "s": str(style)},
    )
    ET.SubElement(cell, f"{{{MAIN_NS}}}v").text = str(value)


def _sheet_xml(
    *,
    title: str,
    metadata: list[tuple[str, object]],
    headers: list[str],
    rows: list[list[tuple[str, object]]],
    widths: list[float],
) -> bytes:
    last_row = max(5, 5 + len(rows))
    worksheet = ET.Element(f"{{{MAIN_NS}}}worksheet")
    ET.SubElement(
        worksheet,
        f"{{{MAIN_NS}}}dimension",
        {"ref": f"A1:{_column_name(len(headers))}{last_row}"},
    )
    views = ET.SubElement(worksheet, f"{{{MAIN_NS}}}sheetViews")
    view = ET.SubElement(views, f"{{{MAIN_NS}}}sheetView", {"workbookViewId": "0"})
    ET.SubElement(
        view,
        f"{{{MAIN_NS}}}pane",
        {"ySplit": "5", "topLeftCell": "A6", "activePane": "bottomLeft", "state": "frozen"},
    )
    columns = ET.SubElement(worksheet, f"{{{MAIN_NS}}}cols")
    for index, width in enumerate(widths, start=1):
        ET.SubElement(
            columns,
            f"{{{MAIN_NS}}}col",
            {"min": str(index), "max": str(index), "width": str(width), "customWidth": "1"},
        )
    sheet_data = ET.SubElement(worksheet, f"{{{MAIN_NS}}}sheetData")

    title_row = ET.SubElement(sheet_data, f"{{{MAIN_NS}}}row", {"r": "1", "ht": "28", "customHeight": "1"})
    _string_cell(title_row, 1, 1, title, 1)

    for row_number, (label, value) in enumerate(metadata, start=2):
        row = ET.SubElement(sheet_data, f"{{{MAIN_NS}}}row", {"r": str(row_number)})
        _string_cell(row, 1, row_number, label, 5)
        if isinstance(value, int):
            _number_cell(row, 2, row_number, value, 3 if "金額" in label else 0)
        else:
            _string_cell(row, 2, row_number, value)

    header_row_number = 5
    header_row = ET.SubElement(sheet_data, f"{{{MAIN_NS}}}row", {"r": str(header_row_number), "ht": "24", "customHeight": "1"})
    for column, header in enumerate(headers, start=1):
        _string_cell(header_row, column, header_row_number, header, 2)

    for row_number, values in enumerate(rows, start=6):
        row = ET.SubElement(sheet_data, f"{{{MAIN_NS}}}row", {"r": str(row_number)})
        for column, (kind, value) in enumerate(values, start=1):
            if kind == "currency":
                _number_cell(row, column, row_number, int(value), 3)
            elif kind == "number":
                _number_cell(row, column, row_number, int(value))
            else:
                _string_cell(row, column, row_number, value, 6 if kind == "wrap" else 0)

    ET.SubElement(
        worksheet,
        f"{{{MAIN_NS}}}autoFilter",
        {"ref": f"A5:{_column_name(len(headers))}{last_row}"},
    )
    merges = ET.SubElement(worksheet, f"{{{MAIN_NS}}}mergeCells", {"count": "1"})
    ET.SubElement(merges, f"{{{MAIN_NS}}}mergeCell", {"ref": f"A1:{_column_name(len(headers))}1"})
    ET.SubElement(
        worksheet,
        f"{{{MAIN_NS}}}pageMargins",
        {"left": "0.3", "right": "0.3", "top": "0.5", "bottom": "0.5", "header": "0.2", "footer": "0.2"},
    )
    return ET.tostring(worksheet, encoding="utf-8", xml_declaration=True)


def _workbook_xml(sheet_names: tuple[str, ...]) -> bytes:
    workbook = ET.Element(f"{{{MAIN_NS}}}workbook")
    sheets = ET.SubElement(workbook, f"{{{MAIN_NS}}}sheets")
    for sheet_id, name in enumerate(sheet_names, start=1):
        ET.SubElement(
            sheets,
            f"{{{MAIN_NS}}}sheet",
            {"name": name, "sheetId": str(sheet_id), f"{{{REL_NS}}}id": f"rId{sheet_id}"},
        )
    return ET.tostring(workbook, encoding="utf-8", xml_declaration=True)


def _styles_xml() -> bytes:
    return b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="1"><numFmt numFmtId="164" formatCode="NT$ #,##0"/></numFmts>
  <fonts count="3">
    <font><sz val="11"/><name val="Microsoft JhengHei"/></font>
    <font><b/><color rgb="FFFFFFFF"/><sz val="15"/><name val="Microsoft JhengHei"/></font>
    <font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Microsoft JhengHei"/></font>
  </fonts>
  <fills count="4">
    <fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF315C4B"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF8D3F2D"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="7">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0"><alignment vertical="center"/></xf>
    <xf numFmtId="0" fontId="2" fillId="3" borderId="0" xfId="0"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"><alignment horizontal="right"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"><alignment wrapText="1" vertical="top"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''


def _format_created_at(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone().strftime("%Y-%m-%d %H:%M")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M")
    return "" if value is None else str(value)


def _package_workbook(sheets: list[bytes], sheet_names: tuple[str, ...]) -> bytes:
    worksheet_types = "\n".join(
        f'  <Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, len(sheets) + 1)
    )
    worksheet_relationships = "\n".join(
        f'  <Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, len(sheets) + 1)
    )
    styles_relationship_id = len(sheets) + 1
    content_types = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="{CONTENT_NS}">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
{worksheet_types}
</Types>'''
    root_rels = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{PACKAGE_REL_NS}">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''
    workbook_rels = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{PACKAGE_REL_NS}">
{worksheet_relationships}
  <Relationship Id="rId{styles_relationship_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''

    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as workbook_zip:
        workbook_zip.writestr("[Content_Types].xml", content_types)
        workbook_zip.writestr("_rels/.rels", root_rels)
        workbook_zip.writestr("xl/workbook.xml", _workbook_xml(sheet_names))
        workbook_zip.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        workbook_zip.writestr("xl/styles.xml", _styles_xml())
        for index, sheet in enumerate(sheets, start=1):
            workbook_zip.writestr(f"xl/worksheets/sheet{index}.xml", sheet)
    return output.getvalue()


def _format_order_identity(order: dict) -> str:
    method = order.get("identity_method", "legacy")
    value = order.get("identity_value")
    labels = {"google": "Google 帳號", "phone": "手機", "email": "Email"}
    if method == "legacy":
        return "舊訂單（未記錄）"
    label = labels.get(method, "聯絡資料")
    return f"{label}：{value}" if value else label


def build_group_order_workbook(group: dict) -> bytes:
    """建立含餐點、訂購者合計與個人明細三張工作表的 XLSX。"""
    status = "進行中" if group["status"] == "open" else "已截止"
    metadata = [
        ("餐廳", group["restaurant_name"]),
        ("團購代碼", group["public_code"]),
        (
            "狀態／訂單／總金額",
            f"{status}／{group['order_count']} 張／NT$ {group['grand_total']:,}",
        ),
    ]
    summary_rows = [
        [
            ("text", item["item_name"]),
            ("wrap", item["note"] or "一般（無備註）"),
            ("currency", item["unit_price"]),
            ("number", item["total_quantity"]),
            ("currency", item["total_amount"]),
        ]
        for item in group["summary"]
    ]
    purchaser_rows = []
    detail_rows = []
    for order in group["orders"]:
        created_at = _format_created_at(order["created_at"])
        identity = _format_order_identity(order)
        purchaser_rows.append(
            [
                ("text", order["customer_name"]),
                ("text", identity),
                ("number", sum(item["quantity"] for item in order["items"])),
                ("currency", order["total_amount"]),
                ("text", created_at),
            ]
        )
        for item in order["items"]:
            detail_rows.append(
                [
                    ("text", order["customer_name"]),
                    ("text", identity),
                    ("text", item["item_name"]),
                    ("wrap", item["note"] or ""),
                    ("currency", item["unit_price"]),
                    ("number", item["quantity"]),
                    ("currency", item["subtotal"]),
                    ("text", created_at),
                ]
            )

    sheets = [
        _sheet_xml(
            title=f"{group['restaurant_name']}｜餐點彙整",
            metadata=metadata,
            headers=["品項名稱", "需求備註", "單價", "總數量", "小計"],
            rows=summary_rows,
            widths=[26, 30, 13, 11, 14],
        ),
        _sheet_xml(
            title=f"{group['restaurant_name']}｜訂購者合計",
            metadata=metadata,
            headers=["姓名", "身分辨識", "餐點總數量", "合計金額", "送單時間"],
            rows=purchaser_rows,
            widths=[18, 28, 15, 16, 20],
        ),
        _sheet_xml(
            title=f"{group['restaurant_name']}｜個人明細",
            metadata=metadata,
            headers=["姓名", "身分辨識", "品項名稱", "需求備註", "單價", "數量", "小計", "送單時間"],
            rows=detail_rows,
            widths=[16, 28, 26, 30, 13, 10, 14, 20],
        ),
    ]

    return _package_workbook(sheets, ("餐點彙整", "訂購者合計", "個人明細"))


def build_store_order_workbook(store: dict) -> bytes:
    """建立含餐點彙整、顧客合計與顧客明細的店家訂單 XLSX。"""
    service_state = "開放接單" if store["active"] else "暫停接單"
    metadata = [
        ("店家", store["restaurant_name"]),
        ("店家識別碼", store["public_slug"]),
        (
            "狀態／訂單／總金額",
            f"{service_state}／{store['order_count']} 張／NT$ {store['grand_total']:,}",
        ),
    ]
    summary_rows = [
        [
            ("text", item["item_name"]),
            ("wrap", item["note"] or "一般（無備註）"),
            ("currency", item["unit_price"]),
            ("number", item["total_quantity"]),
            ("currency", item["total_amount"]),
        ]
        for item in store["summary"]
    ]
    customer_rows = []
    detail_rows = []
    for order in store["orders"]:
        created_at = _format_created_at(order["created_at"])
        identity = _format_order_identity(order)
        customer_rows.append(
            [
                ("text", order["customer_name"]),
                ("text", identity),
                ("number", sum(item["quantity"] for item in order["items"])),
                ("currency", order["total_amount"]),
                ("text", created_at),
            ]
        )
        for item in order["items"]:
            detail_rows.append(
                [
                    ("text", order["customer_name"]),
                    ("text", identity),
                    ("text", item["item_name"]),
                    ("wrap", item["note"] or ""),
                    ("currency", item["unit_price"]),
                    ("number", item["quantity"]),
                    ("currency", item["subtotal"]),
                    ("text", created_at),
                ]
            )

    sheets = [
        _sheet_xml(
            title=f"{store['restaurant_name']}｜餐點彙整",
            metadata=metadata,
            headers=["品項名稱", "需求備註", "單價", "總數量", "小計"],
            rows=summary_rows,
            widths=[26, 30, 13, 11, 14],
        ),
        _sheet_xml(
            title=f"{store['restaurant_name']}｜顧客合計",
            metadata=metadata,
            headers=["姓名", "身分辨識", "餐點總數量", "合計金額", "送單時間"],
            rows=customer_rows,
            widths=[18, 28, 15, 16, 20],
        ),
        _sheet_xml(
            title=f"{store['restaurant_name']}｜顧客明細",
            metadata=metadata,
            headers=["姓名", "身分辨識", "品項名稱", "需求備註", "單價", "數量", "小計", "送單時間"],
            rows=detail_rows,
            widths=[16, 28, 26, 30, 13, 10, 14, 20],
        ),
    ]
    return _package_workbook(sheets, ("餐點彙整", "顧客合計", "顧客明細"))
