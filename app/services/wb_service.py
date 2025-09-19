import aiohttp
import asyncio
from typing import Optional, Dict, List
from datetime import datetime, timedelta
import binascii
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.feedback import Feedback

logger = logging.getLogger(__name__)


class WBService:
    def __init__(self):
        self.session = None

    def _parse_date(self, date_str: str) -> datetime:
        if not date_str:
            return datetime.now()
        if date_str.endswith('Z'):
            date_str = date_str.replace('Z', '+00:00')
        dt = datetime.fromisoformat(date_str)
        return dt.replace(tzinfo=None)

    async def _get_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            )
        return self.session

    def _calculate_vol_part(self, nm_id: int) -> tuple[str, str]:
        s = str(nm_id)

        # Для разных длин номеров могут быть разные правила
        if len(s) <= 6:
            # Короткие номера
            vol = s[:3] if len(s) >= 3 else s
            part = s[:5] if len(s) >= 5 else s
        elif len(s) <= 8:
            # Стандартные номера (как в примере)
            vol = s[:3]
            part = s[:5]
        else:
            # Длинные номера (9+ цифр) - возможно другая логика
            vol = s[:4]  # первые 4 цифры
            part = s[:6]  # первые 6 цифр

        return f"vol{vol}", f"part{part}"

    def _calculate_basket_shard(self, nm_id: int, shards_count: int = 20) -> int:
        h = binascii.crc32(str(nm_id).encode()) & 0xffffffff
        return h % shards_count

    async def _try_basket_shards(self, nm_id: int, path: str) -> Optional[int]:
        session = await self._get_session()

        logger.info(f"Поиск шарда для nm_id {nm_id}, путь: {path}")

        # Попробуем больше шардов (WB может иметь 100+ серверов)
        for shard in range(100):
            host = f"basket-{shard:02d}.wbbasket.ru"
            url = f"https://{host}{path}"

            try:
                async with session.get(url) as response:
                    logger.debug(f"Шард {shard}: статус {response.status}")
                    if response.status == 200:
                        logger.info(f"Найден рабочий шард {shard} для nm_id {nm_id}")
                        return shard
            except Exception as e:
                logger.debug(f"Ошибка при проверке шарда {shard}: {str(e)}")
                continue

        # Попробуем также static-basket хосты
        logger.info(f"Проверяем static-basket хосты для nm_id {nm_id}")
        for shard in range(50):
            host = f"static-basket-{shard:02d}.wbbasket.ru"
            url = f"https://{host}{path}"

            try:
                async with session.get(url) as response:
                    logger.debug(f"Static-basket {shard}: статус {response.status}")
                    if response.status == 200:
                        logger.info(f"Найден рабочий static-basket шард {shard} для nm_id {nm_id}")
                        return shard
            except Exception as e:
                logger.debug(f"Ошибка при проверке static-basket {shard}: {str(e)}")
                continue

        logger.warning(f"Не найден рабочий шард для nm_id {nm_id} среди basket-00..basket-99 и static-basket-00..static-basket-49")
        return None

    async def get_product_info(self, nm_id: int) -> Optional[Dict]:
        vol, part = self._calculate_vol_part(nm_id)
        path = f"/{vol}/{part}/{nm_id}/info/ru/card.json"

        shard = await self._try_basket_shards(nm_id, path)
        if shard is None:
            return None

        session = await self._get_session()
        host = f"basket-{shard:02d}.wbbasket.ru"
        url = f"https://{host}{path}"

        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Получена информация о товаре {nm_id}, imt_id: {data.get('imt_id')}")
                    return data
                else:
                    logger.error(f"Ошибка получения информации о товаре {nm_id}: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Исключение при получении информации о товаре {nm_id}: {str(e)}")
            return None

    async def get_feedbacks(self, nm_id: int, product_info: Dict) -> Optional[Dict]:
        session = await self._get_session()

        # Сначала пробуем основной imt_id
        imt_id = product_info.get('imt_id')
        if imt_id:
            logger.info(f"Проверяем отзывы для основного imt_id {imt_id}")
            data = await self._fetch_feedbacks_by_id(session, imt_id)
            if data and (data.get('feedbacks') or data.get('feedbackCount', 0) > 0):
                return data

        # Если нет отзывов у основного imt_id, пробуем nm_id напрямую
        logger.info(f"Проверяем отзывы по nm_id {nm_id}")
        data = await self._fetch_feedbacks_by_id(session, nm_id)
        if data and (data.get('feedbacks') or data.get('feedbackCount', 0) > 0):
            return data

        # Если товар имеет несколько цветов, проверяем отзывы у связанных товаров
        colors = product_info.get('colors', [])
        if len(colors) > 1:
            logger.info(f"Товар имеет {len(colors)} цветов, проверяем отзывы у связанных товаров")
            for color_nm_id in colors[:5]:  # Проверяем первые 5 цветов
                if color_nm_id != nm_id:
                    logger.info(f"Проверяем отзывы для связанного товара {color_nm_id}")
                    data = await self._fetch_feedbacks_by_id(session, color_nm_id)
                    if data and (data.get('feedbacks') or data.get('feedbackCount', 0) > 0):
                        logger.info(f"Найдены отзывы у связанного товара {color_nm_id}")
                        return data

        logger.warning(f"Отзывы не найдены ни для nm_id {nm_id}, ни для связанных товаров")
        return None

    async def _fetch_feedbacks_by_id(self, session, feedback_id: int) -> Optional[Dict]:
        # Пробуем разные хосты для API отзывов
        hosts = ["feedbacks1.wb.ru", "feedbacks2.wb.ru"]

        for host in hosts:
            url = f"https://{host}/feedbacks/v2/{feedback_id}"
            try:
                headers = {
                    'Accept': 'application/json',
                    'Accept-Encoding': 'gzip, deflate'
                }
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        feedbacks = data.get('feedbacks') or []
                        feedbackCount = data.get('feedbackCount', 0)
                        logger.debug(f"API отзывов {host} {feedback_id}: количество={len(feedbacks)}, feedbackCount={feedbackCount}")

                        # Если найдены отзывы, возвращаем результат
                        if feedbacks or feedbackCount > 0:
                            logger.info(f"Найдены отзывы на {host} для {feedback_id}: {feedbackCount} отзывов")
                            return data
                    else:
                        logger.debug(f"Ошибка получения отзывов {host} для {feedback_id}: {response.status}")
            except Exception as e:
                logger.debug(f"Исключение при получении отзывов {host} для {feedback_id}: {str(e)}")
                continue

        return None

    async def save_bad_feedbacks(
        self,
        db: AsyncSession,
        feedbacks_data: Dict,
        nm_id: int,
        imt_id: int,
        min_rating: int,
        days_period: int
    ) -> int:
        feedbacks_list = feedbacks_data.get('feedbacks', [])
        if not feedbacks_list:
            return 0

        cutoff_date = datetime.now() - timedelta(days=days_period)
        saved_count = 0

        logger.info(f"Фильтрация отзывов: min_rating={min_rating}, days_period={days_period}, cutoff_date={cutoff_date}")

        for feedback in feedbacks_list:
            try:
                rating = feedback.get('productValuation', 0)
                created_date_str = feedback.get('createdDate', '')
                created_date = self._parse_date(created_date_str)

                logger.debug(f"Отзыв ID: {feedback.get('id')}, рейтинг: {rating}, дата: {created_date_str}")

                if rating > min_rating:
                    logger.debug(f"Пропускаем отзыв {feedback.get('id')}: рейтинг {rating} > {min_rating}")
                    continue

                if created_date < cutoff_date:
                    logger.debug(f"Пропускаем отзыв {feedback.get('id')}: дата {created_date} < {cutoff_date}")
                    continue

                stmt = select(Feedback).where(Feedback.feedback_id == feedback.get('id'))
                result = await db.execute(stmt)
                existing_feedback = result.scalar_one_or_none()

                if existing_feedback:
                    logger.debug(f"Отзыв {feedback.get('id')} уже существует в БД")
                    continue

                logger.info(f"Сохраняем плохой отзыв: ID={feedback.get('id')}, рейтинг={rating}, дата={created_date}")

                new_feedback = Feedback(
                    feedback_id=feedback.get('id'),
                    nm_id=nm_id,
                    imt_id=imt_id,
                    user_name=feedback.get('wbUserDetails', {}).get('name', ''),
                    text=feedback.get('text', ''),
                    pros=feedback.get('pros', ''),
                    cons=feedback.get('cons', ''),
                    product_valuation=rating,
                    color=feedback.get('color', ''),
                    size=feedback.get('size', ''),
                    created_date=created_date,
                    updated_date=self._parse_date(feedback.get('updatedDate', '')),
                    has_photo=bool(feedback.get('photos')),
                    has_video=bool(feedback.get('video'))
                )

                db.add(new_feedback)
                saved_count += 1

            except Exception as e:
                logger.error(f"Ошибка при сохранении отзыва {feedback.get('id', 'unknown')}: {str(e)}")
                continue

        try:
            await db.commit()
            logger.info(f"Сохранено {saved_count} плохих отзывов для товара {nm_id}")
        except Exception as e:
            await db.rollback()
            logger.error(f"Ошибка при сохранении отзывов в БД: {str(e)}")
            raise

        return saved_count

    async def close(self):
        if self.session:
            await self.session.close()