from __future__ import annotations

import shutil
from pathlib import Path

from database import SessionLocal
import models
from build_perfume_import import EXPORT, perfume_rows


ROOT = Path(__file__).resolve().parent
PHOTO_DIR = ROOT / "photos"


def main() -> None:
    PHOTO_DIR.mkdir(exist_ok=True)
    session = SessionLocal()
    added = 0
    skipped = 0
    copied = 0
    try:
        existing = {
            (
                (p.name or "").strip().casefold(),
                float(p.price_usd or 0),
                (p.size or "").strip().casefold(),
            )
            for p in session.query(models.Product).all()
        }
        for row in perfume_rows():
            key = (
                row["name"].strip().casefold(),
                float(row["price_usd"]),
                (row.get("size") or "").strip().casefold(),
            )
            if key in existing:
                skipped += 1
                continue
            local_paths = []
            for source_name in row.get("photos", []):
                source = EXPORT / "photos" / source_name
                if not source.exists():
                    continue
                destination = PHOTO_DIR / f"perfume_{source.name}"
                if not destination.exists():
                    shutil.copy2(source, destination)
                    copied += 1
                local_paths.append(str(destination.relative_to(ROOT)).replace("\\", "/"))
            product = models.Product(
                name=row["name"],
                description=row.get("description"),
                price_usd=float(row["price_usd"]),
                size=row.get("size"),
                weight_grams=row.get("weight_grams"),
                location=row.get("location") or "کانادا",
                category="عطر و ادکلن",
                original_photo_path="|".join(local_paths) or None,
            )
            session.add(product)
            existing.add(key)
            added += 1
        session.commit()
        print(f"added={added} skipped={skipped} photos_copied={copied}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
