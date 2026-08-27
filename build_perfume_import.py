from __future__ import annotations

import re
import shutil
import unicodedata
from pathlib import Path

import openpyxl
from bs4 import BeautifulSoup
from openpyxl.styles import Alignment, Font, PatternFill

from database import SessionLocal
import models


ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "product_import_template.xlsx"
EXPORT = Path(r"C:\Users\Hamid Moosavi\Downloads\Telegram Desktop\ChatExport_2026-08-24")
OUTPUT = ROOT / "railway_inventory_import_2026-08-25.xlsx"

DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٬٫", "0123456789,.")
PRICE_RE = re.compile(r"([0-9]+(?:[.,][0-9]+)?)\s*\$")
VOLUME_RE = re.compile(r"([0-9]+(?:[.,][0-9]+)?)\s*(ml|میل)\b", re.I)
WEIGHT_RE = re.compile(r"([0-9]+(?:[.,][0-9]+)?)\s*(?:gr|g|گرم)\b", re.I)


def clean_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).translate(DIGITS)
    return re.sub(r"[ \t]+", " ", value).strip()


def first_name(lines: list[str]) -> str:
    full_text = "\n".join(lines)
    # Some posts start with the note pyramid and mention the actual product
    # in the sales copy, e.g. "Musc Noir Rose دقیقا همونه".
    embedded = re.search(
        r"\b([A-Z][A-Za-z0-9'’&.\-]*(?:\s+[A-Z][A-Za-z0-9'’&.\-]*){1,8})\s+"
        r"(?:دقیقاً|دقیقا|یک عطر|عطر)\b",
        full_text,
    )
    if embedded:
        return embedded.group(1).strip()[:180]
    for line in lines:
        match = re.search(r"(?:عطر|محصول)\s+(.{2,100}?)(?=\s+(?:با|یک|رایحه|از|در|است)\b|$)", line, re.I)
        if match:
            candidate = re.split(r"[|،,:؛.!؟]", match.group(1))[0].strip()
            if candidate:
                return candidate[:180]
    for line in lines:
        line = clean_text(line).strip("🌸💜💛💖🖤✅🔸️⚜-–—: ")
        if not line:
            continue
        if PRICE_RE.fullmatch(line) or VOLUME_RE.fullmatch(line):
            continue
        lower = line.lower()
        if (
            lower in {"edp", "edt", "parfum", "نت ها", "نت ها:", "ترکیب نت ها", "ترکیب نت‌ها", "رایحه اولیه", "اسانس اولیه"}
            or lower.startswith(("رایحه اولیه:", "رایحه میانی:", "رایحه پایه:", "نت‌های ابتدایی:", "نت های ابتدایی:", "اسانس اولیه:"))
        ):
            continue
        if line.startswith("@") or "تومان" in line:
            continue
        return line[:180]
    return "عطر استخراج‌شده"


def perfume_rows() -> list[dict]:
    soup = BeautifulSoup((EXPORT / "messages.html").read_text(encoding="utf-8"), "html.parser")
    result: list[dict] = []
    seen: set[tuple[str, float, str, str]] = set()
    for message in soup.select("div.message.default"):
        text_node = message.select_one(".text")
        text = text_node.get_text("\n", strip=True) if text_node else ""
        photo_paths = [a["href"] for a in message.select("a.photo_wrap[href]")]
        if not text or not photo_paths:
            continue
        normalized = clean_text(text)
        price_match = PRICE_RE.search(normalized)
        if not price_match:
            continue
        price = float(price_match.group(1).replace(",", "."))
        volume_match = VOLUME_RE.search(normalized)
        volume = f"{volume_match.group(1).replace(',', '.')}ml" if volume_match else ""
        weight_match = WEIGHT_RE.search(normalized)
        weight = float(weight_match.group(1).replace(",", ".")) if weight_match else None
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        name = first_name(lines)
        # Do not import obvious price-only availability chatter.
        if name == "عطر استخراج‌شده" and not volume:
            continue
        desc = "\n".join(lines)
        key = (name.casefold(), price, volume.casefold(), photo_paths[0])
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "name": name,
                "description": desc[:4000],
                "price_usd": price,
                "size": volume or None,
                "weight_grams": weight,
                "location": "کانادا",
                "category": "عطر و ادکلن",
                "photos": [Path(p).name for p in photo_paths[:3]],
            }
        )
    return result


