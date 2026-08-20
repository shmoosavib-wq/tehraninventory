from sqlalchemy import Column, Integer, String, Float, Text, DateTime
from sqlalchemy.sql import func
from database import Base

class Product(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    ai_description = Column(Text, nullable=True)
    price_usd = Column(Float, nullable=False)
    size = Column(String, nullable=True)
    weight_grams = Column(Float, nullable=True)
    location = Column(String, nullable=True)
    category = Column(String, nullable=True)
    
    # Telegram photo file_id (from uploaded photo)
    telegram_file_id = Column(String, nullable=True)
    
    # Original photo path (from HTML export)
    original_photo_path = Column(String, nullable=True)
    
    # Telegram links (channels)
    telegram_link_1 = Column(String, nullable=True)
    telegram_link_2 = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
