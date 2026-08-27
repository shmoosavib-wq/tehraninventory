from database import SessionLocal
import models


def main() -> None:
    session = SessionLocal()
    changed = 0
    try:
        products = session.query(models.Product).all()
        for product in products:
            text = f"{product.name or ''}\n{product.description or ''}"
            if any(marker in text for marker in ("موجودی تهران", "ارسال سریع تهران", "تحویل تهران")):
                if product.location != "تهران":
                    product.location = "تهران"
                    changed += 1
        session.commit()
        print(f"changed={changed}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
