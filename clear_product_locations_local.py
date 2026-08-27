from database import SessionLocal
import models


def main() -> None:
    session = SessionLocal()
    try:
        rows = session.query(models.Product).all()
        for product in rows:
            product.location = None
        session.commit()
        print(f"cleared={len(rows)}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