def existing_rows() -> list[dict]:
    session = SessionLocal()
    try:
        rows = []
        for product in session.query(models.Product).order_by(models.Product.id):
            photos = [Path(p).name for p in (product.original_photo_path or "").split("|") if p]
            rows.append(
                {
                    "name": product.name,
                    "description": product.description or "",
                    "price_usd": product.price_usd,
                    "size": product.size,
                    "weight_grams": product.weight_grams,
                    "location": product.location or "کانادا",
                    "category": product.category or "سایر",
                    "photos": photos[:3],
                }
            )
        return rows
    finally:
        session.close()


def build() -> None:
    workbook = openpyxl.load_workbook(TEMPLATE)
    sheet = workbook["محصولات"]
    headers = [cell.value for cell in sheet[4]]
    # Remove the example row and any stale rows while preserving template styling.
    for row in range(sheet.max_row, 4, -1):
        sheet.delete_rows(row)

    rows = existing_rows()
    existing_keys = {
        (clean_text(r["name"]).casefold(), float(r["price_usd"] or 0), clean_text(r.get("size") or "").casefold())
        for r in rows
    }
    added = 0
    for row in perfume_rows():
        key = (clean_text(row["name"]).casefold(), float(row["price_usd"]), clean_text(row.get("size") or "").casefold())
        if key in existing_keys:
            continue
        existing_keys.add(key)
        rows.append(row)
        added += 1

    for idx, row in enumerate(rows, start=5):
        sku = f"IMP-{idx - 4:04d}"
        photos = (row.get("photos") or [])[:3]
        photos += [None] * (3 - len(photos))
        values = [
            sku,
            row["name"],
            row.get("description") or None,
            float(row["price_usd"]),
            row.get("size"),
            row.get("weight_grams"),
            row.get("location") or "کانادا",
            row.get("category") or "سایر",
            *photos,
            None,
            None,
            f"=D{idx}*تنظیمات!$B$3*تنظیمات!$B$5+(F{idx}/1000)*تنظیمات!$B$4",
        ]
        for col, value in enumerate(values, start=1):
            cell = sheet.cell(idx, col, value)
            cell.alignment = Alignment(horizontal="right", vertical="top", wrap_text=True)
        sheet.row_dimensions[idx].height = 72

    # Keep the template guide and make the import caveat explicit.
    guide = workbook["راهنما"]
    guide["A11"] = "۹"
    guide["B11"] = "محصولات گروه عطر از فایل Telegram استخراج شده‌اند؛ عکس‌ها در ستون‌های عکس با نام فایل ثبت شده‌اند."
    guide["A12"] = "۱۰"
    guide["B12"] = "برای نمایش عکس‌ها در Railway، خود فایل‌های عکس باید جداگانه در بات آپلود شوند؛ Excel فقط اطلاعات و نام فایل را منتقل می‌کند."
    for cell in ("A11", "A12", "B11", "B12"):
        guide[cell].alignment = Alignment(horizontal="right", vertical="top", wrap_text=True)

    # A visible marker in the title helps distinguish this populated workbook.
    sheet["A1"] = "ورود گروهی موجودی تهران — محصولات فعلی + استخراج گروه عطر (25 مرداد 1405)"
    sheet["A1"].font = Font(bold=True, size=14, color="FFFFFF")
    sheet["A1"].fill = PatternFill("solid", fgColor="4472C4")
    # Avoid merged cells in the data sheet so lightweight import validators and
    # Telegram's read-only workbook parser can inspect every column reliably.
    for merged_range in list(sheet.merged_cells.ranges):
        sheet.unmerge_cells(str(merged_range))
    workbook.save(OUTPUT)
    print(f"saved={OUTPUT} existing={len(rows)-added} perfume_added={added} total={len(rows)}")


if __name__ == "__main__":
    build()
