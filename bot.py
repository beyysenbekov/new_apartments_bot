#!/usr/bin/env python3
"""
Krisha.kz Monitor Bot
Отслеживает новые объявления о продаже квартир в Алматы
и уведомляет пользователя о ценах ниже заданного порога.
"""

import os
import json
import logging
import asyncio
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ─────────────────────────────────────────────
# Настройка логов
# ─────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Конфиг
# ─────────────────────────────────────────────
BOT_TOKEN = "8737332675:AAEELNxtay1ha0ExxrwfoeQE9L_aKAl1InA"
DATA_FILE = Path("user_data.json")
CHECK_INTERVAL_MINUTES = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ─────────────────────────────────────────────
# Хранилище данных (JSON файл)
# ─────────────────────────────────────────────

def load_data() -> dict:
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_user(chat_id: int) -> dict:
    data = load_data()
    uid = str(chat_id)
    if uid not in data:
        data[uid] = {
            "max_price": None,
            "active": False,
            "seen_ids": [],
            "rooms": [],        # [] = любое количество комнат
            "notified_count": 0,
        }
        save_data(data)
    return data[uid]


def save_user(chat_id: int, user: dict):
    data = load_data()
    data[str(chat_id)] = user
    save_data(data)

# ─────────────────────────────────────────────
# Парсер Krisha.kz
# ─────────────────────────────────────────────

def build_url(max_price: int, rooms: list[int] | None = None) -> str:
    """Строим URL для поиска квартир в Алматы дешевле max_price."""
    base = "https://krisha.kz/prodazha/kvartiry/almaty/"
    params = [f"das[price][to]={max_price}", "das[who]=1"]  # who=1 — от хозяев
    if rooms:
        for r in rooms:
            params.append(f"das[live.rooms][]={r}")
    params.append("sort=date")   # сортировка по дате — свежие первые
    return base + "?" + "&".join(params)


def parse_listings(max_price: int, rooms: list[int] | None = None) -> list[dict]:
    """Скрапим первую страницу Krisha.kz и возвращаем список объявлений."""
    url = build_url(max_price, rooms)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Ошибка запроса krisha.kz: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    listings = []

    # Карточки объявлений
    cards = soup.select("div.a-card")
    logger.info(f"Найдено карточек на странице: {len(cards)}")

    for card in cards:
        try:
            # ID объявления
            link_tag = card.select_one("a.a-card__title, a.a-card__image-link, a[href*='/a/show/']")
            if not link_tag:
                continue
            href = link_tag.get("href", "")
            if "/a/show/" not in href:
                continue

            ad_id = href.split("/a/show/")[-1].split("/")[0].split("?")[0]
            full_url = f"https://krisha.kz{href}" if href.startswith("/") else href

            # Заголовок
            title_tag = card.select_one("a.a-card__title, .a-card__title")
            title = title_tag.get_text(strip=True) if title_tag else "Квартира"

            # Цена
            price_tag = card.select_one(".a-card__price")
            price_text = price_tag.get_text(strip=True) if price_tag else "Цена не указана"

            # Площадь и описание
            desc_tag = card.select_one(".a-card__header-left")
            desc = desc_tag.get_text(" ", strip=True) if desc_tag else ""

            # Адрес
            addr_tag = card.select_one(".a-card__subtitle")
            address = addr_tag.get_text(strip=True) if addr_tag else "Алматы"

            # Фото
            img_tag = card.select_one("img.a-card__img, .a-card__image img")
            photo_url = None
            if img_tag:
                photo_url = img_tag.get("src") or img_tag.get("data-src")

            listings.append({
                "id": ad_id,
                "title": title,
                "price": price_text,
                "desc": desc,
                "address": address,
                "url": full_url,
                "photo": photo_url,
            })
        except Exception as e:
            logger.warning(f"Ошибка парсинга карточки: {e}")
            continue

    return listings

# ─────────────────────────────────────────────
# Форматирование сообщений
# ─────────────────────────────────────────────

def format_listing(listing: dict) -> str:
    return (
        f"🏢 *{listing['title']}*\n"
        f"💰 {listing['price']}\n"
        f"📍 {listing['address']}\n"
        f"📐 {listing['desc']}\n"
        f"🔗 [Открыть объявление]({listing['url']})"
    )

# ─────────────────────────────────────────────
# Проверка и рассылка новых объявлений
# ─────────────────────────────────────────────

