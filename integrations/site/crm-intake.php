<?php
/**
 * ВольтЛиния: отправка заявки с сайта в CRM (crm.voltliniya.ru).
 *
 * Как подключить — в send.php, ПОСЛЕ того как заявка ушла в Telegram, две строки:
 *
 *     require_once __DIR__ . '/crm-intake.php';
 *     vl_send_to_crm($_POST);
 *
 * Telegram всегда первый и не зависит от CRM: этот код вызывается после него, ошибки и таймауты CRM
 * гасятся внутри и только пишутся в лог хостинга (error_log). Ожидание CRM — не больше 5 секунд.
 *
 * Токен не нужен: адрес /api/intake/site принимает только поля формы (как и сама публичная форма).
 */

const VL_CRM_URL = 'https://crm.voltliniya.ru/api/intake/site';

// Подписи полей формы «Заявка на расчёт» — для текста заявки в CRM
const VL_FIELD_LABELS = [
    'object_type' => 'Объект',
    'area'        => 'Площадь, м²',
    'stage'       => 'Стадия ремонта',
    'budget'      => 'Бюджет на работы',
    'comment'     => 'Комментарий',
];

/** UTM-метки и yclid из адреса страницы: «https://voltliniya.ru/?utm_source=yandex&…» → массив. */
function vl_utm_from_url(?string $url): array
{
    if (!$url) {
        return [];
    }
    $query = parse_url($url, PHP_URL_QUERY);
    if (!$query) {
        return [];
    }
    parse_str($query, $q);
    $out = [];
    foreach (['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'yclid'] as $k) {
        if (!empty($q[$k]) && is_string($q[$k])) {
            $out[$k] = mb_substr($q[$k], 0, 200);
        }
    }
    return $out;
}

/** Собирает заявку из полей формы и отправляет в CRM. Возвращает ответ CRM или null при ошибке. */
function vl_send_to_crm(array $post): ?array
{
    try {
        // ловушка для ботов: скрытое поле website заполняют только они
        if (!empty($post['website'])) {
            return null;
        }
        $s = function ($k) use ($post) {
            return isset($post[$k]) && is_string($post[$k]) ? trim($post[$k]) : '';
        };

        // текст заявки: все заполненные поля формы с подписями
        $lines = ['Заявка с сайта'];
        foreach (VL_FIELD_LABELS as $k => $label) {
            if ($s($k) !== '') {
                $lines[] = $label . ': ' . $s($k);
            }
        }

        // страница формы (скрытое поле page) и откуда пришли; метки — с адреса страницы, иначе из Referer
        $page = $s('page');
        $referer = $_SERVER['HTTP_REFERER'] ?? '';
        $utm = vl_utm_from_url($page) ?: vl_utm_from_url($referer);

        $area = str_replace(',', '.', $s('area'));
        $data = array_merge([
            'name'     => $s('name') ?: null,
            'phone'    => $s('phone') ?: null,
            'message'  => implode("\n", $lines),
            'area_m2'  => is_numeric($area) && (float)$area > 0 ? (float)$area : null,
            'page'     => $page ? mb_substr($page, 0, 300) : ($referer ? mb_substr($referer, 0, 300) : null),
            // откуда посетитель пришёл на сайт (поисковик и т.п.) — если форма передаёт его в поле referrer
            'referrer' => $s('referrer') ?: null,
        ], $utm);
        $data = array_filter($data, function ($v) { return $v !== null && $v !== ''; });

        $ch = curl_init(VL_CRM_URL);
        curl_setopt_array($ch, [
            CURLOPT_POST           => true,
            CURLOPT_POSTFIELDS     => json_encode($data, JSON_UNESCAPED_UNICODE),
            CURLOPT_HTTPHEADER     => ['Content-Type: application/json'],
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CONNECTTIMEOUT => 3,
            CURLOPT_TIMEOUT        => 5,
        ]);
        $body = curl_exec($ch);
        $code = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $err = curl_error($ch);
        curl_close($ch);
        if ($body === false || $code !== 200) {
            error_log('crm-intake: CRM ответила ' . $code . ' ' . $err . ' ' . mb_substr((string)$body, 0, 300));
            return null;
        }
        return json_decode($body, true);
    } catch (Throwable $e) {
        error_log('crm-intake: ' . $e->getMessage());
        return null;
    }
}
