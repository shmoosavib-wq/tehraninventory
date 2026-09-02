from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path
import os
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text, func, case
from datetime import datetime, timedelta
import json
from typing import List
import models, schemas
from database import engine, get_db

def ensure_schema():
    models.Base.metadata.create_all(bind=engine)
    columns = {column["name"] for column in inspect(engine).get_columns("products")}
    if "created_by_admin_id" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE products ADD COLUMN created_by_admin_id INTEGER"))
    if "owner_admin_id" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE products ADD COLUMN owner_admin_id INTEGER"))
    if "ai_description" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE products ADD COLUMN ai_description TEXT")
            )
    if "created_by_admin_username" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE products ADD COLUMN created_by_admin_username VARCHAR"))


ensure_schema()

app = FastAPI(title="Tehran Inventory API", version="1.0.0")
cors_origins = [x.strip() for x in os.environ.get("CORS_ORIGINS", "http://127.0.0.1:5500,http://localhost:5500").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_credentials=False, allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "X-Analytics-Token"])
RAILWAY_PHOTO_DIR = Path(os.environ.get("PHOTO_DIR", "/data/photos"))
RAILWAY_PHOTO_DIR.mkdir(parents=True, exist_ok=True)

@app.get("/")
def read_root():
    return {"message": "Tehran Inventory API is running"}

@app.get("/media/{filename}")
def get_media(filename: str):
    photo = RAILWAY_PHOTO_DIR / Path(filename).name
    if not photo.is_file():
        raise HTTPException(status_code=404, detail="Media not found")
    return FileResponse(photo)

@app.post("/media/upload")
async def upload_media(file: UploadFile = File(...), x_media_token: str | None = Header(default=None)):
    expected = os.environ.get("MEDIA_UPLOAD_TOKEN")
    if not expected or x_media_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    filename = Path(file.filename or "").name
    if not filename:
        raise HTTPException(status_code=400, detail="Filename is required")
    target = RAILWAY_PHOTO_DIR / filename
    with target.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            output.write(chunk)
    return {"filename": filename, "path": f"photos/{filename}"}

@app.get("/products", response_model=List[schemas.ProductResponse])
def get_products(db: Session = Depends(get_db)):
    products = db.query(models.Product).all()
    return products

@app.get("/products/{product_id}", response_model=schemas.ProductResponse)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

@app.post("/products", response_model=schemas.ProductResponse)
def create_product(product: schemas.ProductCreate, db: Session = Depends(get_db)):
    db_product = models.Product(**product.dict())
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    return db_product

@app.put("/products/{product_id}", response_model=schemas.ProductResponse)
def update_product(
    product_id: int, 
    product_update: schemas.ProductUpdate, 
    db: Session = Depends(get_db)
):
    db_product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    update_data = product_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_product, field, value)
    
    db.commit()
    db.refresh(db_product)
    return db_product