async def check_and_notify(app: Application):
    """Главная функция проверки — вызывается по расписанию."""
    data = load_data()
    logger.info(f"⏰ Проверка объявлений. Активных пользователей: {len(data)}")

    for uid, user in data.items():
        if not user.get("active") or not user.get("max_price"):
            continue

        chat_id = int(uid)
        max_price = user["max_price"]
        rooms = user.get("rooms", [])
        seen_ids: list = user.get("seen_ids", [])

        listings = parse_listings(max_price, rooms)
        new_listings = [l for l in listings if l["id"] not in seen_ids]

        if not new_listings:
            logger.info(f"Нет новых объявлений для пользователя {uid}")
            continue

        logger.info(f"🆕 Новых объявлений для {uid}: {len(new_listings)}")
        sent = 0

        for listing in new_listings[:10]:   # максимум 10 за раз
            try:
                msg = format_listing(listing)
                if listing.get("photo"):
                    await app.bot.send_photo(
                        chat_id=chat_id,
                        photo=listing["photo"],
                        caption=msg,
                        parse_mode="Markdown",
                    )
                else:
                    await app.bot.send_message(
                        chat_id=chat_id,
                        text=msg,
                        parse_mode="Markdown",
                        disable_web_page_preview=False,
                    )
                seen_ids.append(listing["id"])
                sent += 1
                await asyncio.sleep(0.5)   # антиспам
            except Exception as e:
                logger.error(f"Ошибка отправки сообщения {uid}: {e}")

        # Ограничиваем историю просмотренных ID до 500
        user["seen_ids"] = seen_ids[-500:]
        user["notified_count"] = user.get("notified_count", 0) + sent
        save_user(chat_id, user)

        if sent > 0:
            await app.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Отправлено {sent} новых объявлений. Следующая проверка через {CHECK_INTERVAL_MINUTES} мин.",
            )

# ─────────────────────────────────────────────
# Команды бота
# ─────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    get_user(chat_id)   # инициализируем если нет
    text = (
        "👋 *Привет! Я слежу за объявлениями на Krisha.kz*\n\n"
        "🏢 Категория: *Продажа квартир — Алматы*\n\n"
        "📋 *Команды:*\n"
        "• /setprice `50000000` — установить макс. цену (в тенге)\n"
        "• /rooms — выбрать количество комнат\n"
        "• /start_monitor — запустить мониторинг\n"
        "• /stop_monitor — остановить мониторинг\n"
        "• /status — текущие настройки\n"
        "• /check — проверить прямо сейчас\n"
        "• /help — справка\n\n"
        "💡 Начни с команды `/setprice` и укажи максимальную цену в тенге.\n"
        "Например: `/setprice 45000000`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_setprice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)

    args = ctx.args
    if not args:
        await update.message.reply_text(
            "💰 Укажи максимальную цену в тенге.\n"
            "Например: `/setprice 45000000`",
            parse_mode="Markdown",
        )
        return

    try:
        price_str = args[0].replace(" ", "").replace(",", "").replace(".", "")
        price = int(price_str)
        if price <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Неверный формат. Пример: `/setprice 45000000`", parse_mode="Markdown")
        return

    user["max_price"] = price
    user["seen_ids"] = []   # сброс истории при смене цены
    save_user(chat_id, user)

    formatted = f"{price:,}".replace(",", " ")
    await update.message.reply_text(
        f"✅ Максимальная цена установлена: *{formatted} ₸*\n\n"
        f"Теперь запусти мониторинг командой /start\_monitor",
        parse_mode="Markdown",
    )


async def cmd_rooms(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("1️⃣ Однушки", callback_data="rooms_1"),
            InlineKeyboardButton("2️⃣ Двушки", callback_data="rooms_2"),
        ],
        [
            InlineKeyboardButton("3️⃣ Трёшки", callback_data="rooms_3"),
            InlineKeyboardButton("4️⃣+ Многокомнатные", callback_data="rooms_4"),
        ],
        [InlineKeyboardButton("🏠 Любое количество комнат", callback_data="rooms_0")],
    ]
    await update.message.reply_text(
        "🛏 Выбери количество комнат (можно несколько):",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def callback_rooms(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    user = get_user(chat_id)

    choice = query.data  # например "rooms_2"
    num = int(choice.split("_")[1])

    if num == 0:
        user["rooms"] = []
        label = "🏠 Любое количество комнат"
    else:
        current = user.get("rooms", [])
        if num in current:
            current.remove(num)
        else:
            current.append(num)
            current.sort()
        user["rooms"] = current
        label = f"Выбрано: {', '.join(str(r) for r in current) + '-комнатные' if current else 'ничего не выбрано'}"

    save_user(chat_id, user)
    await query.edit_message_text(f"✅ {label}\n\nМожно запустить /start\_monitor", parse_mode="Markdown")


async def cmd_start_monitor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)

    if not user.get("max_price"):
        await update.message.reply_text(
            "⚠️ Сначала установи цену командой `/setprice`", parse_mode="Markdown"
        )
        return

    user["active"] = True
    user["seen_ids"] = []   # сброс при старте
    save_user(chat_id, user)

    price = f"{user['max_price']:,}".replace(",", " ")
    rooms_txt = (
        f"{', '.join(str(r) for r in user['rooms'])}-комнатные"
        if user.get("rooms")
        else "любые"
    )
    await update.message.reply_text(
        f"🚀 *Мониторинг запущен!*\n\n"
        f"💰 Макс. цена: *{price} ₸*\n"
        f"🛏 Комнаты: *{rooms_txt}*\n"
        f"📍 Город: *Алматы*\n"
        f"⏱ Проверка каждые *{CHECK_INTERVAL_MINUTES} минут*\n\n"
        f"Как только появятся подходящие объявления — сразу пришлю!",
        parse_mode="Markdown",
    )

    # Сразу делаем первую проверку
    await update.message.reply_text("🔍 Делаю первую проверку прямо сейчас...")
    await check_and_notify(ctx.application)


async def cmd_stop_monitor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    user["active"] = False
    save_user(chat_id, user)
    await update.message.reply_text(
        "⏹ *Мониторинг остановлен.*\n\nЧтобы возобновить — /start\_monitor",
        parse_mode="Markdown",
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)

    price = f"{user['max_price']:,}".replace(",", " ") if user.get("max_price") else "не задана"
    status = "🟢 Активен" if user.get("active") else "🔴 Остановлен"
    rooms_txt = (
        f"{', '.join(str(r) for r in user['rooms'])}-комнатные"
        if user.get("rooms")
        else "любые"
    )
    seen = len(user.get("seen_ids", []))
    notified = user.get("notified_count", 0)

    await update.message.reply_text(
        f"📊 *Текущие настройки:*\n\n"
        f"• Статус: {status}\n"
        f"• Макс. цена: *{price} ₸*\n"
        f"• Комнаты: *{rooms_txt}*\n"
        f"• Город: *Алматы*\n"
        f"• Проверка: каждые *{CHECK_INTERVAL_MINUTES} мин*\n"
        f"• Просмотрено объявлений: {seen}\n"
        f"• Всего отправлено уведомлений: {notified}",
        parse_mode="Markdown",
    )


async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)

    if not user.get("max_price"):
        await update.message.reply_text("⚠️ Сначала установи цену: `/setprice 45000000`", parse_mode="Markdown")
        return

    if not user.get("active"):
        await update.message.reply_text("⚠️ Мониторинг не запущен. Используй /start\_monitor", parse_mode="Markdown")
        return

    await update.message.reply_text("🔍 Проверяю объявления...")
    await check_and_notify(ctx.application)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Справка по боту*\n\n"
        "*Как начать:*\n"
        "1️⃣ `/setprice 45000000` — установи макс. цену в тенге\n"
        "2️⃣ `/rooms` — выбери количество комнат (опционально)\n"
        "3️⃣ `/start_monitor` — запусти мониторинг\n\n"
        "*Управление:*\n"
        "• `/stop_monitor` — остановить\n"
        "• `/status` — посмотреть настройки\n"
        "• `/check` — проверить прямо сейчас\n\n"
        "*Как работает:*\n"
        "Каждые 15 минут бот парсит первую страницу krisha.kz с фильтром "
        "«продажа квартир в Алматы дешевле X тенге» и отправляет только новые объявления.\n\n"
        "⚠️ *Примечание:* сайт иногда блокирует частые запросы — в таком случае "
        "бот пропустит один цикл и попробует снова.",
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────
# Запуск
# ─────────────────────────────────────────────

