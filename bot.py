#!/usr/bin/env python3
"""
Krisha.kz Monitor Bot — исправленная версия
"""

import os
import json
import logging
import asyncio
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)

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

BOT_TOKEN = "8737332675:AAEELNxtay1ha0ExxrwfoeQE9L_aKAl1InA"
DATA_FILE = Path("user_data.json")
CHECK_INTERVAL_MINUTES = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9",
}

# ── Данные ────────────────────────────────────

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
        data[uid] = {"max_price": None, "active": False,
                     "seen_ids": [], "rooms": [], "notified_count": 0}
        save_data(data)
    return data[uid]

def save_user(chat_id: int, user: dict):
    data = load_data()
    data[str(chat_id)] = user
    save_data(data)

# ── Парсер ────────────────────────────────────

def build_url(max_price: int, rooms: list) -> str:
    base = "https://krisha.kz/prodazha/kvartiry/almaty/"
    params = [f"das[price][to]={max_price}", "sort=date"]
    for r in rooms:
        params.append(f"das[live.rooms][]={r}")
    return base + "?" + "&".join(params)

def parse_listings(max_price: int, rooms: list) -> list:
    url = build_url(max_price, rooms)
    logger.info(f"Запрос: {url}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Ошибка запроса: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select("div.a-card")
    logger.info(f"Найдено карточек: {len(cards)}")
    listings = []

    for card in cards:
        try:
            link_tag = card.select_one("a[href*='/a/show/']")
            if not link_tag:
                continue
            href = link_tag.get("href", "")
            ad_id = href.split("/a/show/")[-1].split("/")[0].split("?")[0]
            full_url = f"https://krisha.kz{href}" if href.startswith("/") else href

            title = (card.select_one(".a-card__title") or {}).get_text(strip=True) if card.select_one(".a-card__title") else "Квартира"
            price_text = card.select_one(".a-card__price").get_text(strip=True) if card.select_one(".a-card__price") else "—"
            address = card.select_one(".a-card__subtitle").get_text(strip=True) if card.select_one(".a-card__subtitle") else "Алматы"
            desc = card.select_one(".a-card__header-left").get_text(" ", strip=True) if card.select_one(".a-card__header-left") else ""

            img_tag = card.select_one("img.a-card__img, .a-card__image img")
            photo = (img_tag.get("src") or img_tag.get("data-src")) if img_tag else None

            listings.append({"id": ad_id, "title": title, "price": price_text,
                              "desc": desc, "address": address, "url": full_url, "photo": photo})
        except Exception as e:
            logger.warning(f"Ошибка карточки: {e}")
    return listings

def fmt(listing: dict) -> str:
    return (
        f"🏢 *{listing['title']}*\n"
        f"💰 {listing['price']}\n"
        f"📍 {listing['address']}\n"
        f"📐 {listing['desc']}\n"
        f"🔗 [Открыть]({listing['url']})"
    )

# ── Проверка ──────────────────────────────────

async def check_and_notify(app: Application):
    data = load_data()
    logger.info(f"⏰ Проверка. Пользователей: {len(data)}")
    for uid, user in data.items():
        if not user.get("active") or not user.get("max_price"):
            continue
        chat_id = int(uid)
        seen_ids = user.get("seen_ids", [])
        listings = parse_listings(user["max_price"], user.get("rooms", []))
        new = [l for l in listings if l["id"] not in seen_ids]
        if not new:
            logger.info(f"Нет новых для {uid}")
            continue
        sent = 0
        for l in new[:10]:
            try:
                if l.get("photo"):
                    await app.bot.send_photo(chat_id=chat_id, photo=l["photo"],
                                             caption=fmt(l), parse_mode="Markdown")
                else:
                    await app.bot.send_message(chat_id=chat_id, text=fmt(l), parse_mode="Markdown")
                seen_ids.append(l["id"])
                sent += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Ошибка отправки: {e}")
        user["seen_ids"] = seen_ids[-500:]
        user["notified_count"] = user.get("notified_count", 0) + sent
        save_user(chat_id, user)
        if sent:
            await app.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Отправлено {sent} новых. Следующая проверка через {CHECK_INTERVAL_MINUTES} мин."
            )

async def scheduled_check(context: ContextTypes.DEFAULT_TYPE):
    await check_and_notify(context.application)

# ── Команды ───────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    get_user(update.effective_chat.id)
    await update.message.reply_text(
        "👋 *Привет\\! Я слежу за Krisha\\.kz*\n\n"
        "🏢 Продажа квартир — Алматы\n\n"
        "Команды:\n"
        "• /setprice `45000000` — макс\\. цена\n"
        "• /rooms — фильтр по комнатам\n"
        "• /start\\_monitor — запустить\n"
        "• /stop\\_monitor — остановить\n"
        "• /status — настройки\n"
        "• /check — проверить сейчас",
        parse_mode="MarkdownV2",
    )

