#!/usr/bin/env bash
# Первичное развёртывание ВольтЛиния CRM на сервере (Ubuntu/Debian с Docker).
# Репозиторий приватный, поэтому запуск через токен GitHub (Settings → Developer settings → Tokens, права: repo):
#   GH_TOKEN=ghp_xxx bash <(curl -fsSL -H "Authorization: token ghp_xxx" https://raw.githubusercontent.com/konstantinkleman/voltliniya-crm/main/deploy.sh)
# Повторный запуск безопасен: обновит код и пересоберёт контейнеры, .env не тронет.
set -euo pipefail

DIR=/opt/voltliniya-crm
REPO=https://${GH_TOKEN:+$GH_TOKEN@}github.com/konstantinkleman/voltliniya-crm
DOMAIN=${DOMAIN:-crm.voltliniya.ru}
ADMIN_EMAIL=${ADMIN_EMAIL:-voltliniya@yandex.ru}

command -v docker >/dev/null || { echo "Нужен Docker: curl -fsSL https://get.docker.com | sh"; exit 1; }
command -v git >/dev/null || apt-get install -y git

if [ -d "$DIR/.git" ]; then
  [ -n "${GH_TOKEN:-}" ] && git -C "$DIR" remote set-url origin "$REPO"
  git -C "$DIR" pull --ff-only
else
  git clone "$REPO" "$DIR"
fi
# токен остаётся в .git/config только для git pull при обновлениях; доступ к каталогу — только root
chmod 700 "$DIR"
cd "$DIR"

# 1. Освободить порты 80/443: их держит Caddy старой системы voltline-warehouse.
#    Останавливаем все контейнеры старой системы (боевой и тестовый стенды). Тома с данными не трогаем —
#    41 позиция номенклатуры останется в Postgres и будет перенесена при запуске склада.
OLD=$(docker ps -q --filter name=voltline-warehouse || true)
if [ -n "$OLD" ]; then
  echo "Останавливаю старую систему voltline-warehouse (данные в томах сохраняются)…"
  docker stop $OLD >/dev/null || true
fi
# tg-relay и боты старой системы порты 80/443 не занимают, их не трогаем.
if ss -ltn | grep -qE ':(80|443) '; then
  echo "Порты 80/443 всё ещё заняты:"; ss -ltnp | grep -E ':(80|443) ' || true
  echo "Останавливаю контейнеры, которые их публикуют…"
  for c in $(docker ps -q); do
    if docker port "$c" 2>/dev/null | grep -qE ':(80|443)$'; then docker stop "$c" >/dev/null || true; fi
  done
fi

# 2. .env — создаётся один раз со случайными секретами.
if [ ! -f .env ]; then
  PG=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 24)
  JWT=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 48)
  ADM=$(tr -dc A-Za-z0-9 </dev/urandom | head -c 12)
  cat > .env <<EOF
DOMAIN=$DOMAIN
POSTGRES_DB=crm
POSTGRES_USER=crm
POSTGRES_PASSWORD=$PG
JWT_SECRET=$JWT
ADMIN_EMAIL=$ADMIN_EMAIL
ADMIN_PASSWORD=$ADM
ADMIN_NAME=Константин
CREW_SHARE=0.55
HTTP_PORT=80
HTTPS_PORT=443
EOF
  chmod 600 .env
  echo
  echo "=============================================="
  echo " Создан .env. Вход в CRM:"
  echo "   https://$DOMAIN"
  echo "   логин:  $ADMIN_EMAIL"
  echo "   пароль: $ADM"
  echo " (пароль можно сменить в Настройках после входа)"
  echo "=============================================="
  echo
fi

# 3. Сборка и запуск.
docker compose up -d --build
sleep 5
docker compose ps
echo
echo "Проверка API:"; curl -s http://127.0.0.1/api/health || curl -sk https://127.0.0.1/api/health || true; echo
echo "Готово. Сертификат Let's Encrypt выпустится автоматически, когда DNS $DOMAIN укажет на этот сервер."
echo "Логи: cd $DIR && docker compose logs -f --tail=100"
