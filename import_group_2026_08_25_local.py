from __future__ import annotations

import re
import shutil
from pathlib import Path

from bs4 import BeautifulSoup

from database import SessionLocal
import models


ROOT = Path(__file__).resolve().parent
EXPORT = Path(r"C:\Users\Hamid Moosavi\Downloads\Telegram Desktop\ChatExport_2026-08-25")
PHOTO_DIR = ROOT / "photos"
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٬٫", "0123456789,.")


def norm(text: str) -> str:
    return text.translate(DIGITS).replace("٫", ".").strip()


def category(text: str) -> str:
    t = text.casefold()
    if any(x in t for x in ("کفش", "صندل", "sneaker", "shoe", "adidas", "puma", "nike")):
        return "کفش"
    if any(x in t for x in ("کیف", "bag", "purse", "cross body")):
        return "کیف"
    if any(x in t for x in ("عطر", "ادکلن", "perfume", "parfum", "eau de", "edt", "edp")):
        return "عطر و ادکلن"
    if any(x in t for x in ("تیشرت", "لباس", "شلوار", "پیراهن", "پالتو", "dress", "shirt")):
        return "لباس"
    if any(x in t for x in ("قرص", "ویتامین", "مکمل", "دارو")):
        return "دارو و سلامتی"
    if any(x in t for x in ("اکسسوری", "ساعت", "گردنبند", "دستبند", "عینک")):
        return "اکسسوری"
    return "سایر"


def extract_name(lines: list[str]) -> str:
    skip = re.compile(r"^(?:موجودی|برای ثبت|قیمت|وزن|سایز|size|[0-9]+(?:[.,][0-9]+)?\s*(?:gr|g|گرم|\$|دلار))", re.I)
    for line in lines:
        line = re.sub(r"^[📦🌸😇🔸️✅❌\-\s]+", "", line).strip()
        if not line or skip.search(norm(line)):
            continue
        if "برای ثبت سفارش" in line or "آیدی" in line or line.startswith("@"):
            continue
        return line[:180]
    return "محصول وارداتی"


def parse_messages() -> list[dict]:
    soup = BeautifulSoup((EXPORT / "messages.html").read_text(encoding="utf-8"), "html.parser")
    products: list[dict] = []
    for message in soup.select("div.message.default"):
        text_node = message.select_one(".text")
        text = text_node.get_text("\n", strip=True) if text_node else ""
        photos = [a["href"] for a in message.select("a.photo_wrap[href]")]
        if text:
            products.append({"text": text, "photos": photos})
        elif photos and products:
            products[-1]["photos"].extend(photos)

    result = []
    for item in products:
        text = norm(item["text"])
        price_matches = re.findall(r"([0-9]+(?:[.,][0-9]+)?)\s*(?:[$]|دلار)", text, re.I)
        if not price_matches or not item["photos"]:
            continue
        price = float(price_matches[-1].replace(",", "."))
        weight_match = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*(?:gr|g|گرم)", text, re.I)
        weight = float(weight_match.group(1).replace(",", ".")) if weight_match else None
        size_match = re.search(r"(?:سایز|size)\s*[:\-]?\s*([A-Za-z0-9۰-۹/ .-]+)", item["text"], re.I)
        size = size_match.group(1).strip() if size_match else None
        lines = [x.strip() for x in item["text"].splitlines() if x.strip()]
        result.append(
            {
                "name": extract_name(lines),
                "description": item["text"][:4000],
                "price_usd": price,
                "size": size,
                "weight_grams": weight,
                "category": category(item["text"]),
                "location": "کانادا",
                "photos": [Path(p).name for p in item["photos"]],
            }
        )
    return result


def main() -> None:
    rows = parse_messages()
    session = SessionLocal()
    added = skipped = copied = 0
    try:
        keys = {
            ((p.name or "").casefold().strip(), float(p.price_usd or 0), (p.weight_grams or 0))
            for p in session.query(models.Product).all()
        }
        for row in rows:
            key = (row["name"].casefold().strip(), row["price_usd"], row["weight_grams"] or 0)
            if key in keys:
                skipped += 1
                continue
            paths = []
            for photo in row["photos"]:
                src = EXPORT / "photos" / photo
                if not src.exists():
                    continue
                dst = PHOTO_DIR / f"group0825_{src.name}"
                if not dst.exists():
                    shutil.copy2(src, dst)
                    copied += 1
                paths.append(str(dst.relative_to(ROOT)).replace("\\", "/"))
            session.add(models.Product(
                name=row["name"], description=row["description"],
                price_usd=row["price_usd"], size=row["size"],
                weight_grams=row["weight_grams"], category=row["category"],
                location=row["location"], original_photo_path="|".join(paths) or None,
            ))
            keys.add(key)
            added += 1
        session.commit()
        print(f"candidates={len(rows)} added={added} skipped={skipped} photos_copied={copied}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
