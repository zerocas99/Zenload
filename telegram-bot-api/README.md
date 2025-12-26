# Telegram Local Bot API Server

Этот сервис позволяет отправлять файлы до 2GB через Telegram Bot API (вместо стандартного лимита 50MB).

## Настройка на Railway

### 1. Получить API credentials

1. Перейди на https://my.telegram.org
2. Войди с номером телефона
3. Перейди в "API development tools"
4. Создай приложение и получи `api_id` и `api_hash`

### 2. Создать новый сервис на Railway

1. В проекте Railway нажми "New Service" → "GitHub Repo"
2. Выбери этот репозиторий
3. В настройках сервиса укажи:
   - **Root Directory**: `telegram-bot-api`
   - **Environment Variables**:
     - `TELEGRAM_API_ID` = твой api_id
     - `TELEGRAM_API_HASH` = твой api_hash

### 3. Настроить основной бот

Добавь переменную окружения в основной бот:
```
TELEGRAM_LOCAL_API_URL=http://<service-name>.railway.internal:8081
```

Где `<service-name>` - имя сервиса telegram-bot-api в Railway (например `telegram-bot-api.railway.internal`).

## Преимущества Local Bot API

- Файлы до 2GB (вместо 50MB)
- Быстрее загрузка (файлы не проходят через Telegram сервера)
- Можно использовать локальные пути к файлам
