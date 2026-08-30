from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class ProductCreate(BaseModel):
    name: str
    description: Optional[str] = None
    ai_description: Optional[str] = None
    price_usd: float
    size: Optional[str] = None
    weight_grams: Optional[float] = None
    location: Optional[str] = None
    category: Optional[str] = None
    owner_admin_id: Optional[int] = None
    created_by_admin_id: Optional[int] = None
    telegram_file_id: Optional[str] = None
    original_photo_path: Optional[str] = None
    telegram_link_1: Optional[str] = None
    telegram_link_2: Optional[str] = None

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    ai_description: Optional[str] = None
    price_usd: Optional[float] = None
    size: Optional[str] = None
    weight_grams: Optional[float] = None
    location: Optional[str] = None
    category: Optional[str] = None
    owner_admin_id: Optional[int] = None
    created_by_admin_id: Optional[int] = None
    telegram_file_id: Optional[str] = None
    original_photo_path: Optional[str] = None
    telegram_link_1: Optional[str] = None
    telegram_link_2: Optional[str] = None

class ProductResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    ai_description: Optional[str] = None
    price_usd: float
    size: Optional[str] = None
    weight_grams: Optional[float] = None
    location: Optional[str] = None
    category: Optional[str] = None
    owner_admin_id: Optional[int] = None
    created_by_admin_id: Optional[int] = None
    telegram_file_id: Optional[str] = None
    original_photo_path: Optional[str] = None
    telegram_link_1: Optional[str] = None
    telegram_link_2: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
