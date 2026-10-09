# ВольтЛиния CRM

Заявки → объекты → бригады и выплаты → расходы → аналитика. Одна система для директора и прорабов.

Логика системы описана в документе «ВольтЛиния CRM — логика системы» (Claude Docs).

## Состав

- `backend/` — FastAPI + SQLAlchemy + PostgreSQL. REST под `/api`, Swagger по `/api/docs` (только после входа).
- `frontend/` — Vite + React + TypeScript. Отдаётся Caddy, который же проксирует `/api` в бэкенд и выпускает TLS.
- `docker-compose.yml` — три сервиса: `db`, `api`, `web`.

## Запуск на сервере

```bash
git clone https://github.com/konstantinkleman/voltliniya-crm /opt/voltliniya-crm
cd /opt/voltliniya-crm
cp .env.example .env   # заполнить пароли, JWT_SECRET, DOMAIN, ADMIN_*
docker compose up -d --build
```

Обновление: `git pull && docker compose up -d --build`.

Бэкап базы: `docker compose exec db pg_dump -U crm crm | gzip > backup-$(date +%F).sql.gz`.

## Правила денег (из документа логики)

- Бригада получает `CREW_SHARE` (0.55) от стоимости работ по смете + доп. работ. Выплата идёт прорабу с пометкой «бригаде».
- Прораб — фиксированная зарплата; распределяется поровну на его объекты месяца сделки.
- Стоимость клиента по каналу = расходы канала за месяц ÷ сделок канала + общий маркетинг ÷ всех сделок.
- Прибыль объекта = договор − материалы по себестоимости − доля бригады − доля зарплаты прораба − стоимость клиента.

Все расчёты — в `backend/app/finance.py`.
