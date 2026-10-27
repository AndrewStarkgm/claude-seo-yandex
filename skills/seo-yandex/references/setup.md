# Настройка доступа к API Яндекса

Один OAuth-токен работает для Вебмастера и Метрики. Wordstat API требует отдельного одобрения доступа.

## 1. Приложение и токен

1. Создайте приложение: https://oauth.yandex.ru/client/new
   - Платформа: «Веб-сервисы», Redirect URI: `https://oauth.yandex.ru/verification_code`
   - Права: **Яндекс.Вебмастер** (`webmaster:hostinfo`, `webmaster:verify`), **Яндекс.Метрика**
     (`metrika:read`). Для Вордстата - доступ запрашивается отдельно (см. п. 3).
2. Получите токен (откройте в браузере, войдя в аккаунт, где подтверждены сайты):
   `https://oauth.yandex.ru/authorize?response_type=token&client_id=<ClientID>`
3. Wordstat API: заявка на доступ через поддержку Яндекса (форма на странице документации Wordstat API).
   После одобрения тот же или отдельный токен передаётся как `Bearer`.

Токен живёт год. Аккаунт должен иметь доступ к сайтам в Вебмастере и к счётчику Метрики.

## 2. Конфиг

`~/.config/claude-seo/yandex-api.json` (права 600):
```json
{
  "oauth_token": "y0_...",
  "wordstat_token": "",
  "metrika_counter_id": 12345678,
  "default_host": "https://example.ru"
}
```
Или переменные окружения: `YANDEX_OAUTH_TOKEN`, `YANDEX_WORDSTAT_TOKEN`, `YANDEX_METRIKA_COUNTER`,
`YANDEX_DEFAULT_HOST`.

## 3. Проверка

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/claude-seo" run yandex_auth.py --check
```
Ожидается `webmaster ok`, `metrika ok`; `wordstat` - `ok` только при одобренном доступе.

Никогда не вставляйте токен в чат, отчёты, URL или коммиты.
