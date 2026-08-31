from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Header
from fastapi.responses import FileResponse
from pathlib import Path
import os
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text
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


ensure_schema()

app = FastAPI(title="Tehran Inventory API", version="1.0.0")
RAILWAY_PHOTO_DIR = Path("/data/photos")
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