def main():
    if BOT_TOKEN == "ВСТАВЬ_СВОЙ_ТОКЕН_ЗДЕСЬ":
        print("❌ Укажи BOT_TOKEN в переменной окружения или прямо в коде!")
        print("   export BOT_TOKEN=1234567890:AAABBBCCC...")
        return

    print("🤖 Krisha.kz Monitor Bot запускается...")

    app = Application.builder().token(BOT_TOKEN).build()

    # Хэндлеры команд
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("setprice", cmd_setprice))
    app.add_handler(CommandHandler("rooms", cmd_rooms))
    app.add_handler(CommandHandler("start_monitor", cmd_start_monitor))
    app.add_handler(CommandHandler("stop_monitor", cmd_stop_monitor))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(callback_rooms, pattern="^rooms_"))

    # Планировщик — каждые 15 минут
    scheduler = AsyncIOScheduler(timezone="Asia/Almaty")
    scheduler.add_job(
        check_and_notify,
        trigger="interval",
        minutes=CHECK_INTERVAL_MINUTES,
        args=[app],
        id="krisha_check",
        name="Krisha.kz parser",
        misfire_grace_time=60,
    )

    async def post_init(application: Application):
        scheduler.start()
        logger.info(f"✅ Планировщик запущен. Интервал: {CHECK_INTERVAL_MINUTES} мин.")

    app.post_init = post_init

    print("✅ Бот запущен. Нажми Ctrl+C для остановки.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
