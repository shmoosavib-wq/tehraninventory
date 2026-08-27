from database import SessionLocal
import models


CANADA = "\u06a9\u0627\u0646\u0627\u062f\u0627"


def main() -> None:
    session = SessionLocal()
    try:
        rows = session.query(models.Product).filter(models.Product.location == CANADA).all()
        ids = [p.id for p in rows]
        for product in rows:
            session.delete(product)
        session.commit()
        print(f"deleted={len(ids)} ids={ids[:20]}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
