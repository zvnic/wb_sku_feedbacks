import os
from pydantic_settings import BaseSettings
import logging


class Settings(BaseSettings):
    database_url: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/wb_feedbacks")
    default_rating_threshold: int = 3
    default_days_period: int = 3
    log_level: str = os.getenv("LOG_LEVEL", "DEBUG")

    class Config:
        env_file = ".env"


settings = Settings()


def setup_logging():
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('logs/app.log', encoding='utf-8')
        ]
    )

    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    logging.getLogger('aiohttp.access').setLevel(logging.WARNING)