from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, UniqueConstraint
from sqlalchemy.sql import func
from app.database import Base


class Feedback(Base):
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    feedback_id = Column(String, unique=True, index=True, nullable=False)
    nm_id = Column(Integer, index=True, nullable=False)
    imt_id = Column(Integer, index=True, nullable=False)
    user_name = Column(String, nullable=True)
    text = Column(Text, nullable=True)
    pros = Column(Text, nullable=True)
    cons = Column(Text, nullable=True)
    product_valuation = Column(Integer, nullable=False)
    color = Column(String, nullable=True)
    size = Column(String, nullable=True)
    created_date = Column(DateTime, nullable=False)
    updated_date = Column(DateTime, nullable=False)
    has_photo = Column(Boolean, default=False)
    has_video = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint('feedback_id', name='uq_feedback_id'),)