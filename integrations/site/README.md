# Заявки с сайта voltliniya.ru → CRM

Сайт лежит на виртуальном хостинге Timeweb, форма «Заявка на расчёт» отправляется на `/send.php`.

1. Загрузить `crm-intake.php` в ту же папку, что и `send.php`.
2. В `crm-intake.php` вписать токен: строка `INTAKE_TOKEN` из `/opt/voltliniya-crm/.env` на сервере CRM
   (`grep INTAKE_TOKEN /opt/voltliniya-crm/.env`).
3. В `send.php` после отправки в Telegram добавить:

```php
require_once __DIR__ . '/crm-intake.php';
vl_send_to_crm($_POST);
```

Источник определяется по UTM-меткам страницы (Директ, SMS, поиск, другое), площадь и ответы формы
попадают в заявку, повтор с того же телефона пишется в историю открытой заявки, бот (поле `website`) отсекается.
Сбой CRM не ломает форму — только запись в лог хостинга.
