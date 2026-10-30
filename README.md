# Monster Islands — Beta 1.0 (Playable Art Edition)

Вертикальный Telegram Mini App: процедурная тайловая карта с коллизиями, анимированная ходьба персонажа (4 направления и 4 кадра), декорации и постройки, монстры-спутники, кейсы, инвентарь, рынок, сохранение острова. Сервер FastAPI + SQLite (для тестов), Telegram-бот на aiogram.

## Локально (Windows PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:DEV_DEMO="1"
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Зайди на http://127.0.0.1:8000. Перед публичным запуском выключи DEV_DEMO, задай BOT_TOKEN и WEBAPP_URL (HTTPS), настрой постоянное хранилище для базы данных и запусти отдельно `python bot.py`. Не используй эфемерный SQLite на Render без persistent disk.

## Статус

Это запускаемая beta-сборка, **не готовая коммерческая MMO**. Карта нарисована программно; объём создаётся пиксельными спрайтами и тенями, это 2D, не 3D-модели. Внутри Telegram на физических телефонах не тестировалась.

Основная структура сервера и часть графических ресурсов перенесены из Monster Islands V1.3. Примерные игровые сцены и дополнительные текстуры из загруженного Phaser RPG Template сохранены как reference, но работающий клиент остаётся Canvas, а не Phaser.
