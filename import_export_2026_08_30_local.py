from __future__ import annotations

import re
import shutil
from pathlib import Path

from bs4 import BeautifulSoup

from database import SessionLocal
import models


ROOT = Path(__file__).resolve().parent
EXPORT = Path(r"C:\Users\Hamid Moosavi\Downloads\Telegram Desktop\ChatExport_2026-08-30 (1)")
PHOTO_DIR = ROOT / "photos"
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٬٫", "0123456789,.")
PRICE_RE = re.compile(r"([0-9]+(?:[.,][0-9]+)?)\s*(?:دلار|دالر|usd|\$)", re.I)
WEIGHT_RE = re.compile(r"([0-9]+(?:[.,][0-9]+)?)\s*(?:گرم|gr|g)\b", re.I)


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.translate(DIGITS)).strip()


def category(text: str) -> str:
    t = text.casefold()
    rules = [
        ("عطر و ادکلن", ("عطر", "ادکلن", "perfume", "cologne", "fragrance", "parfum")),
        ("دارو و سلامتی", ("قرص", "ادویل", "ویتامین", "مکمل", "دارو", "rogaine", "minoxidil")),
        ("کفش", ("کفش", "کتونی", "صندل", "بوت", "sneaker", "shoe", "nike", "adidas", "plakton")),
        ("کیف", ("کیف", "کوله", "bag", "tote", "satchel", "backpack")),
        ("لباس", ("تیشرت", "پیراهن", "شلوار", "کاپشن", "پافر", "لباس", "shirt", "jacket", "polo")),
        ("ورزشی", ("ورزشی", "فوتبال", "بدنسازی", "running", "gym", "sport")),
        ("اکسسوری", ("اکسسوری", "ساعت", "انگشتر", "گردنبند", "دستبند", "watch")),
        ("آرایشی بهداشتی", ("آرایشی", "بهداشتی", "کرم", "شامپو", "cosmetic")),
    ]
    return next((label for label, words in rules if any(word in t for word in words)), "سایر")


def name_from_text(text: str, cat: str) -> str:
    lines = [clean(x) for x in text.splitlines() if clean(x)]
    for line in lines:
        line = line.strip("🌸💜💛💖🖤✅🔸️⚜👜👟🏃‍♂️🇨🇦🇮🇷-–—: ")
        if not line or PRICE_RE.search(line) or re.fullmatch(r"[0-9 .,/+-]+", line):
            continue
        if line.lower().startswith(("قیمت", "وزن", "سایز", "موقعیت", "موجود", "انقضا", "عرض سینه", "قد")):
            continue
        return line[:180]
    return f"محصول {cat}"


def parse_rows() -> list[dict]:
    soup = BeautifulSoup((EXPORT / "messages.html").read_text(encoding="utf-8"), "html.parser")
    rows = []
    for message in soup.select("div.message.default"):
        text_node = message.select_one(".text")
        text = text_node.get_text("\n", strip=True) if text_node else ""
        photos = [Path(a["href"]).name for a in message.select("a.photo_wrap[href]")]
        if not text or not photos:
            continue
        normalized = clean(text)
        prices = PRICE_RE.findall(normalized)
        if not prices:
            continue
        price = float(prices[-1].replace(",", "."))
        weight_match = WEIGHT_RE.search(normalized)
        weight = float(weight_match.group(1).replace(",", ".")) if weight_match else None
        cat = category(normalized)
        location = "کانادا" if ("🇨🇦" in text or "کانادا" in text or "canada" in text.casefold()) else "تهران"
        rows.append({
            "name": name_from_text(text, cat),
            "description": text[:4000],
            "price_usd": price,
            "weight_grams": weight,
            "category": cat,
            "location": location,
            "photos": photos[:3],
        })
    return rows


def main() -> None:
    PHOTO_DIR.mkdir(exist_ok=True)
    rows = parse_rows()
    db = SessionLocal()
    added = skipped = copied = 0
    try:
        existing = {
            ((p.name or "").strip().casefold(), float(p.price_usd or 0), float(p.weight_grams or 0))
            for p in db.query(models.Product).all()
        }
        for row in rows:
            key = (row["name"].casefold().strip(), row["price_usd"], float(row["weight_grams"] or 0))
            if key in existing:
                skipped += 1
                continue
            paths = []
            for filename in row["photos"]:
                source = EXPORT / "photos" / filename
                if not source.exists():
                    continue
                target = PHOTO_DIR / f"export0830_{filename}"
                if not target.exists():
                    shutil.copy2(source, target)
                    copied += 1
                paths.append(str(target.relative_to(ROOT)).replace("\\", "/"))
            db.add(models.Product(
                name=row["name"], description=row["description"], price_usd=row["price_usd"],
                weight_grams=row["weight_grams"], category=row["category"], location=row["location"],
                original_photo_path="|".join(paths) or None,
            ))
            existing.add(key)
            added += 1
        db.commit()
        print(f"candidates={len(rows)} added={added} skipped={skipped} photos_copied={copied} total={db.query(models.Product).count()}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
