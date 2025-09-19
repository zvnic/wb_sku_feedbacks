# CLAUDE.md

Это файл предоставляет руководство для Claude Code (claude.ai/code) при работе с кодом в этом репозитории.

## Архитектура проекта

Этот проект представляет собой FastAPI веб-приложение с dashboard для мониторинга отзывов товаров Wildberries. Основные компоненты:

### Структура данных и API
- **SKU Processing**: Определение basket-N шарда по алгоритму на основе nmID товара
- **WB API Integration**:
  - Получение информации о товаре: `https://basket-{shard}.wbbasket.ru/vol{vol}/part{part}/{nmId}/info/ru/card.json`
  - Получение отзывов: `https://feedbacks1.wb.ru/feedbacks/v2/{imt_id}`
- **Database**: SQLAlchemy модели для хранения отзывов с дедупликацией
- **Background Tasks**: Периодический сбор отзывов по заданным критериям

### Ключевые функции
- Конвертация nmID в vol/part пути: первые 3 цифры для vol, первые 5 для part
- Определение basket шарда (предположительно через CRC32 или division модуль)
- Фильтрация отзывов по минимальному рейтингу и временному периоду
- Dashboard для визуализации собранных данных

## Docker-окружение

Проект запускается исключительно через Docker Compose:

```bash
# Запуск всех сервисов
docker-compose up -d

# Просмотр логов
docker-compose logs -f

# Остановка
docker-compose down

# Пересборка при изменениях
docker-compose up --build
```

## База данных

Используется SQLAlchemy для ORM:
- Модель для хранения отзывов с уникальными ограничениями
- Миграции через Alembic
- PostgreSQL как основная БД

## Структура входных параметров

Dashboard принимает:
1. **SKU** (nmID товара Wildberries)
2. **Минимальная оценка** (по умолчанию 3 звезды)
3. **Период сбора** (по умолчанию 3 дня)

## API Endpoints

- `GET /` - Dashboard интерфейс
- `POST /monitor` - Запуск мониторинга товара
- `GET /feedbacks/{sku}` - Получение сохраненных отзывов
- `GET /health` - Проверка состояния сервиса

## Логирование и обработка ошибок

- Структурированное логирование через loguru или стандартный logging
- Обработка ошибок API Wildberries (rate limiting, недоступность)
- Валидация входных данных
- Monitoring готовности базы данных

## Тестирование

```bash
# Запуск тестов в Docker
docker-compose exec app pytest

# Тесты с покрытием
docker-compose exec app pytest --cov=app
```

## Разработка

Для локальной разработки используйте Docker Compose с volume mounting для автоматической перезагрузки кода.