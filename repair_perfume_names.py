from database import SessionLocal
import models
from build_perfume_import import perfume_rows


GENERIC = {"عطر استخراج‌شده", "نت ها", "ترکیب نت‌ها", "ترکیب نت ها", "264gr", "258gr", "261gr", "262gr"}


def main() -> None:
    rows = perfume_rows()
    by_photo = {}
    for row in rows:
        for photo in row.get("photos", []):
            by_photo[photo] = row["name"]
    session = SessionLocal()
    changed = 0
    try:
        for product in session.query(models.Product).all():
            if product.category != "عطر و ادکلن" or not product.original_photo_path:
                continue
            for photo in product.original_photo_path.split("|"):
                key = photo.replace("\\", "/").rsplit("/", 1)[-1]
                if key.startswith("perfume_"):
                    key = key.removeprefix("perfume_")
                candidate = by_photo.get(key)
                bad_name = (
                    product.name in GENERIC
                    or len(product.name) < 5
                    or product.name.startswith(("رایحه", "نت", "اسانس", "ترکیب نت"))
                )
                if candidate and bad_name:
                    product.name = candidate
                    changed += 1
                    break
        session.commit()
        print(f"changed={changed}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
