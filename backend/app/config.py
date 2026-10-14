from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+psycopg://crm:crm@localhost:5432/crm"
    JWT_SECRET: str = "dev-secret-change-me"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 30
    UPLOAD_DIR: str = "/data/uploads"
    CREW_SHARE: float = 0.55
    ADMIN_EMAIL: str = ""
    ADMIN_PASSWORD: str = ""
    ADMIN_NAME: str = "Директор"
    MAX_UPLOAD_MB: int = 50
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    # Публичный адрес CRM — нужен для вебхука Авито и ссылок в уведомлениях
    PUBLIC_URL: str = "https://crm.voltliniya.ru"

    # Авито Messenger API (кабинет Авито для бизнеса → Интеграции → ключи API)
    AVITO_CLIENT_ID: str = ""
    AVITO_CLIENT_SECRET: str = ""
    # Секретный хвост адреса вебхука: /api/avito/webhook/<AVITO_WEBHOOK_SECRET>
    AVITO_WEBHOOK_SECRET: str = ""
    # Бот-продажник отвечает в чатах Авито сам (1) или только заносит в CRM и уведомляет (0)
    AVITO_BOT_ENABLED: bool = True
    # Сколько часов бот молчит в чате после того, как в нём вручную написал директор
    AVITO_MANUAL_HOLD_HOURS: int = 24
    # Часы ответов бота по Москве: [START; END). Ночные сообщения получают ответ утром в START:00 + 0…SPREAD мин
    AVITO_HOURS_START: int = 9
    AVITO_HOURS_END: int = 23
    AVITO_MORNING_SPREAD_MIN: int = 40
    # Напоминания клиенту, замолчавшему после нашего вопроса: 1-е через 20–26 ч, 2-е через ~3 дня,
    # ещё через AVITO_CLOSE_AFTER_DAYS дней тишины — заявка «Проиграна: не ответил». Отправляются только в окне ниже.
    AVITO_FOLLOWUP_ENABLED: bool = True
    AVITO_FOLLOWUP_HOURS_START: int = 10
    AVITO_FOLLOWUP_HOURS_END: int = 20
    AVITO_CLOSE_AFTER_DAYS: int = 3
    # Алерт «клиент ждёт ответа»: бот не ответил за N минут рабочего времени (сбой) / вы ведёте чат и не ответили за M минут
    AVITO_ALERT_BOT_MIN: int = 15
    AVITO_ALERT_MANUAL_MIN: int = 60

    # Уведомления в Telegram (бот → личный чат директора)
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # Claude API для бота-продажника и еженедельного разбора чатов
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-5-5"
    # Еженедельный разбор переписок: день недели (0 = понедельник) и час по Москве
    AVITO_REVIEW_WEEKDAY: int = 0
    # Фоновый обработчик очереди бота (отключается в тестах, там очередь крутится вручную)
    AVITO_WORKER_ENABLED: bool = True
    AVITO_REVIEW_HOUR_MSK: int = 9


settings = Settings()
