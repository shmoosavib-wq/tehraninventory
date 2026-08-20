from pydantic import BaseModel
from datetime import datetime
from typing import Optional

# Request schemas
class ProductCreate(BaseModel):
    name: str
    description: Optional[str] = None
    ai_description: Optional[str] = None
    price_usd: float
    size: Optional[str] = None
    weight_grams: Optional[float] = None
    location: Optional[str] = None
    category: Optional[str] = None
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
    telegram_file_id: Optional[str] = None
    original_photo_path: Optional[str] = None
    telegram_link_1: Optional[str] = None
    telegram_link_2: Optional[str] = None

# Response schemas
class ProductResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    ai_description: Optional[str]
    price_usd: float
    size: Optional[str]
    weight_grams: Optional[float]
    location: Optional[str]
    category: Optional[str]
    telegram_file_id: Optional[str]
    original_photo_path: Optional[str]
    telegram_link_1: Optional[str]
    telegram_link_2: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True