@app.delete("/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    db_product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    db.delete(db_product)
    db.commit()
    return {"message": "Product deleted"}


@app.post("/analytics/events", response_model=schemas.ActivityEventResponse)
def create_activity_event(event: schemas.ActivityEventCreate, db: Session = Depends(get_db)):
    allowed = {"user_started", "search", "search_no_result", "view_product", "click_order", "order_referred", "order_created", "order_completed", "order_cancelled", "product_created"}
    if event.event_type not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported event type")
    row = models.ActivityEvent(user_id=event.user_id, event_type=event.event_type, product_id=event.product_id, search_text=(event.search_text or "")[:255] or None, category=event.category, price_min=event.price_min, price_max=event.price_max, metadata_json=json.dumps(event.metadata, ensure_ascii=False) if event.metadata else None)
    db.add(row); db.commit(); db.refresh(row); return row

@app.get("/analytics/summary")
def analytics_summary(days: int = 7, db: Session = Depends(get_db)):
    days=max(1,min(days,90)); since=datetime.utcnow()-timedelta(days=days); q=db.query(models.ActivityEvent).filter(models.ActivityEvent.created_at>=since)
    users=q.with_entities(func.count(func.distinct(models.ActivityEvent.user_id))).scalar() or 0
    searches=q.filter(models.ActivityEvent.event_type=="search").count(); views=q.filter(models.ActivityEvent.event_type=="view_product").count(); clicks=q.filter(models.ActivityEvent.event_type=="click_order").count(); completed=q.filter(models.ActivityEvent.event_type=="order_completed").count()
    return {"days":days,"unique_users":users,"searches":searches,"product_views":views,"order_clicks":clicks,"completed_orders":completed,"conversion_rate":round(completed/searches*100,2) if searches else 0}

@app.get("/analytics/demand")
def analytics_demand(days: int = 30, limit: int = 20, db: Session = Depends(get_db)):
    since = datetime.utcnow() - timedelta(days=max(1, min(days, 90))); limit = max(1, min(limit, 100))
    def norm(value):
        value = (value or "").strip().lower().replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه")
        value = " ".join(value.split())
        return {"ادیداس":"adidas", "آدیداس":"adidas", "نایک":"nike", "نايك":"nike"}.get(value, value)
    rows = db.query(models.ActivityEvent.search_text, models.ActivityEvent.category, models.ActivityEvent.user_id).filter(models.ActivityEvent.created_at >= since, models.ActivityEvent.event_type.in_(["search", "search_no_result"]), models.ActivityEvent.search_text.isnot(None)).all()
    groups = {}
    for text_value, category, user_id in rows:
        key = (norm(text_value), category or "")
        item = groups.setdefault(key, {"query": text_value, "category": category, "search_count": 0, "users": set()})
        item["search_count"] += 1
        if user_id is not None: item["users"].add(user_id)
    result = [{"query": x["query"], "category": x["category"], "search_count": x["search_count"], "unique_users": len(x["users"])} for x in groups.values()]
    result.sort(key=lambda x: x["search_count"], reverse=True)
    return result[:limit]


def require_analytics_token(x_analytics_token: str | None = Header(default=None)):
    expected = os.environ.get("ANALYTICS_TOKEN")
    if not expected or x_analytics_token != expected:
        raise HTTPException(status_code=401, detail="Analytics authorization required")

@app.get("/analytics/admins")
def analytics_admins(days: int = 30, db: Session = Depends(get_db), _auth=Depends(require_analytics_token)):
    days = max(1, min(days, 90)); since = datetime.utcnow() - timedelta(days=days)
    admin_ids = {r[0] for r in db.query(models.Product.created_by_admin_id).filter(models.Product.created_by_admin_id.isnot(None)).all()}
    result = []
    for admin_id in sorted(admin_ids):
        created = db.query(models.Product).filter(models.Product.created_by_admin_id == admin_id, models.Product.created_at >= since).count()
        referred = db.query(models.ActivityEvent).filter(models.ActivityEvent.user_id == admin_id, models.ActivityEvent.event_type.in_(["order_referred", "click_order"]), models.ActivityEvent.created_at >= since).count()
        completed = db.query(models.ActivityEvent).filter(models.ActivityEvent.user_id == admin_id, models.ActivityEvent.event_type == "order_completed", models.ActivityEvent.created_at >= since).count()
        username = next((r[0] for r in db.query(models.Product.created_by_admin_username).filter(models.Product.created_by_admin_id == admin_id, models.Product.created_by_admin_username.isnot(None)).limit(1).all()), None)
        result.append({"admin_id": admin_id, "username": username, "products_created": created, "referrals": referred, "completed_orders": completed})
    return {"days": days, "admins": result}

@app.get("/analytics/products")
def analytics_products(days: int = 30, limit: int = 50, db: Session = Depends(get_db), _auth=Depends(require_analytics_token)):
    days = max(1, min(days, 90)); limit = max(1, min(limit, 200)); since = datetime.utcnow() - timedelta(days=days)
    result = []
    for product in db.query(models.Product).all():
        events = db.query(models.ActivityEvent).filter(models.ActivityEvent.product_id == product.id, models.ActivityEvent.created_at >= since)
        views = events.filter(models.ActivityEvent.event_type == "view_product").count(); clicks = events.filter(models.ActivityEvent.event_type == "click_order").count(); completed = events.filter(models.ActivityEvent.event_type == "order_completed").count()
        if views or clicks or completed:
            result.append({"product_id": product.id, "name": product.name, "category": product.category, "price_usd": product.price_usd, "views": views, "order_clicks": clicks, "completed_orders": completed, "owner_admin_id": product.owner_admin_id, "owner_admin_username": product.created_by_admin_username})
    result.sort(key=lambda x: (x["order_clicks"], x["views"]), reverse=True)
    return {"days": days, "products": result[:limit]}
