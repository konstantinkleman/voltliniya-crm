#!/usr/bin/env bash
# Первичное развёртывание ВольтЛиния CRM на сервере (Ubuntu/Debian с Docker).
# Репозиторий приватный, поэтому запуск через токен GitHub (Settings → Developer settings → Tokens, права: repo):
#   GH_TOKEN=ghp_xxx bash <(curl -fsSL -H "Authorization: token ghp_xxx" https://raw.githubusercontent.com/konstantinkleman/voltliniya-crm/main/deploy.sh)
# Повторный запуск безопасен: обновит код и пересоберёт контейнеры, .env не тронет.
set -euo pipefail
trap 'echo "Ошибка на строке $LINENO: $BASH_COMMAND" >&2' ERR

DIR=/opt/voltliniya-crm
REPO=https://${GH_TOKEN:+$GH_TOKEN@}github.com/konstantinkleman/voltliniya-crm
DOMAIN=${DOMAIN:-crm.voltliniya.ru}
ADMIN_EMAIL=${ADMIN_EMAIL:-voltliniya@yandex.ru}

command -v docker >/dev/null || { echo "Нужен Docker: curl -fsSL https://get.docker.com | sh"; exit 1; }
command -v git >/dev/null || apt-get install -y git

# Обновление кода. Скрипт перезаписывает сам себя при git pull, поэтому после обновления
# перезапускаемся заново (bash читает файл по ходу выполнения, иначе выполнение обрывается).
if [ -z "${DEPLOY_RESTARTED:-}" ]; then
  if [ -d "$DIR/.git" ]; then
    [ -n "${GH_TOKEN:-}" ] && git -C "$DIR" remote set-url origin "$REPO"
    git -C "$DIR" pull --ff-only
  else
    git clone "$REPO" "$DIR"
  fi
  DEPLOY_RESTARTED=1 exec bash "$DIR/deploy.sh"
fi
# токен остаётся в .git/config только для git pull при обновлениях; доступ к каталогу — только root
chmod 700 "$DIR"
cd "$DIR"

# 1. Освободить порты 80/443: их держит Caddy старой системы voltline-warehouse.
#    Останавливаем контейнеры старой системы. Тома с данными не трогаем.
set +e
echo "Останавливаю старую систему voltline-warehouse (данные в томах сохраняются)…"
docker ps --format '{{.Names}}' | grep -E '^voltline-warehouse' | xargs -r docker stop
for c in $(docker ps -q); do
  if docker port "$c" 2>/dev/null | grep -qE ':(80|443)$'; then
    echo "Останавливаю $(docker inspect -f '{{.Name}}' "$c") — занимает 80/443"; docker stop "$c"
  fi
done
echo "Порты 80/443 после остановки:"; ss -ltnp | grep -E ':(80|443) ' || echo "свободны"
set -e

# 2. .env — создаётся один раз со случайными секретами.
if [ ! -f .env ]; then
  rnd() { head -c 64 /dev/urandom | base64 | tr -dc A-Za-z0-9 | head -c "$1" || true; }
  PG=$(rnd 24); JWT=$(rnd 48); ADM=$(rnd 12)
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
# Распознавание накладных по фото: вставьте ключ OpenAI и перезапустите deploy.sh
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o
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

# 2b. Новые переменные в существующем .env (без перезаписи значений).
grep -q '^OPENAI_API_KEY=' .env || printf '\n# Распознавание накладных по фото: вставьте ключ OpenAI и перезапустите deploy.sh\nOPENAI_API_KEY=\nOPENAI_MODEL=gpt-4o\n' >> .env

# 2c. Версия сборки = хеш коммита: по ней открытые вкладки CRM понимают, что надо перезагрузиться.
sed -i '/^APP_VERSION=/d' .env
echo "APP_VERSION=$(git rev-parse --short HEAD 2>/dev/null || date +%s)" >> .env

# 2a. Авито и Telegram: дописать недостающие ключи в существующий .env (повторный запуск ничего не перезапишет).
#     Токен Telegram берётся из релея заявок с сайта (/opt/tg-relay/.env) — тот же бот @Voltliniya_zayavki_bot.
addkey() { grep -q "^$1=" .env || printf '%s=%s\n' "$1" "$2" >> .env; }
TG_TOK=""
[ -f /opt/tg-relay/.env ] && TG_TOK=$(grep '^TG_TOKEN=' /opt/tg-relay/.env | cut -d= -f2-)
addkey TELEGRAM_BOT_TOKEN "$TG_TOK"
addkey TELEGRAM_CHAT_ID "838171850"
addkey AVITO_WEBHOOK_SECRET "$(head -c 48 /dev/urandom | base64 | tr -dc A-Za-z0-9 | head -c 40 || true)"
addkey AVITO_BOT_ENABLED "1"
addkey AVITO_CLIENT_ID ""
addkey AVITO_CLIENT_SECRET ""
addkey ANTHROPIC_API_KEY ""
addkey ANTHROPIC_MODEL "claude-sonnet-5-5"
for k in AVITO_CLIENT_ID AVITO_CLIENT_SECRET ANTHROPIC_API_KEY TELEGRAM_BOT_TOKEN; do
  grep -q "^$k=.\+" .env || echo "ВНИМАНИЕ: в .env пусто $k — впишите значение и повторите: docker compose up -d --build"
done

# 3. Сборка и запуск.
docker compose up -d --build
sleep 5
docker compose ps
echo
echo "Проверка API:"; curl -s http://127.0.0.1/api/health || curl -sk https://127.0.0.1/api/health || true; echo
echo "Готово. Сертификат Let's Encrypt выпустится автоматически, когда DNS $DOMAIN укажет на этот сервер."
echo "Логи: cd $DIR && docker compose logs -f --tail=100"