async def cmd_setprice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not ctx.args:
        await update.message.reply_text("Пример: `/setprice 45000000`", parse_mode="Markdown")
        return
    try:
        price = int(ctx.args[0].replace(",", "").replace(" ", ""))
        assert price > 0
    except:
        await update.message.reply_text("❌ Неверный формат. Пример: `/setprice 45000000`", parse_mode="Markdown")
        return
    user["max_price"] = price
    user["seen_ids"] = []
    save_user(chat_id, user)
    await update.message.reply_text(
        f"✅ Макс. цена: *{price:,} ₸*\n\nЗапусти /start\_monitor".replace(",", " "),
        parse_mode="Markdown"
    )

async def cmd_rooms(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("1️⃣ Однушки", callback_data="rooms_1"),
         InlineKeyboardButton("2️⃣ Двушки", callback_data="rooms_2")],
        [InlineKeyboardButton("3️⃣ Трёшки", callback_data="rooms_3"),
         InlineKeyboardButton("4️⃣+ Многокомнатные", callback_data="rooms_4")],
        [InlineKeyboardButton("🏠 Любое количество", callback_data="rooms_0")],
    ]
    await update.message.reply_text("🛏 Выбери комнаты:", reply_markup=InlineKeyboardMarkup(kb))

async def callback_rooms(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    user = get_user(chat_id)
    num = int(q.data.split("_")[1])
    if num == 0:
        user["rooms"] = []
        label = "🏠 Любое количество"
    else:
        cur = user.get("rooms", [])
        cur.remove(num) if num in cur else cur.append(num)
        user["rooms"] = sorted(cur)
        label = f"Выбрано: {', '.join(map(str, user['rooms']))}-комн." if user["rooms"] else "Ничего не выбрано"
    save_user(chat_id, user)
    await q.edit_message_text(f"✅ {label}\n\nЗапусти /start\\_monitor", parse_mode="Markdown")

async def cmd_start_monitor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user.get("max_price"):
        await update.message.reply_text("⚠️ Сначала: `/setprice 45000000`", parse_mode="Markdown")
        return
    user["active"] = True
    user["seen_ids"] = []
    save_user(chat_id, user)
    rooms_txt = f"{', '.join(map(str, user['rooms']))}-комн." if user.get("rooms") else "любые"
    price_fmt = str(user['max_price'])
    await update.message.reply_text(
        f"🚀 *Мониторинг запущен\\!*\n\n"
        f"💰 Макс\\. цена: *{price_fmt} ₸*\n"
        f"🛏 Комнаты: *{rooms_txt}*\n"
        f"📍 Город: *Алматы*\n"
        f"⏱ Каждые *{CHECK_INTERVAL_MINUTES} минут*",
        parse_mode="MarkdownV2",
    )
    await update.message.reply_text("🔍 Первая проверка прямо сейчас...")
    await check_and_notify(ctx.application)

async def cmd_stop_monitor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    user["active"] = False
    save_user(chat_id, user)
    await update.message.reply_text("⏹ Мониторинг остановлен. Возобновить: /start\\_monitor", parse_mode="Markdown")

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    price = str(user['max_price']) if user.get("max_price") else "не задана"
    status = "🟢 Активен" if user.get("active") else "🔴 Остановлен"
    rooms_txt = f"{', '.join(map(str, user['rooms']))}-комн." if user.get("rooms") else "любые"
    await update.message.reply_text(
        f"📊 *Настройки:*\n\n"
        f"• Статус: {status}\n"
        f"• Макс. цена: *{price} ₸*\n"
        f"• Комнаты: *{rooms_txt}*\n"
        f"• Отправлено: {user.get('notified_count', 0)} объявлений",
        parse_mode="Markdown"
    )

async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = get_user(chat_id)
    if not user.get("max_price"):
        await update.message.reply_text("⚠️ Сначала: `/setprice 45000000`", parse_mode="Markdown")
        return
    if not user.get("active"):
        await update.message.reply_text("⚠️ Запусти мониторинг: /start\\_monitor", parse_mode="Markdown")
        return
    await update.message.reply_text("🔍 Проверяю...")
    await check_and_notify(ctx.application)

# ── Запуск ────────────────────────────────────

def main():
    if BOT_TOKEN == "ВСТАВЬ_СВОЙ_ТОКЕН_ЗДЕСЬ":
        print("❌ Укажи BOT_TOKEN!")
        print("   Windows PowerShell: $env:BOT_TOKEN='твой_токен'")
        print("   Linux/macOS:        export BOT_TOKEN='твой_токен'")
        return

    print("🤖 Запуск Krisha.kz Bot...")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("setprice", cmd_setprice))
    app.add_handler(CommandHandler("rooms", cmd_rooms))
    app.add_handler(CommandHandler("start_monitor", cmd_start_monitor))
    app.add_handler(CommandHandler("stop_monitor", cmd_stop_monitor))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(CallbackQueryHandler(callback_rooms, pattern="^rooms_"))

    # ✅ Встроенный JobQueue — никакого APScheduler
    app.job_queue.run_repeating(
        scheduled_check,
        interval=CHECK_INTERVAL_MINUTES * 60,
        first=10,
        name="krisha_check",
    )

    print(f"✅ Бот работает. Проверка каждые {CHECK_INTERVAL_MINUTES} мин. Ctrl+C для остановки.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
