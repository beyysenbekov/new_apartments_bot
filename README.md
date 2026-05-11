# 🏢 Krisha.kz Monitor Bot

Telegram-бот для отслеживания новых объявлений о **продаже квартир в Алматы** на сайте krisha.kz.

---

## ⚡ Быстрый старт

### 1. Установи Python
Нужен Python **3.10+**. Проверь версию:
```bash
python --version
```

### 2. Установи зависимости
```bash
pip install -r requirements.txt
```

### 3. Укажи токен бота

**Способ А — через переменную окружения (рекомендуется):**
```bash
# Windows (PowerShell)
$env:BOT_TOKEN="1234567890:AAABBBCCCDDDEEE..."

# Linux / macOS
export BOT_TOKEN="1234567890:AAABBBCCCDDDEEE..."
```

**Способ Б — прямо в коде:**
Открой `bot.py` и замени строку:
```python
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬ_СВОЙ_ТОКЕН_ЗДЕСЬ")
```
на:
```python
BOT_TOKEN = "1234567890:AAABBBCCCDDDEEE..."
```

### 4. Запусти бота
```bash
python bot.py
```

---

## 🤖 Как получить токен у @BotFather

1. Открой Telegram и найди **@BotFather**
2. Напиши `/newbot`
3. Придумай имя и username для бота
4. Скопируй полученный токен (вида `1234567890:AAABBB...`)

---

## 📋 Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и список команд |
| `/setprice 45000000` | Установить макс. цену в тенге |
| `/rooms` | Выбрать количество комнат |
| `/start_monitor` | Запустить мониторинг |
| `/stop_monitor` | Остановить мониторинг |
| `/status` | Текущие настройки |
| `/check` | Проверить прямо сейчас |
| `/help` | Справка |

---

## 🔄 Как это работает

1. Каждые **15 минут** бот заходит на krisha.kz
2. Ищет квартиры в **Алматы** дешевле твоей цены
3. Сравнивает с уже виденными объявлениями
4. Отправляет **только новые** — с фото, ценой и ссылкой

---

## 🛠 Структура файлов

```
krisha_bot/
├── bot.py              # Основной код бота
├── requirements.txt    # Зависимости
├── README.md           # Это руководство
├── bot.log             # Логи (создаётся автоматически)
└── user_data.json      # Данные пользователей (создаётся автоматически)
```

---

## 🖥 Запуск на сервере (VPS / Linux) — 24/7

Чтобы бот работал постоянно, используй **systemd**:

```ini
# /etc/systemd/system/krishabot.service
[Unit]
Description=Krisha.kz Telegram Bot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/krisha_bot
Environment="BOT_TOKEN=твой_токен_здесь"
ExecStart=/usr/bin/python3 /home/ubuntu/krisha_bot/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable krishabot
sudo systemctl start krishabot
sudo systemctl status krishabot
```

Или просто через **tmux / screen**:
```bash
tmux new -s krishabot
python bot.py
# Ctrl+B, затем D — чтобы отсоединиться
```

---

## ⚠️ Важные замечания

- Krisha.kz иногда защищает от парсинга — бот пропустит цикл и попробует снова
- Данные сохраняются в `user_data.json` — не удаляй этот файл
- Максимум **10 объявлений** за одну проверку (защита от спама)
- История из **500 последних ID** хранится для дедупликации
