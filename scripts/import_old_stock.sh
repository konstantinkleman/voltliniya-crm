#!/usr/bin/env bash
# Перенос номенклатуры и остатков из старой системы (voltline-warehouse) в новую CRM.
# Запуск на сервере: bash /opt/voltliniya-crm/scripts/import_old_stock.sh [ID склада в новой системе]
# Старый Postgres поднимается на время выгрузки и снова останавливается. Повторный запуск не дублирует позиции.
set -euo pipefail
cd /opt/voltliniya-crm
OLD=voltline-warehouse-postgres-1
TARGET_WH=${1:-}
OUT=/tmp/old_stock.json

echo "1/3 Поднимаю старую базу…"
docker start $OLD >/dev/null
for i in $(seq 1 20); do docker exec $OLD pg_isready -q 2>/dev/null && break; sleep 1; done

echo "2/3 Выгружаю категории, номенклатуру, остатки…"
docker exec $OLD sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "
select json_build_object(
  '"'"'categories'"'"', (select coalesce(json_agg(row_to_json(c)), '"'"'[]'"'"') from categories c),
  '"'"'products'"'"',   (select coalesce(json_agg(row_to_json(p)), '"'"'[]'"'"') from products p),
  '"'"'warehouses'"'"', (select coalesce(json_agg(row_to_json(w)), '"'"'[]'"'"') from warehouses w),
  '"'"'balances'"'"',   (select coalesce(json_agg(row_to_json(b)), '"'"'[]'"'"') from stock_balances b)
)"' > $OUT
docker stop $OLD >/dev/null
echo "   выгружено: $(python3 -c "import json;d=json.load(open('$OUT'));print(', '.join(f'{k}: {len(v)}' for k,v in d.items()))")"

echo "3/3 Загружаю в новую систему…"
docker compose cp $OUT api:/tmp/old_stock.json
docker compose exec -T api python -m scripts.import_old_stock /tmp/old_stock.json ${TARGET_WH}
