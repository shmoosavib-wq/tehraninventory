from __future__ import annotations

import os
import time

import httpx

from database import SessionLocal
import models


API_BASE_URL = os.getenv(
    "MIGRATION_API_URL",
    "https://tehraninventory-production.up.railway.app",
).rstrip("/")


def main() -> None:
    db = SessionLocal()
    client = httpx.Client(timeout=30)
    try:
        products = db.query(models.Product).order_by(models.Product.id).all()
        remote = client.get(f"{API_BASE_URL}/products")
        remote.raise_for_status()
        existing = remote.json()
        keys = {
            (
                str(p.get("name") or "").strip().casefold(),
                float(p.get("price_usd") or 0),
                float(p.get("weight_grams") or 0),
            )
            for p in existing
        }
        added = skipped = failed = 0
        for product in products:
            key = (
                (product.name or "").strip().casefold(),
                float(product.price_usd or 0),
                float(product.weight_grams or 0),
            )
            if key in keys:
                skipped += 1
                continue
            payload = {
                "name": product.name,
                "description": product.description,
                "ai_description": product.ai_description,
                "price_usd": product.price_usd,
                "size": product.size,
                "weight_grams": product.weight_grams,
                "location": product.location,
                "category": product.category,
                "owner_admin_id": product.owner_admin_id,
                "created_by_admin_id": product.created_by_admin_id,
                "telegram_file_id": product.telegram_file_id,
                "original_photo_path": product.original_photo_path,
                "telegram_link_1": product.telegram_link_1,
                "telegram_link_2": product.telegram_link_2,
            }
            try:
                response = client.post(f"{API_BASE_URL}/products", json=payload)
                response.raise_for_status()
                keys.add(key)
                added += 1
                print(f"added local_id={product.id} remote_id={response.json().get('id')}")
            except Exception as exc:
                failed += 1
                print(f"failed local_id={product.id}: {exc}")
            time.sleep(0.05)
        print(f"local={len(products)} remote_before={len(existing)} added={added} skipped={skipped} failed={failed}")
    finally:
        client.close()
        db.close()


if __name__ == "__main__":
    main()
