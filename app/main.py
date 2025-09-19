from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from datetime import datetime, timedelta
import logging
import os

from app.database import get_db, engine
from app.models.feedback import Feedback, Base
from app.services.wb_service import WBService
from app.config import settings, setup_logging

os.makedirs('logs', exist_ok=True)
setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="WB Feedback Monitor", description="Мониторинг отзывов товаров Wildberries")

templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.post("/monitor")
async def monitor_product(
    sku: int = Form(...),
    min_rating: int = Form(default=settings.default_rating_threshold, description="Максимальная оценка для плохих отзывов (включительно)"),
    days_period: int = Form(default=settings.default_days_period),
    db: AsyncSession = Depends(get_db)
):
    wb_service = None
    try:
        wb_service = WBService()

        product_info = await wb_service.get_product_info(sku)
        if not product_info:
            await wb_service.close()
            raise HTTPException(status_code=404, detail=f"Товар {sku} не найден. Возможно, неверный SKU или товар удален с площадки.")

        feedbacks_data = await wb_service.get_feedbacks(sku, product_info)
        if not feedbacks_data:
            await wb_service.close()
            raise HTTPException(status_code=404, detail="Отзывы не найдены")

        imt_id = product_info.get("imt_id", sku)  # Fallback to nm_id if no imt_id
        saved_count = await wb_service.save_bad_feedbacks(
            db, feedbacks_data, sku, imt_id, min_rating, days_period
        )

        # Получаем общее количество сохраненных отзывов для этого товара
        from sqlalchemy import select, func
        total_stmt = select(func.count(Feedback.id)).where(Feedback.nm_id == sku)
        total_result = await db.execute(total_stmt)
        total_feedbacks = total_result.scalar()

        await wb_service.close()

        logger.info(f"Сохранено {saved_count} новых плохих отзывов для товара {sku}, всего в базе: {total_feedbacks}")

        return {
            "message": f"Мониторинг запущен для товара {sku}",
            "saved_feedbacks": saved_count,
            "total_feedbacks": total_feedbacks,
            "min_rating": min_rating,
            "days_period": days_period
        }

    except HTTPException:
        # Повторно поднимаем HTTPException без изменений
        raise
    except Exception as e:
        if wb_service:
            await wb_service.close()
        logger.error(f"Ошибка при мониторинге товара {sku}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка обработки: {str(e)}")


@app.get("/feedbacks/{sku}")
async def get_feedbacks(sku: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select

    try:
        stmt = select(Feedback).where(Feedback.nm_id == sku).order_by(Feedback.created_date.desc())
        result = await db.execute(stmt)
        feedbacks = result.scalars().all()

        return {
            "sku": sku,
            "total_feedbacks": len(feedbacks),
            "feedbacks": [
                {
                    "id": f.feedback_id,
                    "rating": f.product_valuation,
                    "text": f.text,
                    "pros": f.pros,
                    "cons": f.cons,
                    "user_name": f.user_name,
                    "color": f.color,
                    "created_date": f.created_date.isoformat(),
                    "has_photo": f.has_photo,
                    "has_video": f.has_video
                }
                for f in feedbacks
            ]
        }

    except Exception as e:
        logger.error(f"Ошибка при получении отзывов для товара {sku}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Ошибка получения данных: {str(e)}")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "wb-feedback-monitor"}