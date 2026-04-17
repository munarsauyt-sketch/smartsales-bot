import os
import asyncio
import logging
import re
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from groq import Groq
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import json
import requests

# Supabase credentials
SUPABASE_URL = "https://zoyqyqbimotlxyesgyua.supabase.co"
SUPABASE_KEY = "sb_publishable_xQ2GXRqOMQjWUdydJv9yrg_WFLbSHcO"
SUPABASE_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates"
}

def save_banners():
    """Сохраняем баннеры и настройки ИИ в Supabase"""
    try:
        # Собираем настройки ИИ для всех продавцов
        ai_settings_data = {
            str(uid): {
                "ai_timer": s.get("ai_timer", "2m"),
                "ai_prompt": s.get("ai_prompt", ""),
                "ai_enabled": s.get("ai_enabled", False),
                "ai_paid": s.get("ai_paid", False),
            }
            for uid, s in sellers.items()
        }
        data = {
            "id": 1,
            "catalog_banner": json.dumps(state_store.get("catalog_banner")),
            "cat_banners": json.dumps(state_store.get("cat_banners", {})),
            "ad_products": json.dumps(ad_products),
            "verified_sellers": json.dumps(list(verified_sellers)),
            "ai_settings": json.dumps(ai_settings_data),
        }
        resp = requests.post(
            f"{SUPABASE_URL}/rest/v1/bot_settings",
            headers=SUPABASE_HEADERS,
            json=data,
            timeout=5
        )
        if resp.status_code not in (200, 201):
            logger.error(f"save_banners error: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"save_banners exception: {e}")

def load_banners():
    """Загружаем баннеры из Supabase при старте"""
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/bot_settings?id=eq.1",
            headers=SUPABASE_HEADERS,
            timeout=5
        )
        if resp.status_code == 200 and resp.json():
            row = resp.json()[0]
            cb = json.loads(row.get("catalog_banner") or "null")
            if cb:
                state_store["catalog_banner"] = cb
            catb = json.loads(row.get("cat_banners") or "{}")
            if catb:
                state_store["cat_banners"] = catb
            adp = json.loads(row.get("ad_products") or "[]")
            if adp:
                ad_products.extend(adp)
            vs = json.loads(row.get("verified_sellers") or "[]")
            if vs:
                verified_sellers.update(vs)
            logger.info("Баннеры загружены из Supabase")
        else:
            logger.info("Нет сохранённых баннеров в Supabase")
    except Exception as e:
        logger.error(f"load_banners exception: {e}")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "1048682172"))
ADMIN_USERNAME = "evnnnu"
YOOMONEY_WALLET = "4100118679419062"
AI_PRICE = 500
AD_BANNER_3D = 500     # основной баннер 3 дня
AD_BANNER_7D = 750     # основной баннер неделя
AD_CAT_3D = 150        # саб-баннер 3 дня
AD_CAT_7D = 250        # саб-баннер неделя
AD_TOP_PRICE = 200
VERIFIED_PRICE = 300
groq_client = Groq(api_key=GROQ_API_KEY)

# --- ХРАНИЛИЩЕ ---
products = {}
product_counter = [1]
sellers = {}
active_chats = {}
pending_ai_tasks = {}
user_states = {}
user_temp = {}
reviews = {}
favorites = {}
views_count = {}
promo_codes = {}
top_sellers = {}
ad_products = []
guarantees = {}
state_store = {
    "sponsor_banner": None,
    "catalog_banner": None,
    "cat_banners": {}
}
# Храним ID и тип последнего сообщения бота для каждого пользователя
last_bot_message = {}  # uid -> message_id
last_msg_is_photo = {}  # uid -> bool (True если последнее сообщение — фото)

# Плавный фейковый онлайн — не скачет резко
_fake_online = {"value": 72, "viewers": 18}

def get_fake_online():
    """Плавно меняет онлайн в зависимости от времени суток. Шаг ±1-3."""
    from datetime import datetime, timezone, timedelta
    # Алматы UTC+5
    now = datetime.now(timezone(timedelta(hours=5)))
    hour = now.hour

    # Целевой онлайн по времени суток
    if 0 <= hour < 6:      # ночь
        target = random.randint(15, 30)
    elif 6 <= hour < 10:   # утро
        target = random.randint(35, 55)
    elif 10 <= hour < 14:  # день
        target = random.randint(55, 75)
    elif 14 <= hour < 18:  # после обеда
        target = random.randint(65, 90)
    elif 18 <= hour < 22:  # вечер (пик)
        target = random.randint(80, 120)
    else:                   # поздний вечер
        target = random.randint(45, 70)

    current = _fake_online["value"]
    # Двигаемся к цели шагом 1-3, не скачем
    if current < target:
        step = random.randint(1, 3)
        current = min(current + step, target)
    elif current > target:
        step = random.randint(1, 3)
        current = max(current - step, target)

    _fake_online["value"] = current

    # Просматривающих — примерно 20-30% от онлайна, тоже плавно
    viewers_target = max(5, current // 4 + random.randint(-2, 2))
    v = _fake_online["viewers"]
    if v < viewers_target:
        v = min(v + random.randint(1, 2), viewers_target)
    elif v > viewers_target:
        v = max(v - random.randint(1, 2), viewers_target)
    _fake_online["viewers"] = v

    return current, v

async def safe_edit_text(query, uid, text, keyboard, parse_mode="Markdown"):
    """Показывает текстовое сообщение с кнопками. Всегда редактирует на месте."""
    last_msg_is_photo[uid] = False
    try:
        await query.edit_message_text(text, parse_mode=parse_mode, reply_markup=keyboard)
    except Exception:
        try:
            await query.message.delete()
        except Exception:
            pass
        try:
            sent = await query.message.chat.send_message(
                text, parse_mode=parse_mode, reply_markup=keyboard)
            last_bot_message[uid] = sent.message_id
        except Exception:
            pass

async def safe_edit_photo(query, uid, photo_id, caption, keyboard):
    """Показывает фото с кнопками. Удаляет старое сообщение и шлёт новое."""
    last_msg_is_photo[uid] = True
    chat_id = query.message.chat_id
    msg_id = query.message.message_id
    bot = query.get_bot()
    # Удаляем старое сообщение
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass
    # Шлём новое фото с кнопками
    try:
        sent = await bot.send_photo(
            chat_id=chat_id,
            photo=photo_id,
            caption=caption if caption else None,
            reply_markup=keyboard
        )
        last_bot_message[uid] = sent.message_id
    except Exception:
        # Фото не вышло — шлём текст
        try:
            sent = await bot.send_message(
                chat_id=chat_id,
                text=caption or "📂 Выберите:",
                reply_markup=keyboard
            )
            last_bot_message[uid] = sent.message_id
            last_msg_is_photo[uid] = False
        except Exception:
            pass
verified_sellers = set()
all_users = set()
PAGE_SIZE = 8
CATEGORIES = ["Brawl Stars", "PUBG Mobile", "Roblox", "Standoff 2", "Steam", "CS2"]
CAT_EMOJI = {"Brawl Stars": "🎯", "PUBG Mobile": "🔫", "Roblox": "🧱",
             "Standoff 2": "🔪", "Steam": "🎮", "CS2": "🏆"}
AI_TIMERS = {
    "30s": ("30 секунд", 30), "1m": ("1 минута", 60), "2m": ("2 минуты", 120),
    "3m": ("3 минуты", 180), "5m": ("5 минут", 300), "10m": ("10 минут", 600),
    "15m": ("15 минут", 900), "30m": ("30 минут", 1800), "1h": ("1 час", 3600),
    "2h": ("2 часа", 7200),
}
DEFAULT_AI_PROMPT = "Ты продавец цифровых товаров. Пиши коротко и по делу — только преимущества товара без воды. Не здоровайся длинно, сразу к сути. Отвечай на русском."

def init_demo():
    sellers[ADMIN_ID] = {
        "name": "SmartSales", "username": "admin",
        "ai_enabled": True, "ai_paid": True,
        "ai_prompt": "Ты опытный продавец игровых аккаунтов. Расскажи о преимуществах товара, убеди купить, будь дружелюбным.",
        "products": []
    }
    top_sellers[ADMIN_ID] = 47
    verified_sellers.add(ADMIN_ID)
    demo_products = [
        {"cat": "Brawl Stars", "title": "Аккаунт 45 бравлеров, Мортис макс", "desc": "45 бравлеров, Мортис 11, Эмбер 9, Байрон 10. Трофеи 32,000. Без привязки к номеру.", "price": 1800},
        {"cat": "Brawl Stars", "title": "Аккаунт 3 легендарки + Brawl Pass", "desc": "Леон, Сэнди, Корделиус. 28,500 трофеев. Активный Brawl Pass. Почта в комплекте.", "price": 2400},
        {"cat": "Brawl Stars", "title": "1000 гемов Brawl Stars фаст", "desc": "Пополнение через официальный аккаунт. Отправлю в течение 10 минут после оплаты.", "price": 600},
        {"cat": "Brawl Stars", "title": "Аккаунт 170 бравлеров 54к трофеев", "desc": "170 бравлеров включая всех легендарок. 54,200 трофеев. Аккаунт прокачан полностью.", "price": 8500},
        {"cat": "Brawl Stars", "title": "Brawl Pass + 80 гемов", "desc": "Сезонный Brawl Pass + 80 гемов в подарок. Введу код сразу после оплаты.", "price": 450},
        {"cat": "Brawl Stars", "title": "Аккаунт новый старт 12 бравлеров", "desc": "Чистый аккаунт 12 бравлеров, Шелли макс, Нита 9, Кольт 8. 4,500 трофеев.", "price": 300},
        {"cat": "Brawl Stars", "title": "170 гемов Brawl Stars фаст", "desc": "170 гемов — хватит на скин или Brawl Pass. Пополню за 10 минут.", "price": 300},
        {"cat": "Brawl Stars", "title": "80 гемов Brawl Stars быстро", "desc": "80 гемов на ваш аккаунт. Нужен только тег. Фаст, работаю без задержек.", "price": 200},
        {"cat": "Brawl Stars", "title": "Старт аккаунт 5 бравлеров", "desc": "Новый аккаунт, 5 разных бравлеров включая Эль Примо. 1800 трофеев. Дёшево!", "price": 250},
        {"cat": "Brawl Stars", "title": "Аккаунт 8 бравлеров 3к трофеев", "desc": "8 бравлеров, Шелли и Нита прокачаны. 3200 трофеев. Без привязки.", "price": 350},
        {"cat": "Brawl Stars", "title": "40 гемов + 2 скина бесплатных", "desc": "40 гемов и 2 базовых скина на аккаунте. Хорошо для старта.", "price": 200},
        {"cat": "Brawl Stars", "title": "100 гемов фаст без предоплаты", "desc": "100 гемов. Работаю по схеме: ты первый — я быстро. 50+ продаж.", "price": 280},
        {"cat": "Brawl Stars", "title": "Аккаунт 6 бравлеров Динамайк макс", "desc": "6 бравлеров, Динамайк 11 уровень, Бо 8. 2500 трофеев. Быстрая передача.", "price": 220},
        {"cat": "Brawl Stars", "title": "Старт аккаунт Колетт + Эш", "desc": "Аккаунт с Колетт и Эшем. 4100 трофеев. 7 бравлеров общих.", "price": 380},
        {"cat": "Brawl Stars", "title": "50 гемов дёшево без предоплаты", "desc": "50 гемов — цена ниже рынка. Нужен тег игрока. Фаст 5 минут.", "price": 210},
        {"cat": "Brawl Stars", "title": "68к кубков | 72 бравлера | Леон + Корд макс | почта в комп", "desc": "Топовый акк с легендарками, почта передаётся. Без привязки к номеру. Передача быстро.", "price": 4500},
        {"cat": "Brawl Stars", "title": "82к кубков | все легендарки | редкие скины | без привязки", "desc": "Все легендарные бравлеры прокачаны, редкие скины куплены за реал. Чистый акк без банов.", "price": 7200},
        {"cat": "Brawl Stars", "title": "55к кубков | Сэнди + Эмбер + Байрон | пасс активен", "desc": "Три легендарки, все гаджеты открыты. Brawl Pass активен на текущий сезон.", "price": 3800},
        {"cat": "Brawl Stars", "title": "31к кубков | Мортис 11лвл | гипер урон открыт | срочно", "desc": "Мортис полностью прокачан, гипер урон разблокирован. Продаю срочно, цена низкая.", "price": 1900},
        {"cat": "Brawl Stars", "title": "45к кубков | 58 персов | скин Кроу Феникс | фаст", "desc": "58 бравлеров, редкий скин Кроу Феникс. Передача в течение 10 минут.", "price": 2800},
        {"cat": "Brawl Stars", "title": "91к кубков | 83 перса | 8 хром скинов | цена договорная", "desc": "83 бравлера, 8 хромных скинов. Серьёзный акк для серьёзного игрока.", "price": 9500},
        {"cat": "Brawl Stars", "title": "73к кубков | скин Эмбер Дракон | почта отдаётся", "desc": "Редкий скин Эмбер Дракон. Почта в комплекте, смена данных после передачи.", "price": 5100},
        {"cat": "Brawl Stars", "title": "28к кубков | Мортис + Кроу + Спайк | все гаджеты", "desc": "Три легендарки, все гаджеты и старпауэры открыты. Хорошая цена.", "price": 2200},
        {"cat": "Brawl Stars", "title": "49к кубков | 5 легендарок | все на 9-11лвл | срочно", "desc": "Пять легендарных бравлеров, все прокачаны до максимума. Продаю срочно.", "price": 3200},
        {"cat": "Brawl Stars", "title": "22к кубков | 41 перс | Пауэр Лига Диамант", "desc": "41 бравлер, ранг Диамант в Пауэр Лиге. Хороший акк для фарма.", "price": 1500},
        {"cat": "Brawl Stars", "title": "67к кубков | пасс в комплекте | Леон + Сэнди макс", "desc": "Леон и Сэнди на максимальном уровне. Brawl Pass текущего сезона в комплекте.", "price": 4100},
        {"cat": "Brawl Stars", "title": "88к кубков | топ 10к в сезоне | Гром + Эш макс", "desc": "Был в топ 10к игроков сезона. Гром и Эш прокачаны полностью.", "price": 6800},
        {"cat": "Brawl Stars", "title": "76к кубков | красивый тег | почта отдаю | без привязки", "desc": "Редкий красивый тег, почта передаётся в комплекте. Без привязки к номеру.", "price": 5500},
        {"cat": "Brawl Stars", "title": "62к кубков | Гром + Эш + Мэнди | скины за реал куплены", "desc": "Три мощных бравлера, скины покупались за реальные деньги. Всё прокачано.", "price": 4700},
        {"cat": "Brawl Stars", "title": "35к кубков | Кроу + Леон | редкие скины есть", "desc": "Кроу и Леон макс, несколько редких скинов. Передача быстрая.", "price": 2400},
        {"cat": "Brawl Stars", "title": "41к кубков | ранг Мастер соло | Корделиус макс", "desc": "Ранг Мастер в соло режиме. Корделиус полностью прокачан.", "price": 2900},
        {"cat": "Brawl Stars", "title": "95к кубков | 8 хромов | много эксклюзивных скинов", "desc": "8 хромных скинов, много эксклюзивов. Один из лучших аккаунтов.", "price": 8900},
        {"cat": "Brawl Stars", "title": "57к кубков | Про лига | Байрон + Корделиус", "desc": "Опыт в Про лиге. Байрон и Корделиус на максимуме.", "price": 3600},
        {"cat": "Brawl Stars", "title": "33к кубков | Спайк + Леон | давно не захожу", "desc": "Спайк и Леон прокачаны. Давно не играю — отдам по хорошей цене.", "price": 2100},
        {"cat": "Brawl Stars", "title": "79к кубков | красивый тег | все гаджеты и старпауэры", "desc": "Красивый короткий тег. Все гаджеты и старпауэры открыты на всех персах.", "price": 5800},
        {"cat": "Brawl Stars", "title": "100к кубков | хром скины на всех легах | почта в комп", "desc": "100 тысяч кубков! Хромные скины на всех легендарках. Почта передаётся.", "price": 11000},
        {"cat": "Brawl Stars", "title": "9к кубков | 20 персов | старт дёшево", "desc": "Чистый акк для старта. 20 бравлеров, нет привязки. Дёшево.", "price": 350},
        {"cat": "Brawl Stars", "title": "18к кубков | 35 персов | Кроу + Мортис", "desc": "Кроу и Мортис в наличии, 35 бравлеров. Хороший средний акк.", "price": 1200},
        {"cat": "Brawl Stars", "title": "52к кубков | скин Леон Акула хром | пасс активен", "desc": "Редкий хромный скин Леон Акула. Brawl Pass активен на текущий сезон.", "price": 3400},
        {"cat": "Brawl Stars", "title": "44к кубков | 61 перс | Пауэр Лига Платина", "desc": "61 бравлер, ранг Платина в Пауэр Лиге. Стабильный акк.", "price": 2700},
        {"cat": "Brawl Stars", "title": "37к кубков | Сэнди + Эмбер | все гаджеты открыты", "desc": "Две легендарки, все гаджеты разблокированы. Передача быстро.", "price": 2500},
        {"cat": "Brawl Stars", "title": "71к кубков | скин Спайк Кактус эксклюзив | фаст", "desc": "Эксклюзивный скин Спайк Кактус. Передача в течение 15 минут.", "price": 4900},
        {"cat": "Brawl Stars", "title": "25к кубков | 47 персов | Мортис + Кроу + Леон", "desc": "Три легендарки, 47 бравлеров. Хорошая цена за такой состав.", "price": 1800},
        {"cat": "Brawl Stars", "title": "83к кубков | Про лига топ | 6 хромов", "desc": "Топовый результат в Про лиге. Шесть хромных скинов.", "price": 7100},
        {"cat": "Brawl Stars", "title": "16к кубков | 31 перс | Байрон + Корделиус", "desc": "Байрон и Корделиус в наличии. 31 бравлер, хорошее начало.", "price": 1300},
        {"cat": "Brawl Stars", "title": "60к кубков | все старпауэры | скин Сэнди Фараон", "desc": "Все старпауэры открыты. Редкий скин Сэнди Фараон на аккаунте.", "price": 4300},
        {"cat": "Brawl Stars", "title": "48к кубков | 65 персов | пасс плюс в комплекте", "desc": "65 бравлеров, Brawl Pass Plus активен. Передача быстро.", "price": 3100},
        {"cat": "Brawl Stars", "title": "92к кубков | редкий тег 4 символа | почта в комп", "desc": "Редчайший тег из 4 символов. 92 тысячи кубков, почта передаётся.", "price": 8200},
        {"cat": "Brawl Stars", "title": "39к кубков | Гром + Эш | гаджеты все открыты", "desc": "Гром и Эш прокачаны, все гаджеты разблокированы. Фаст.", "price": 2600},
        {"cat": "Brawl Stars", "title": "26к кубков | 43 перса | Кроу + Спайк + Мортис", "desc": "Три легендарки в одном акке за эту цену — редкость. Фаст.", "price": 1900},
        {"cat": "Brawl Stars", "title": "77к кубков | скин Байрон Призрак | Пауэр Лига Мастер", "desc": "Ранг Мастер в Пауэр Лиге. Редкий скин Байрон Призрак.", "price": 5700},
        {"cat": "PUBG Mobile", "title": "Аккаунт 68 уровень Conqueror сезон", "desc": "68 лвл, был Conqueror в прошлом сезоне. 2800+ матчей. 3 ультра скина.", "price": 3200},
        {"cat": "PUBG Mobile", "title": "600 UC PUBG фаст 10 минут", "desc": "Пополняю UC на ваш аккаунт. Нужен только ID игрока. Фаст — 10 минут.", "price": 750},
        {"cat": "PUBG Mobile", "title": "1800 UC PUBG Mobile выгодно", "desc": "1800 UC — выгоднее чем покупать в магазине. Работаю быстро, 200+ продаж.", "price": 1900},
        {"cat": "PUBG Mobile", "title": "Аккаунт M17 ранг + Glacier M416", "desc": "Уровень M17, ранг Алмаз, легендарный скин M416 Glacier. 45 скинов персонажей.", "price": 5500},
        {"cat": "PUBG Mobile", "title": "Аккаунт 34 уровень, 8 скинов оружия", "desc": "34 уровень, 8 редких скинов оружия включая AKM Glacier. Хороший старт!", "price": 1200},
        {"cat": "PUBG Mobile", "title": "60 UC PUBG фаст", "desc": "60 UC — хватит на один выбор. Введу на ваш ID за 5 минут.", "price": 200},
        {"cat": "PUBG Mobile", "title": "180 UC PUBG Mobile недорого", "desc": "180 UC. Нужен ID игрока. Отправляю быстро, есть отзывы.", "price": 320},
        {"cat": "PUBG Mobile", "title": "Аккаунт 12 уровень 3 скина", "desc": "12 уровень, 3 скина персонажа включая Hazmat Suit. Старт дёшево.", "price": 250},
        {"cat": "PUBG Mobile", "title": "Аккаунт 20 уровень Silver ранг", "desc": "20 лвл, ранг Серебро. 2 скина оружия. Без привязки к номеру.", "price": 350},
        {"cat": "PUBG Mobile", "title": "120 UC пополнение 15 минут", "desc": "120 UC на ваш аккаунт. Нужен только ID. Без обмана, 80+ продаж.", "price": 260},
        {"cat": "PUBG Mobile", "title": "Акк 68лвл | Conqueror сезон 12 | 3 ультра сета | почта в комп", "desc": "Был Завоевателем в 12 сезоне. Три ультра сета одежды, почта передаётся.", "price": 4200},
        {"cat": "PUBG Mobile", "title": "Акк с Glacier M416 MAX | 52лвл | Ace ранг | фаст", "desc": "Легендарный скин M416 Glacier максимального уровня. Ранг Туз, передача быстро.", "price": 6800},
        {"cat": "PUBG Mobile", "title": "Акк 34лвл | 8 редких скинов оружия | AKM Glacier есть", "desc": "8 редких скинов включая AKM Glacier. Хороший средний акк.", "price": 1800},
        {"cat": "PUBG Mobile", "title": "Топ акк | X-Suit Ворон | 200+ скинов | Conqueror", "desc": "X-Suit Ворон, более 200 скинов, был Завоевателем. Серьёзный аккаунт.", "price": 15000},
        {"cat": "PUBG Mobile", "title": "Акк 45лвл | Diamond ранг | скин AWM сиреневый | фаст", "desc": "Ранг Алмаз, редкий скин AWM. Передача в течение 15 минут.", "price": 2500},
        {"cat": "PUBG Mobile", "title": "600 UC фаст | нужен только ID | работаю давно", "desc": "600 UC пополню на ваш аккаунт за 10 минут. Только ID игрока.", "price": 750},
        {"cat": "PUBG Mobile", "title": "1800 UC выгодно | дешевле магазина | 200+ продаж", "desc": "1800 UC ниже официальной цены. Более 200 довольных покупателей.", "price": 1900},
        {"cat": "PUBG Mobile", "title": "Акк 28лвл | куча скинов | срочно продаю | без привязки", "desc": "Много косметики накоплено, продаю срочно. Без привязки к номеру.", "price": 900},
        {"cat": "PUBG Mobile", "title": "Акк Conqueror | сезон 18 | M762 Glacier | почта есть", "desc": "Завоеватель 18 сезона, M762 Glacier скин. Почта в комплекте.", "price": 7500},
        {"cat": "PUBG Mobile", "title": "300 UC фаст | нужен ID | без предоплаты | проверенный", "desc": "300 UC на ваш аккаунт. Работаю без предоплаты, много отзывов.", "price": 380},
        {"cat": "PUBG Mobile", "title": "Акк 71лвл | Ace Master | Mythic Fashion 80+ вещей", "desc": "Ранг Туз Мастер, более 80 предметов Mythic Fashion. Топовый акк.", "price": 9200},
        {"cat": "PUBG Mobile", "title": "Акк 19лвл | Silver ранг | 3 скина | дёшево отдам", "desc": "Начальный акк с тремя скинами. Продаю недорого.", "price": 450},
        {"cat": "PUBG Mobile", "title": "3000 UC оптом | самая низкая цена | фаст", "desc": "3000 UC по самой низкой цене на рынке. Быстрое пополнение.", "price": 3200},
        {"cat": "PUBG Mobile", "title": "Акк | UMP скин ледник | 38лвл | Gold ранг", "desc": "UMP скин ледник, ранг Золото, 38 уровень. Хороший акк.", "price": 1400},
        {"cat": "PUBG Mobile", "title": "Акк 55лвл | Platinum ранг | 2 ультра сета | фаст", "desc": "Ранг Платина, два ультра сета персонажа. Передача быстро.", "price": 3600},
        {"cat": "PUBG Mobile", "title": "150 UC быстро | нужен ID | честно и надёжно", "desc": "150 UC за 5 минут. Нужен только ID. Много продаж.", "price": 200},
        {"cat": "PUBG Mobile", "title": "Акк 83лвл | все сезоны Conqueror | редчайший акк", "desc": "Завоеватель в нескольких сезонах подряд. Один из редких аккаунтов.", "price": 18000},
        {"cat": "PUBG Mobile", "title": "Акк 22лвл | просто давно не играю | отдам недорого", "desc": "Играл активно, потом бросил. Несколько скинов, отдам за копейки.", "price": 600},
        {"cat": "PUBG Mobile", "title": "Акк 48лвл | Ace ранг | скин Kar98 снежный | фаст", "desc": "Ранг Туз, скин Kar98 снежный. Передача в течение 20 минут.", "price": 3100},
        {"cat": "PUBG Mobile", "title": "600 UC | нужен только ID | 10 минут | 100+ продаж", "desc": "600 UC пополняю за 10 минут. Проверенный продавец, 100+ продаж.", "price": 730},
        {"cat": "Roblox", "title": "800 Robux фаст официально", "desc": "Официальное пополнение 800 Robux. Введу на ваш аккаунт за 5 минут.", "price": 650},
        {"cat": "Roblox", "title": "Аккаунт Roblox 2019 года + хаты", "desc": "Старый аккаунт 2019 года, куплено хат на 4500R, редкие предметы.", "price": 1100},
        {"cat": "Roblox", "title": "2000 Robux по выгодной цене", "desc": "2000 Robux — дешевле официального магазина. 150+ довольных клиентов.", "price": 1400},
        {"cat": "Roblox", "title": "Roblox Premium 1 месяц + 450R", "desc": "Активирую Premium подписку на 1 месяц + 450 Robux. Сразу после оплаты.", "price": 550},
        {"cat": "Roblox", "title": "Аккаунт Adopt Me легендарные питомцы", "desc": "Аккаунт с 12 легендарными питомцами в Adopt Me: Neon Dragon, Shadow Dragon.", "price": 2800},
        {"cat": "Roblox", "title": "80 Robux фаст моментально", "desc": "80 Robux — введу за 5 минут. Нужен только ник аккаунта.", "price": 200},
        {"cat": "Roblox", "title": "200 Robux недорого", "desc": "200 Robux на ваш аккаунт. Честно и быстро. 60+ довольных покупателей.", "price": 320},
        {"cat": "Roblox", "title": "Аккаунт Roblox 2021 года старт", "desc": "Аккаунт с 2021 года, несколько хат, чистая история. Хорошее начало.", "price": 250},
        {"cat": "Roblox", "title": "150 Robux + бонус хата", "desc": "150 Robux и хата в подарок на аккаунте. Отличный стартовый набор.", "price": 280},
        {"cat": "Roblox", "title": "400 Robux выгоднее магазина", "desc": "400 Robux — дешевле чем в официальном магазине. Фаст.", "price": 390},
        {"cat": "Roblox", "title": "Акк 2019 года | куча лимок | Adopt Me дракон неон | редкий", "desc": "Старый акк с 2019 года. В Adopt Me неоновый дракон и теневой дракон.", "price": 3500},
        {"cat": "Roblox", "title": "Акк | Blox Fruits | фрукт Leopard | 2450 уровень", "desc": "2450 уровень в Blox Fruits, фрукт Леопард. Топовый акк для фанатов игры.", "price": 4800},
        {"cat": "Roblox", "title": "1700 Robux фаст | нужен только ник | честно", "desc": "1700 Robux на ваш аккаунт за 10 минут. Нужен только ник.", "price": 1350},
        {"cat": "Roblox", "title": "Акк 2020 года | Royale High | много диамантов | редкие сеты", "desc": "В Royale High накоплены редкие сеты и много диамантов. Старый акк.", "price": 1800},
        {"cat": "Roblox", "title": "450 Robux фаст | без предоплаты | нужен ник", "desc": "450 Robux пополню за 5 минут. Работаю без предоплаты.", "price": 420},
        {"cat": "Roblox", "title": "Акк | MM2 | куча мифических ножей | годами копил", "desc": "В Murder Mystery 2 накоплены мифические ножи за несколько лет игры.", "price": 2200},
        {"cat": "Roblox", "title": "3600 Robux выгодно | дешевле официального | фаст", "desc": "3600 Robux по цене ниже официального магазина Roblox.", "price": 2700},
        {"cat": "Roblox", "title": "Акк 2021 года | старые ограниченные хаты | не играю", "desc": "Старые лимитированные шляпы с 2021 года. Продаю так как не играю.", "price": 950},
        {"cat": "Roblox", "title": "700 Robux нужен ник | фаст 5 минут | проверенный", "desc": "700 Robux за 5 минут. Много отзывов, работаю честно.", "price": 630},
        {"cat": "Roblox", "title": "Акк | Blox Fruits | все острова открыты | 2100 лвл", "desc": "Все острова открыты, 2100 уровень, есть неплохие фрукты.", "price": 2900},
        {"cat": "Roblox", "title": "Roblox Premium подписка 1 месяц | + 450R в подарок", "desc": "Активирую Premium на ваш акк на месяц. 450 Robux начислятся автоматически.", "price": 550},
        {"cat": "Roblox", "title": "Акк 2018 года | очень старый | редкие вещи | отдам", "desc": "Акк с 2018 года, есть очень старые и редкие предметы. Продаю.", "price": 4200},
        {"cat": "Roblox", "title": "1000 Robux фаст | нужен ник | 50+ продаж", "desc": "1000 Robux за 10 минут. Проверенный продавец, 50+ доволных.", "price": 880},
        {"cat": "Roblox", "title": "Акк | Adopt Me | неон единорог + неон летучая мышь", "desc": "Два неоновых питомца в Adopt Me. Передача акка быстро.", "price": 1600},
        {"cat": "Roblox", "title": "240 Robux дёшево | фаст | нужен ник", "desc": "240 Robux по низкой цене. Быстрое пополнение.", "price": 240},
        {"cat": "Roblox", "title": "Акк 2022 года | Brookhaven | много вещей | без привязки", "desc": "Много имущества в Brookhaven. Без привязки к номеру, чистая история.", "price": 700},
        {"cat": "Roblox", "title": "2000 Robux | дешевле магазина на 20% | фаст", "desc": "2000 Robux дешевле официального магазина. Пополняю быстро.", "price": 1500},
        {"cat": "Roblox", "title": "Акк | Blox Fruits | фрукт Dragon | 1900 лвл | фаст", "desc": "Фрукт Дракон, 1900 уровень. Хороший акк для Blox Fruits.", "price": 3200},
        {"cat": "Roblox", "title": "500 Robux | нужен только ник | 15 минут", "desc": "500 Robux на ваш аккаунт. Нужен только ник, пополняю за 15 минут.", "price": 460},
        {"cat": "Roblox", "title": "Акк 2019 года | старые ограниченные хаты дорогие | продаю", "desc": "Акк с редкими лимитированными предметами 2019 года. Хорошая цена.", "price": 5500},
        {"cat": "Standoff 2", "title": "Аккаунт 42 уровень Золото ранг", "desc": "42 уровень, Золото в ранговых. 14 скинов оружия, 3 ножа. Почта в комплекте.", "price": 1600},
        {"cat": "Standoff 2", "title": "Нож Керамбит Crimson Web продажа", "desc": "Редкий нож Керамбит Crimson Web. Передам через трейд безопасно.", "price": 3400},
        {"cat": "Standoff 2", "title": "Аккаунт 18 уровень старт дёшево", "desc": "18 уровень, 6 скинов, АК Vulcan. Хорошее начало для игры.", "price": 400},
        {"cat": "Standoff 2", "title": "Аккаунт 67 уровень Платина + ножи", "desc": "67 лвл, Платиновый ранг. 5 ножей включая Butterfly Fade. 38 скинов.", "price": 6200},
        {"cat": "Standoff 2", "title": "5000 золотых монет фаст", "desc": "Пополню голды на ваш аккаунт. 5000 монет. Моментально после оплаты.", "price": 850},
        {"cat": "Standoff 2", "title": "Аккаунт 5 уровень старт дёшево", "desc": "5 уровень, 2 скина. Хороший старт для новичка. Быстрая передача.", "price": 200},
        {"cat": "Standoff 2", "title": "1000 золотых монет фаст", "desc": "1000 монет на ваш аккаунт. Нужен только ник. Отправлю за 10 минут.", "price": 250},
        {"cat": "Standoff 2", "title": "Аккаунт 10 уровень 3 скина", "desc": "10 уровень, 3 скина оружия включая АК Vulcan копия. Дёшево!", "price": 300},
        {"cat": "Standoff 2", "title": "2000 золотых монет выгодно", "desc": "2000 монет. Работаю быстро, честно. 70+ продаж.", "price": 380},
        {"cat": "Standoff 2", "title": "Аккаунт 8 уровень нож перочинный", "desc": "8 уровень, перочинный нож + 2 скина. Хорошее начало.", "price": 350},
        {"cat": "Standoff 2", "title": "Акк 67лвл | нож Бабочка Fade | Platinum ранг | фаст", "desc": "67 уровень, нож Бабочка Fade — один из самых ценных. Ранг Платина.", "price": 8500},
        {"cat": "Standoff 2", "title": "Акк 38лвл | Gold ранг | АК Черная Жемчужина | фаст", "desc": "АК-47 Чёрная Жемчужина, ранг Золото. Красивый акк.", "price": 3200},
        {"cat": "Standoff 2", "title": "2000 голды фаст | нужен только ник | без предоплаты", "desc": "2000 золотых монет за 10 минут. Работаю без предоплаты.", "price": 380},
        {"cat": "Standoff 2", "title": "Акк 52лвл | нож Керамбит Doppler | куча скинов", "desc": "Нож Керамбит Doppler, много скинов оружия. Хороший акк.", "price": 6200},
        {"cat": "Standoff 2", "title": "Акк 15лвл | 5 скинов | отдам дёшево | без привязки", "desc": "5 скинов, 15 уровень. Продаю недорого, без привязки к номеру.", "price": 350},
        {"cat": "Standoff 2", "title": "5000 голды | нужен ник | пополняю быстро | фаст", "desc": "5000 золота на ваш акк. Быстрое пополнение, много продаж.", "price": 850},
        {"cat": "Standoff 2", "title": "Акк 44лвл | нож Штык-нож Crimson Web | Gold ранг", "desc": "Штык-нож Crimson Web, ранг Золото, 44 уровень. Отличный акк.", "price": 4100},
        {"cat": "Standoff 2", "title": "Акк 29лвл | Silver ранг | М4А1 Dragon | передам быстро", "desc": "М4А1 Dragon скин, ранг Серебро. Быстрая передача.", "price": 1200},
        {"cat": "Standoff 2", "title": "10000 голды оптом | самая низкая цена | фаст", "desc": "10000 золота по самой низкой цене. Пополняю быстро.", "price": 1600},
        {"cat": "Standoff 2", "title": "Акк 73лвл | все топ скины | нож Gut Knife Fade | редкий", "desc": "73 уровень, нож Gut Knife Fade, коллекция топ скинов. Редкий акк.", "price": 11000},
        {"cat": "Standoff 2", "title": "Акк 8лвл | пара скинов | только начал играть | дёшево", "desc": "Начальный акк, пара скинов. Продаю так как перестал играть.", "price": 200},
        {"cat": "Standoff 2", "title": "3000 голды | без предоплаты | нужен ник | проверенный", "desc": "3000 золота без предоплаты. Проверенный продавец.", "price": 550},
        {"cat": "Standoff 2", "title": "Акк 58лвл | Platinum ранг | MP5 | M4A4 Howl копия", "desc": "Platinum ранг, M4A4 Howl копия и MP5 скин. Хороший набор.", "price": 4800},
        {"cat": "Standoff 2", "title": "Акк 21лвл | Bronze ранг | АК Vulcan | передам фаст", "desc": "АК Vulcan скин, Bronze ранг. Хорошее начало для нового игрока.", "price": 650},
        {"cat": "Standoff 2", "title": "1000 голды дёшево | нужен ник | 5 минут", "desc": "1000 золота за 5 минут. Самая низкая цена.", "price": 200},
        {"cat": "Standoff 2", "title": "Акк 85лвл | нож Butterfly Sapphire | топ акк | дорого", "desc": "85 уровень, легендарный нож Butterfly Sapphire. Один из лучших.", "price": 22000},
        {"cat": "Standoff 2", "title": "Акк 34лвл | Gold ранг | 14 скинов оружия | почта есть", "desc": "14 скинов оружия, ранг Золото, почта в комплекте.", "price": 2100},
        {"cat": "Standoff 2", "title": "500 голды быстро | нужен ник | честно и надёжно", "desc": "500 золота за 3 минуты. Честно и надёжно.", "price": 120},
        {"cat": "Standoff 2", "title": "Акк 47лвл | нож Карамбит Ultraviolet | Silver ранг", "desc": "Нож Карамбит Ultraviolet, Silver ранг, 47 уровень.", "price": 3800},
        {"cat": "Steam", "title": "Steam пополнение 500 рублей фаст", "desc": "Пополню кошелёк Steam на 500р. Активирую код в течение 15 минут.", "price": 580},
        {"cat": "Steam", "title": "Аккаунт Steam 47 игр + CS2 Prime", "desc": "47 игр, CS2 с Prime статусом, GTA V, RDR2. 2800 часов в играх.", "price": 4500},
        {"cat": "Steam", "title": "Steam 1000 рублей выгодно", "desc": "Пополнение Steam 1000р. Работаю быстро, более 300 продаж.", "price": 1100},
        {"cat": "Steam", "title": "Аккаунт 12 лет Steam + редкие игры", "desc": "Аккаунт с 2012 года, 89 игр, значки, торговые карточки.", "price": 3800},
        {"cat": "Steam", "title": "Steam пополнение 200 рублей фаст", "desc": "Пополню кошелёк Steam на 200р. Активирую код за 15 минут.", "price": 230},
        {"cat": "Steam", "title": "Steam 300 рублей быстро", "desc": "300р на Steam кошелёк. Работаю честно, более 200 продаж.", "price": 340},
        {"cat": "Steam", "title": "Аккаунт Steam 5 игр инди", "desc": "5 инди игр: Stardew Valley, Terraria, Celeste и др. Старый аккаунт.", "price": 350},
        {"cat": "Steam", "title": "Steam 400 рублей выгодно", "desc": "400р на кошелёк Steam. Ниже рыночной цены. Фаст.", "price": 380},
        {"cat": "Steam", "title": "Аккаунт Steam Dota 2 500 часов", "desc": "Аккаунт с Dota 2, 500+ часов. Несколько косметических предметов.", "price": 300},
        {"cat": "Steam", "title": "Акк Steam | 89 игр | GTA V + RDR2 + Cyberpunk | 3400ч", "desc": "89 игр, 3400 часов наигрыша. GTA V, Red Dead 2, Cyberpunk 2077 в наличии.", "price": 4500},
        {"cat": "Steam", "title": "Пополнение Steam 500р фаст | активирую код за 15 минут", "desc": "500 рублей на Steam кошелёк. Активирую код в течение 15 минут.", "price": 570},
        {"cat": "Steam", "title": "Акк Steam | CS2 Prime | 1200ч | инвентарь 3000р", "desc": "CS2 с Prime, 1200 часов, инвентарь на 3000 рублей. Без банов.", "price": 2800},
        {"cat": "Steam", "title": "Steam 1000р выгодно | ниже официальной цены | фаст", "desc": "1000 рублей на Steam. Ниже официальной цены.", "price": 1100},
        {"cat": "Steam", "title": "Акк Steam 2015 года | 156 игр | значки и карточки | фаст", "desc": "Акк с 2015 года, 156 игр, коллекция значков и торговых карточек.", "price": 6200},
        {"cat": "Steam", "title": "200р на Steam фаст | нужен только логин | 10 минут", "desc": "200 рублей на кошелёк Steam за 10 минут.", "price": 230},
        {"cat": "Steam", "title": "Акк Steam | Dota 2 | 4500ч | Immortal ранг | скины", "desc": "4500 часов в Dota 2, ранг Бессмертный, редкие скины на героях.", "price": 5500},
        {"cat": "Steam", "title": "Steam 300р быстро | без предоплаты | проверенный", "desc": "300 рублей на Steam без предоплаты. Много положительных отзывов.", "price": 340},
        {"cat": "Steam", "title": "Акк Steam | 12 лет | 200+ игр | редкие ранние игры", "desc": "Аккаунт с 2013 года, более 200 игр включая редкие ранние тайтлы.", "price": 8900},
        {"cat": "Steam", "title": "Steam 2000р выгодно | дешевле официального | фаст", "desc": "2000 рублей на Steam ниже официальной цены.", "price": 2100},
        {"cat": "Steam", "title": "Акк Steam | Rust 800ч + PUBG + Hunt Showdown | фаст", "desc": "Rust 800 часов, PUBG, Hunt Showdown. Хороший набор игр.", "price": 3200},
        {"cat": "Steam", "title": "100р на Steam | минимальный номинал | фаст 5 минут", "desc": "100 рублей на Steam. Быстрее всех на рынке.", "price": 120},
        {"cat": "Steam", "title": "Акк Steam | Valorant + CS2 Prime | 600ч | без банов", "desc": "CS2 Prime и Valorant на одном акке. 600 часов, чистая история.", "price": 1800},
        {"cat": "Steam", "title": "Steam 500р | нужен логин | пополняю за 15 минут | фаст", "desc": "500 рублей на кошелёк. Нужен логин от Steam.", "price": 570},
        {"cat": "Steam", "title": "Акк Steam | 7 лет | 80 игр | CS2 + Dota + GTA V", "desc": "Аккаунт с 2018 года, 80 игр, CS2 и Dota 2 и GTA V.", "price": 3800},
        {"cat": "Steam", "title": "Steam 1500р | самый выгодный курс | фаст", "desc": "1500 рублей на Steam по выгодному курсу.", "price": 1580},
        {"cat": "Steam", "title": "Акк Steam | инди коллекция 45 игр | Stardew + Hades | фаст", "desc": "45 инди игр: Stardew Valley, Hades, Hollow Knight и другие хиты.", "price": 1400},
        {"cat": "Steam", "title": "400р на Steam | быстро и честно | 200+ продаж", "desc": "400 рублей на Steam. Более 200 успешных пополнений.", "price": 450},
        {"cat": "Steam", "title": "Акк Steam | 9 лет | 120 игр | есть Cyberpunk 2077 | фаст", "desc": "Аккаунт с 2016 года, 120 игр, Cyberpunk 2077 в наличии.", "price": 4100},
        {"cat": "Steam", "title": "Steam 250р фаст | нужен логин | без обмана | надёжно", "desc": "250 рублей на Steam. Надёжно и без обмана.", "price": 280},
        {"cat": "CS2", "title": "Аккаунт CS2 Prime MG2 ранг", "desc": "Prime статус, ранг MG2. 1200 часов. Скин AWP Asiimov Field Tested.", "price": 2200},
        {"cat": "CS2", "title": "AK-47 Redline FT продажа скина", "desc": "Скин AK-47 Redline Field Tested. Передам через трейд.", "price": 900},
        {"cat": "CS2", "title": "Аккаунт CS2 Supreme + AWP Dragon Lore", "desc": "Supreme ранг! AWP Dragon Lore Field Tested. 3400 часов. Топовый аккаунт.", "price": 28000},
        {"cat": "CS2", "title": "CS2 Prime активация аккаунта", "desc": "Активирую Prime статус на вашем аккаунте. Безопасно и быстро.", "price": 1400},
        {"cat": "CS2", "title": "Аккаунт CS2 Gold Nova 3, чистый", "desc": "Gold Nova 3, 680 часов. Чистый аккаунт без банов.", "price": 1800},
        {"cat": "CS2", "title": "Аккаунт CS2 Silver 2 чистый", "desc": "Silver 2, 120 часов. Чистый без банов. Хорошо для старта.", "price": 350},
        {"cat": "CS2", "title": "Скин P250 Sand Dune FT", "desc": "Скин P250 Sand Dune Field Tested. Чистый, без критичных царапин.", "price": 200},
        {"cat": "CS2", "title": "Аккаунт CS2 без ранга 80ч", "desc": "Аккаунт без ранга, 80 часов. Для разогрева или alt-аккаунта.", "price": 250},
        {"cat": "CS2", "title": "Аккаунт CS2 Silver 4 + кейс Chroma", "desc": "Silver 4, кейс Chroma в инвентаре. 200 часов. Без банов.", "price": 380},
        {"cat": "CS2", "title": "Нож Gut Knife Scorched BS дёшево", "desc": "Gut Knife Scorched Battle Scarred. Нож дёшево!", "price": 390},
        {"cat": "CS2", "title": "Акк CS2 | Supreme | AWP Asiimov FT | 2800ч | без банов", "desc": "Supreme ранг, AWP Asiimov Field Tested, 2800 часов. Чистый акк без банов.", "price": 4200},
        {"cat": "CS2", "title": "Акк CS2 | AK-47 Redline | M4A4 Howl FT | инвентарь 8к", "desc": "AK Redline и M4A4 Howl Field Tested. Инвентарь на 8000 рублей.", "price": 7500},
        {"cat": "CS2", "title": "Акк CS2 Prime | MG2 ранг | 900ч | чистый | фаст", "desc": "CS2 Prime, ранг MG2, 900 часов. Без банов, передача быстро.", "price": 2100},
        {"cat": "CS2", "title": "Акк CS2 | нож Butterfly Fade | топ инвентарь | фаст", "desc": "Butterfly Knife Fade — один из редчайших ножей. Топ инвентарь.", "price": 35000},
        {"cat": "CS2", "title": "Акк CS2 | Gold Nova 3 | 400ч | Prime | без банов | фаст", "desc": "Gold Nova 3, 400 часов, Prime статус. Хороший акк без истории банов.", "price": 1800},
        {"cat": "CS2", "title": "Акк CS2 | Global Elite | 5000ч | много скинов | почта", "desc": "Global Elite ранг, 5000 часов, большая коллекция скинов. Почта передаётся.", "price": 12000},
        {"cat": "CS2", "title": "Акк CS2 | Silver 4 | 120ч | Prime | чистый | дёшево", "desc": "Silver 4, Prime, 120 часов. Чистый акк по низкой цене.", "price": 650},
        {"cat": "CS2", "title": "Акк CS2 | AK Vulcan FT + M4 Asiimov | LEM ранг | фаст", "desc": "AK Vulcan и M4A1 Asiimov, ранг LEM. Хороший акк для игры.", "price": 3800},
        {"cat": "CS2", "title": "Акк CS2 | 10 лет | 3000ч | редкие значки и медали | фаст", "desc": "Акк с 2015 года, 3000 часов, редкие юбилейные медали и значки.", "price": 5500},
        {"cat": "CS2", "title": "Акк CS2 | без ранга | 50ч | Prime | для старта | дёшево", "desc": "Prime акк без ранга, 50 часов. Отличный старт для новичка.", "price": 400},
        {"cat": "CS2", "title": "Акк CS2 | AWP Dragon Lore FN | топ акк | очень дорого", "desc": "AWP Dragon Lore Factory New — самый редкий скин. Серьёзный акк.", "price": 55000},
        {"cat": "CS2", "title": "Акк CS2 | Legendary Eagle | 1500ч | AK Redline | фаст", "desc": "LE ранг, 1500 часов, AK Redline в инвентаре. Хороший акк.", "price": 2900},
        {"cat": "CS2", "title": "Скин AK-47 Asiimov FT | трейд | чистый | фаст", "desc": "AK-47 Asiimov Field Tested. Передача через трейд, чистый скин.", "price": 1200},
        {"cat": "CS2", "title": "Акк CS2 | Supreme + | 2200ч | несколько ножей | фаст", "desc": "Supreme+, 2200 часов, несколько ножей в инвентаре. Хорошая цена.", "price": 6800},
        {"cat": "CS2", "title": "Акк CS2 | Gold Nova 1 | 250ч | Prime | без банов | фаст", "desc": "GN1 ранг, 250 часов, Prime. Чистый акк без VAC банов.", "price": 1100},
        {"cat": "CS2", "title": "Скин AWP Asiimov FT | трейд | популярный | фаст", "desc": "AWP Asiimov Field Tested. Очень популярный скин, передача через трейд.", "price": 2800},
        {"cat": "CS2", "title": "Акк CS2 | 8 лет | 4000ч | Faceit Level 8 | фаст", "desc": "8 лет акку, 4000 часов, 8 уровень Faceit. Опытный игрок.", "price": 7200},
        {"cat": "CS2", "title": "Акк CS2 | MG1 ранг | 600ч | Prime | AK Redline | фаст", "desc": "MG1 ранг, 600 часов, Prime, AK Redline скин в инвентаре.", "price": 2400},
        {"cat": "CS2", "title": "Скин M4A4 Howl FT | трейд | редкий | цена договорная", "desc": "M4A4 Howl Field Tested — один из самых редких скинов CS2.", "price": 18000},
        {"cat": "CS2", "title": "Акк CS2 | DMG ранг | 1800ч | Prime | фаст без банов", "desc": "Distinguished Master Guardian, 1800 часов, Prime. Опытный акк.", "price": 3500},
    ]
    for d in demo_products:
        pid = product_counter[0]
        product_counter[0] += 1
        products[pid] = {
            "title": d["title"], "description": d["desc"], "price": d["price"],
            "category": d["cat"], "seller_id": ADMIN_ID, "seller_name": "SmartSales", "photos": []
        }
        sellers[ADMIN_ID]["products"].append(pid)
        views_count[pid] = 0
        reviews[pid] = []
    promo_codes["SMART10"] = {"seller_id": ADMIN_ID, "discount_pct": 10, "uses_left": 100}
    promo_codes["SALE20"] = {"seller_id": ADMIN_ID, "discount_pct": 20, "uses_left": 50}
init_demo()
load_banners()  # Восстанавливаем баннеры после перезапуска

def get_seller_rating(seller_id):
    total, count = 0, 0
    for pid in sellers.get(seller_id, {}).get("products", []):
        for r in reviews.get(pid, []):
            total += r["rating"]
            count += 1
    return round(total / count, 1) if count else 5.0

# ================================================================
# /start
# ================================================================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_states[uid] = None
    all_users.add(uid)
    is_seller = uid in sellers
    kb = [
        [InlineKeyboardButton("🛒 Каталог товаров", callback_data="catalog"),
         InlineKeyboardButton("🔍 Поиск", callback_data="search")],
        [InlineKeyboardButton("🤖 Купить ИИ-помощника", callback_data="buy_ai")],
        [InlineKeyboardButton("❤️ Избранное", callback_data="favorites"),
         InlineKeyboardButton("🗂 Мои покупки", callback_data="my_purchases")],
        [InlineKeyboardButton("🏆 Топ продавцов", callback_data="top_sellers")],
    ]
    if is_seller:
        kb.insert(2, [InlineKeyboardButton("🏪 Мой магазин", callback_data="my_shop")])
    else:
        kb.append([InlineKeyboardButton("📦 Стать продавцом", callback_data="become_seller")])
    online, viewers = get_fake_online()
    text = (
        f"🎮 *SmartSalesAI* — цифровой магазин\n\n"
        f"🟢 Сейчас онлайн: *{online} человек*\n"
        f"👁 Просматривают товары: *{viewers}*\n\n"
        "⚡ Отвечаю клиентам за 3 секунды (24/7)\n"
        "💰 Продаю и консультирую как живой эксперт\n"
        "📦 Моментально выдаю товар после оплаты\n\n"
        "Твой бизнес больше не спит. Давай начнём!"
    )
    bottom_kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📖 Как работает бот"), KeyboardButton("🛒 Каталог")]],
        resize_keyboard=True, is_persistent=True
    )
    # Удаляем предыдущее сообщение бота чтобы не засорять чат
    if uid in last_bot_message:
        try:
            await ctx.bot.delete_message(chat_id=uid, message_id=last_bot_message[uid])
        except Exception:
            pass

    sent = await update.effective_message.reply_text(
        text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    last_bot_message[uid] = sent.message_id

# ================================================================
# ПОМОЩЬ / КАТАЛОГ
# ================================================================
async def help_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Как работает SmartSalesAI*\n\n"
        "🛒 *Покупателям:*\n"
        "• Выбери категорию → найди товар\n"
        "• Нажми «Написать продавцу»\n"
        "• Если продавец не ответил — ИИ ответит за него\n"
        "• Используй промокод для скидки\n\n"
        "🏪 *Продавцам:*\n"
        "• Нажми «Стать продавцом» → добавь товары\n"
        "• Купи ИИ-помощника за 500₽/мес\n"
        "• ИИ продаёт за тебя пока ты спишь 😴\n\n"
        "📣 *Реклама для продавцов:*\n"
        "• Основной баннер в каталоге — 500₽/мес\n"
        "• Саб-баннер в категории — 200₽/мес\n"
        "• Топ в категории — 200₽/нед\n"
        "• Рассылка всем — 300₽\n"
        "• Бейдж Проверен — 300₽/мес\n\n"
        f"По вопросам рекламы: @{ADMIN_USERNAME}"
    )
    uid = update.effective_user.id
    if uid in last_bot_message:
        try:
            await ctx.bot.delete_message(chat_id=uid, message_id=last_bot_message[uid])
        except Exception:
            pass
    sent = await update.effective_message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Начать", callback_data="back_main")]]))
    last_bot_message[uid] = sent.message_id

async def show_catalog_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    kb = [[InlineKeyboardButton(f"{CAT_EMOJI.get(c,'📦')} {c}", callback_data=f"cat_{c}")] for c in CATEGORIES]
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="back_main")])
    # Удаляем предыдущее сообщение бота
    if uid in last_bot_message:
        try:
            await ctx.bot.delete_message(chat_id=uid, message_id=last_bot_message[uid])
        except Exception:
            pass
    banner = state_store.get("catalog_banner")
    if banner and banner.get("photo_id"):
        # Отправляем одно сообщение: фото + подпись + кнопки категорий
        caption = banner.get("caption", "")
        full_caption = (caption + "\n\n" if caption else "") + "📂 Выберите категорию:"
        try:
            sent = await update.effective_message.reply_photo(
                photo=banner["photo_id"],
                caption=full_caption,
                reply_markup=InlineKeyboardMarkup(kb)
            )
            last_bot_message[uid] = sent.message_id
            return
        except Exception:
            pass
    sent = await update.effective_message.reply_text(
        "📂 *Выберите категорию:*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb))
    last_bot_message[uid] = sent.message_id

# ================================================================
# ПОИСК / ИЗБРАННОЕ / ТОП
# ================================================================
async def search_start(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    user_states[uid] = "searching"
    await query.edit_message_text(
        "🔍 *Поиск товаров*\n\nВведите название или ключевое слово:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back_main")]]))

async def do_search(uid, query_text, update, ctx):
    q = query_text.lower()
    found = [(pid, p) for pid, p in products.items()
             if q in p["title"].lower() or q in p["description"].lower() or q in p["category"].lower()]
    if not found:
        await update.message.reply_text(f"😔 По запросу *{query_text}* ничего не найдено.", parse_mode="Markdown")
        return
    kb = []
    for pid, p in found[:15]:
        kb.append([InlineKeyboardButton(f"{p['title']} — {p['price']}₽", callback_data=f"product_{pid}_0")])
    kb.append([InlineKeyboardButton("🔍 Новый поиск", callback_data="search"),
               InlineKeyboardButton("◀️ Меню", callback_data="back_main")])
    await update.message.reply_text(
        f"🔍 Найдено {len(found)}:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def show_favorites(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    fav = favorites.get(uid, set())
    if not fav:
        await query.edit_message_text(
            "❤️ *Избранное пусто*", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Каталог", callback_data="catalog"),
                                                InlineKeyboardButton("◀️ Назад", callback_data="back_main")]]))
        return
    kb = []
    for pid in fav:
        p = products.get(pid)
        if p:
            kb.append([InlineKeyboardButton(f"{p['title']} — {p['price']}₽", callback_data=f"product_{pid}_0")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="back_main")])
    await query.edit_message_text(f"❤️ *Избранное* — {len(fav)} товаров:", parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup(kb))

async def show_top_sellers(update, ctx):
    query = update.callback_query
    await query.answer()
    sorted_sellers = sorted([(uid, s) for uid, s in sellers.items()],
                            key=lambda x: top_sellers.get(x[0], 0), reverse=True)[:10]
    total_online, _ = get_fake_online()
    text = f"🏆 *Топ продавцов SmartSalesAI*\n🟢 Онлайн: {total_online} покупателей\n\n"
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    for i, (uid, s) in enumerate(sorted_sellers):
        rating = get_seller_rating(uid)
        sales = top_sellers.get(uid, 0)
        ai_badge = "🤖" if s.get("ai_enabled") else ""
        ver_badge = "✅" if uid in verified_sellers else ""
        text += f"{medals[i]} *{s['name']}* {ver_badge}{ai_badge}\n   ⭐ {rating} · 📦 {sales} продаж\n\n"
    await query.edit_message_text(text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back_main")]]))

# ================================================================
# КАТАЛОГ — с основным баннером
# ================================================================
async def show_catalog(update, ctx):
    query = update.callback_query
    uid = update.effective_user.id
    await query.answer()

    kb = [[InlineKeyboardButton(f"{CAT_EMOJI.get(c,'📦')} {c}", callback_data=f"cat_{c}")] for c in CATEGORIES]
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="back_main")])

    banner = state_store.get("catalog_banner")
    if banner and banner.get("photo_id"):
        caption = banner.get("caption", "")
        full_caption = (caption + "\n\n" if caption else "") + "📂 Выберите категорию:"
        await safe_edit_photo(query, uid, banner["photo_id"], full_caption, InlineKeyboardMarkup(kb))
    else:
        await safe_edit_text(query, uid, "📂 *Выберите категорию:*", InlineKeyboardMarkup(kb))

# ================================================================
# КАТЕГОРИЯ — с саб-баннером
# ================================================================
async def show_category(update, ctx, category, page=0):
    query = update.callback_query
    uid = update.effective_user.id
    await query.answer()

    ad_items = [(pid, products[pid]) for pid in ad_products
                if products.get(pid, {}).get("category") == category]
    reg_items = [(pid, p) for pid, p in products.items()
                 if p["category"] == category and pid not in ad_products]
    items = ad_items + reg_items
    if not items:
        await query.edit_message_text(
            "😔 Нет товаров.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="catalog")]]))
        return
    total = len(items)
    start_i = page * PAGE_SIZE
    end_i = start_i + PAGE_SIZE
    page_items = items[start_i:end_i]
    kb = []
    for pid, p in page_items:
        ad_badge = "📣 " if pid in ad_products else ""
        rev_list = reviews.get(pid, [])
        label = f"{ad_badge}{p['title']} — {p['price']}₽"
        if rev_list:
            avg = sum(r["rating"] for r in rev_list) / len(rev_list)
            label += f" ⭐{avg:.1f}"
        if p.get("seller_id") in verified_sellers:
            label += " ✅"
        kb.append([InlineKeyboardButton(label, callback_data=f"product_{pid}_0")])
    cat_idx = CATEGORIES.index(category) if category in CATEGORIES else 0
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"cp_{cat_idx}_{page-1}"))
    if end_i < total:
        nav.append(InlineKeyboardButton("Далее ▶️", callback_data=f"cp_{cat_idx}_{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("🔙 К категориям", callback_data="catalog")])
    showing = f"{start_i+1}–{min(end_i,total)} из {total}"
    base_online, _ = get_fake_online()
    cat_online = max(3, base_online // 6 + random.randint(-1, 1))

    # Саб-баннер — фото поверх сообщения с кнопками
    cat_banner = state_store.get("cat_banners", {}).get(category)
    cat_title = f"{CAT_EMOJI.get(category,'📦')} {category} — {total} товаров | {showing} · 🟢 {cat_online} онлайн"
    if cat_banner and page == 0 and cat_banner.get("photo_id"):
        caption = cat_banner.get("caption", "")
        full_caption = (caption + "\n\n" if caption else "") + cat_title
        await safe_edit_photo(query, uid, cat_banner["photo_id"], full_caption, InlineKeyboardMarkup(kb))
    else:
        await safe_edit_text(query, uid,
            f"{CAT_EMOJI.get(category,'📦')} *{category}* — {total} товаров\n_{showing}_ · 🟢 {cat_online} онлайн",
            InlineKeyboardMarkup(kb))

async def show_product(update, ctx, pid, photo_idx=0):
    query = update.callback_query
    await query.answer()
    p = products.get(pid)
    if not p:
        await query.edit_message_text("Товар не найден.")
        return
    views_count[pid] = views_count.get(pid, 0) + 1
    if views_count[pid] % 5 == 0:
        try:
            await ctx.bot.send_message(p["seller_id"],
                f"👁 Ваш товар *{p['title']}* просмотрели {views_count[pid]} раз!",
                parse_mode="Markdown")
        except Exception:
            pass
    seller = sellers.get(p["seller_id"], {})
    uid = update.effective_user.id
    is_fav = pid in favorites.get(uid, set())
    fav_btn = "💔 Убрать" if is_fav else "❤️ В избранное"
    ai_badge = "\n🤖 _ИИ-продавец онлайн 24/7_" if seller.get("ai_enabled") else ""
    ver_badge = " ✅" if p.get("seller_id") in verified_sellers else ""
    rev_list = reviews.get(pid, [])
    rev_text = ""
    if rev_list:
        avg = sum(r["rating"] for r in rev_list) / len(rev_list)
        rev_text = f"\n⭐ Рейтинг: {avg:.1f} ({len(rev_list)} отзывов)"
    seller_rating = get_seller_rating(p["seller_id"])
    text = (
        f"🛍 *{p['title']}*\n\n"
        f"📝 {p['description']}\n\n"
        f"💰 Цена: *{p['price']}₽*\n"
        f"📂 {p['category']}\n"
        f"👤 Продавец: {p['seller_name']}{ver_badge} ⭐{seller_rating}"
        f"{rev_text}{ai_badge}\n"
        f"👁 Просмотров: {views_count.get(pid, 0)}\n"
        f"🔥 Смотрят сейчас: *{max(1, _fake_online['value'] // 20 + random.randint(0, 2))} чел.*"
    )
    kb = [
        [InlineKeyboardButton("💬 Написать продавцу", callback_data=f"chat_seller_{pid}")],
        [InlineKeyboardButton("🎟 Промокод", callback_data=f"promo_{pid}"),
         InlineKeyboardButton(fav_btn, callback_data=f"fav_{pid}")],
        [InlineKeyboardButton("📝 Отзывы", callback_data=f"reviews_{pid}"),
         InlineKeyboardButton("🤝 Гарантия", callback_data=f"guarantee_{pid}")],
        [InlineKeyboardButton("◀️ Назад", callback_data=f"cat_{p['category']}")],
    ]
    uid_p = update.effective_user.id
    await safe_edit_text(query, uid_p, text, InlineKeyboardMarkup(kb))

# ================================================================
# ОТЗЫВЫ / ПРОМОКОД / ГАРАНТИЯ
# ================================================================
async def show_reviews(update, ctx, pid):
    query = update.callback_query
    await query.answer()
    p = products.get(pid, {})
    rev_list = reviews.get(pid, [])
    if not rev_list:
        text = f"📝 *Отзывы*\n_{p.get('title','')}_\n\nОтзывов пока нет."
    else:
        avg = sum(r["rating"] for r in rev_list) / len(rev_list)
        text = f"📝 *Отзывы* — {p.get('title','')}\n⭐ {avg:.1f}/5\n\n"
        for r in rev_list[-5:]:
            text += f"{'⭐'*r['rating']} *{r['buyer_name']}*\n{r['text']}\n\n"
    kb = [[InlineKeyboardButton("✍️ Оставить отзыв", callback_data=f"leave_review_{pid}")],
          [InlineKeyboardButton("◀️ Назад", callback_data=f"product_{pid}_0")]]
    uid_r = update.effective_user.id
    await safe_edit_text(query, uid_r, text, InlineKeyboardMarkup(kb))

async def promo_start(update, ctx, pid):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    user_states[uid] = f"entering_promo_{pid}"
    await query.edit_message_text(
        "🎟 *Введите промокод:*", parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data=f"product_{pid}_0")]]))

async def guarantee_start(update, ctx, pid):
    query = update.callback_query
    await query.answer()
    p = products.get(pid, {})
    kb = [[InlineKeyboardButton("✅ Подтвердить получение", callback_data=f"guarantee_ok_{pid}")],
          [InlineKeyboardButton("❌ Открыть спор", callback_data=f"guarantee_dispute_{pid}")],
          [InlineKeyboardButton("◀️ Назад", callback_data=f"product_{pid}_0")]]
    await query.edit_message_text(
        f"🤝 *Гарантия сделки*\n\nТовар: _{p.get('title','')}_\nЦена: *{p.get('price',0)}₽*\n\n"
        "После получения нажмите «Подтвердить».\nЕсли проблема — «Открыть спор».",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

# ================================================================
# ЧАТ / ИИ
# ================================================================
async def start_chat(update, ctx, pid):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    p = products.get(pid)
    if not p:
        return
    seller_id = p["seller_id"]
    if uid == seller_id:
        await query.edit_message_text("❌ Нельзя написать самому себе.")
        return
    active_chats[uid] = {"seller_id": seller_id, "product_id": pid, "ai_replied": False}
    user_states[uid] = f"chatting_{seller_id}_{pid}"
    buyer_name = update.effective_user.first_name or str(uid)
    await query.edit_message_text(
        f"💬 *Чат с {p['seller_name']}*\n\nТовар: _{p['title']}_\nЦена: *{p['price']}₽*\n\n"
        "✍️ Напишите сообщение.\n⏱ Если не ответит — ИИ ответит за него.\n\n/start — выйти",
        parse_mode="Markdown")
    try:
        kb = [[InlineKeyboardButton(f"↩️ Ответить {buyer_name}", callback_data=f"reply_to_{uid}")]]
        await ctx.bot.send_message(seller_id,
            f"📩 *Новый покупатель!*\n👤 {buyer_name}\n🛍 *{p['title']}* — {p['price']}₽",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    except Exception:
        pass
    if uid in pending_ai_tasks:
        pending_ai_tasks[uid].cancel()
    asyncio.create_task(ai_instant_intro(ctx, uid, pid, buyer_name))
    task = asyncio.create_task(ai_reply_after_delay(ctx, uid, pid, buyer_name))
    pending_ai_tasks[uid] = task

async def ai_instant_intro(ctx, buyer_id, pid, buyer_name):
    """ИИ отвечает покупателю через таймер продавца"""
    chat_info = active_chats.get(buyer_id, {})
    seller_id = chat_info.get("seller_id")
    seller_tmp = sellers.get(seller_id, {})
    timer_key = seller_tmp.get("ai_timer", "2m")
    delay = AI_TIMERS.get(timer_key, ("2 минуты", 120))[1]

    logger.info(f"AI timer started: {delay}s for buyer {buyer_id}, seller {seller_id}")
    await asyncio.sleep(delay)

    chat = active_chats.get(buyer_id)
    if not chat or chat.get("ai_replied"):
        logger.info(f"AI skipped: chat={chat}, ai_replied={chat.get('ai_replied') if chat else None}")
        return

    p = products.get(pid, {})
    seller = sellers.get(seller_id, {})

    if not seller.get("ai_enabled") or not seller.get("ai_paid"):
        logger.info(f"AI disabled for seller {seller_id}: enabled={seller.get('ai_enabled')} paid={seller.get('ai_paid')}")
        return

    prompt = seller.get("ai_prompt", "") or DEFAULT_AI_PROMPT
    seller_prods = [products[pid2] for pid2 in seller.get("products", []) if pid2 in products]
    other_prods = [p2["title"] for p2 in seller_prods if p2["title"] != p.get("title","")][:3]
    other_text = f"\nДругие товары продавца: {', '.join(other_prods)}" if other_prods else ""

    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": f"{prompt}\nТовар: {p.get('title','')}. {p.get('description','')}. Цена: {p.get('price','')}₽.{other_text}"},
                {"role": "user", "content": f"Покупатель {buyer_name} написал. Ответь коротко — представься и назови 2-3 преимущества товара. Максимум 3 предложения на русском."}
            ], max_tokens=200)
        ai_text = resp.choices[0].message.content
        chat["ai_replied"] = True
        seller_name = seller.get("name", "Продавец")
        await ctx.bot.send_message(buyer_id, f"🤖 *{seller_name}:*\n\n{ai_text}", parse_mode="Markdown")
        logger.info(f"AI replied OK to buyer {buyer_id}")
    except Exception as e:
        logger.error(f"AI intro error: {e}")

async def ai_reply_after_delay(ctx, buyer_id, pid, buyer_name):
    """Резервный ответ если покупатель написал снова"""
    chat_info = active_chats.get(buyer_id, {})
    seller_id = chat_info.get("seller_id")
    seller_tmp = sellers.get(seller_id, {})
    timer_key = seller_tmp.get("ai_timer", "2m")
    delay = AI_TIMERS.get(timer_key, ("2 минуты", 120))[1]

    await asyncio.sleep(delay + 30)

    chat = active_chats.get(buyer_id)
    if not chat or chat.get("ai_replied"):
        return

    p = products.get(pid, {})
    seller = sellers.get(seller_id, {})

    if not seller.get("ai_enabled") or not seller.get("ai_paid"):
        return

    prompt = seller.get("ai_prompt", "") or DEFAULT_AI_PROMPT
    seller_prods = [products[pid2] for pid2 in seller.get("products", []) if pid2 in products]
    other_prods = [p2["title"] for p2 in seller_prods if p2["title"] != p.get("title","")][:3]
    other_text = f"\nДругие товары: {', '.join(other_prods)}" if other_prods else ""

    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": f"{prompt}\nТовар: {p.get('title','')}. {p.get('description','')}. Цена: {p.get('price','')}₽.{other_text} Отвечай кратко на русском."},
                {"role": "user", "content": f"Покупатель {buyer_name} ещё ждёт. Уточни детали и предложи помочь. 2 предложения."}
            ], max_tokens=150)
        ai_text = resp.choices[0].message.content
        chat["ai_replied"] = True
        await ctx.bot.send_message(buyer_id, f"🤖 *ИИ-продавец:*\n\n{ai_text}", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"AI delay error: {e}")

# ================================================================
# МОЙ МАГАЗИН
# ================================================================
async def my_shop(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    s = sellers.get(uid, {})
    ai_status = "✅" if s.get("ai_enabled") and s.get("ai_paid") else "❌"
    my_prods = [p for p in s.get("products", []) if p in products]
    total_views = sum(views_count.get(p, 0) for p in my_prods)
    total_reviews = sum(len(reviews.get(p, [])) for p in my_prods)
    rating = get_seller_rating(uid)
    sales = top_sellers.get(uid, 0)
    ver_badge = " ✅ Проверен" if uid in verified_sellers else ""
    kb = [
        [InlineKeyboardButton("➕ Добавить товар", callback_data="add_product"),
         InlineKeyboardButton("📦 Мои товары", callback_data="list_my_products")],
        [InlineKeyboardButton(f"🤖 ИИ: {ai_status}", callback_data="ai_settings"),
         InlineKeyboardButton("🎟 Промокоды", callback_data="my_promos")],
        [InlineKeyboardButton("📣 Реклама", callback_data="ad_menu"),
         InlineKeyboardButton("📊 Статистика", callback_data="my_stats")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
    ]
    await query.edit_message_text(
        f"🏪 *Мой магазин*{ver_badge}\n\n"
        f"👤 {s.get('name','')}\n"
        f"📦 Товаров: {len(my_prods)}\n"
        f"⭐ Рейтинг: {rating}\n"
        f"📦 Продаж: {sales}\n"
        f"👁 Просмотров: {total_views}\n"
        f"📝 Отзывов: {total_reviews}\n"
        f"🤖 ИИ: {ai_status}",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

# ================================================================
# РЕКЛАМНОЕ МЕНЮ — с баннерами
# ================================================================
async def ad_menu(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    ver_status = "✅ Активен" if uid in verified_sellers else "❌ Нет"
    has_cat_banner = any(v.get("seller_id") == uid for v in state_store["cat_banners"].values())
    has_main_banner = state_store["catalog_banner"] and state_store["catalog_banner"].get("seller_id") == uid
    main_status = "✅ Активен" if has_main_banner else "❌ Нет"
    cat_status = "✅ Активен" if has_cat_banner else "❌ Нет"
    kb = [
        [InlineKeyboardButton("🖼 Основной баннер в каталоге", callback_data="ad_main_banner")],
        [InlineKeyboardButton("🎯 Саб-баннер в категории", callback_data="ad_cat_banner")],
        [InlineKeyboardButton("📣 Топ в категории", callback_data="advertise")],
        [InlineKeyboardButton("📢 Рассылка пользователям", callback_data="ad_broadcast")],
        [InlineKeyboardButton("✅ Бейдж «Проверен»", callback_data="ad_verified")],
        [InlineKeyboardButton("◀️ Назад", callback_data="my_shop")],
    ]
    text = (
        "📣 *Реклама в SmartSalesAI*\n\n"
        f"🖼 Основной баннер в каталоге: {main_status}\n"
        f"   3 дня — *{AD_BANNER_3D}₽* | неделя — *{AD_BANNER_7D}₽*\n\n"
        f"🎯 Саб-баннер в категории: {cat_status}\n"
        f"   3 дня — *{AD_CAT_3D}₽* | неделя — *{AD_CAT_7D}₽*\n\n"
        f"📣 Топ в категории — *{AD_TOP_PRICE}₽/нед*\n"
        f"📢 Рассылка всем — *{VERIFIED_PRICE}₽*\n"
        f"✅ Бейдж «Проверен»: {ver_status} — *{VERIFIED_PRICE}₽/мес*\n\n"
        f"Оплата: ЮMoney `{YOOMONEY_WALLET}`\n"
        f"После оплаты пишите @{ADMIN_USERNAME}"
    )
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

# ----------------------------------------------------------------
# ОСНОВНОЙ БАННЕР в каталоге
# Логика: бот просто просит фото — никакого списка товаров
# ----------------------------------------------------------------
async def ad_main_banner_page(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    has_banner = state_store["catalog_banner"] and state_store["catalog_banner"].get("seller_id") == uid
    yoo_3d = f"https://yoomoney.ru/transfer/quickpay?receiver={YOOMONEY_WALLET}&sum={AD_BANNER_3D}&label=mainbanner3d_{uid}&targets=Баннер+3дня+SmartSalesAI"
    yoo_7d = f"https://yoomoney.ru/transfer/quickpay?receiver={YOOMONEY_WALLET}&sum={AD_BANNER_7D}&label=mainbanner7d_{uid}&targets=Баннер+неделя+SmartSalesAI"
    kb = []
    if has_banner:
        kb.append([InlineKeyboardButton("❌ Снять баннер", callback_data="remove_main_banner")])
    else:
        kb.append([InlineKeyboardButton(f"💳 3 дня — {AD_BANNER_3D}₽", url=yoo_3d)])
        kb.append([InlineKeyboardButton(f"💳 Неделя — {AD_BANNER_7D}₽", url=yoo_7d)])
        kb.append([InlineKeyboardButton("✅ Я оплатил — загрузить баннер", callback_data="upload_main_banner")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="ad_menu")])
    text = (
        "🖼 *Основной баннер в каталоге*\n\n"
        f"3 дня — *{AD_BANNER_3D}₽*\n"
        f"Неделя — *{AD_BANNER_7D}₽*\n\n"
        "Ваш баннер (картинка) показывается каждому кто открывает каталог.\n"
        f"Охват: все пользователи бота.\n\n"
        "После оплаты нажмите «Я оплатил» и отправьте фото баннера.\n"
        "На фото можно указать ваш контакт, цену, условия."
    )
    if has_banner:
        text += "\n\n✅ *Ваш баннер сейчас активен!*"
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

# ----------------------------------------------------------------
# САБ-БАННЕР в категории
# Логика: выбираешь категорию → бот просит фото → фото показывается сверху в категории
# ----------------------------------------------------------------
async def ad_cat_banner_page(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    my_cat_banners = [cat for cat, b in state_store["cat_banners"].items() if b.get("seller_id") == uid]
    yoo_3d = f"https://yoomoney.ru/transfer/quickpay?receiver={YOOMONEY_WALLET}&sum={AD_CAT_3D}&label=catbanner3d_{uid}&targets=Саб-баннер+3дня+SmartSalesAI"
    yoo_7d = f"https://yoomoney.ru/transfer/quickpay?receiver={YOOMONEY_WALLET}&sum={AD_CAT_7D}&label=catbanner7d_{uid}&targets=Саб-баннер+неделя+SmartSalesAI"
    kb = [
        [InlineKeyboardButton(f"💳 3 дня — {AD_CAT_3D}₽", url=yoo_3d)],
        [InlineKeyboardButton(f"💳 Неделя — {AD_CAT_7D}₽", url=yoo_7d)],
        [InlineKeyboardButton("✅ Я оплатил — выбрать категорию", callback_data="cat_banner_select_cat")],
    ]
    if my_cat_banners:
        for cat in my_cat_banners:
            kb.append([InlineKeyboardButton(f"❌ Снять баннер в {cat}", callback_data=f"remove_cat_banner_{cat}")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="ad_menu")])
    text = (
        "🎯 *Саб-баннер в категории*\n\n"
        f"3 дня — *{AD_CAT_3D}₽* | Неделя — *{AD_CAT_7D}₽*\n\n"
        "Ваш баннер (картинка) показывается сверху при открытии выбранной категории.\n\n"
        "Шаги:\n"
        "1. Оплатите\n"
        "2. Нажмите «Я оплатил»\n"
        "3. Выберите категорию (Brawl Stars, PUBG и т.д.)\n"
        "4. Отправьте фото баннера\n\n"
        "На фото укажите ваш контакт и условия."
    )
    if my_cat_banners:
        text += f"\n\n✅ Активные баннеры: {', '.join(my_cat_banners)}"
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def cat_banner_select_category(update, ctx):
    query = update.callback_query
    await query.answer()
    kb = [[InlineKeyboardButton(f"{CAT_EMOJI.get(c,'📦')} {c}", callback_data=f"cat_banner_pick_{c}")]
          for c in CATEGORIES]
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="ad_cat_banner")])
    await query.edit_message_text(
        "🎯 В какой категории хотите разместить баннер?",
        reply_markup=InlineKeyboardMarkup(kb))

async def ad_broadcast_page(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    s = sellers.get(uid, {})
    my_prods = [p for p in s.get("products", []) if p in products]
    if not my_prods:
        await query.edit_message_text(
            "❌ Сначала добавьте товар.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="ad_menu")]]))
        return
    yoo_link = f"https://yoomoney.ru/transfer/quickpay?receiver={YOOMONEY_WALLET}&sum={VERIFIED_PRICE}&label=broadcast_{uid}&targets=Рассылка+SmartSalesAI"
    kb = [
        [InlineKeyboardButton(f"💳 Оплатить {VERIFIED_PRICE}₽", url=yoo_link)],
        [InlineKeyboardButton("✅ Я оплатил — выбрать товар", callback_data="broadcast_select")],
        [InlineKeyboardButton("◀️ Назад", callback_data="ad_menu")],
    ]
    await query.edit_message_text(
        f"📢 *Рассылка всем пользователям*\n\n"
        f"Стоимость: *{VERIFIED_PRICE}₽* за одну рассылку\n\n"
        f"Ваш товар отправят *{len(all_users)} пользователям* бота.",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def broadcast_select_product(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    s = sellers.get(uid, {})
    my_prods = [p for p in s.get("products", []) if p in products]
    kb = []
    for pid in my_prods:
        p = products[pid]
        kb.append([InlineKeyboardButton(f"{p['title'][:35]}", callback_data=f"req_broadcast_{pid}")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="ad_broadcast")])
    await query.edit_message_text("📢 Выберите товар для рассылки:", reply_markup=InlineKeyboardMarkup(kb))

async def ad_verified_page(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    is_ver = uid in verified_sellers
    yoo_link = f"https://yoomoney.ru/transfer/quickpay?receiver={YOOMONEY_WALLET}&sum={VERIFIED_PRICE}&label=verified_{uid}&targets=Верификация+SmartSalesAI"
    kb = []
    if is_ver:
        kb.append([InlineKeyboardButton("✅ Бейдж активен", callback_data="ad_menu")])
    else:
        kb.append([InlineKeyboardButton(f"💳 Оплатить {VERIFIED_PRICE}₽", url=yoo_link)])
        kb.append([InlineKeyboardButton("✅ Я оплатил", callback_data="req_verified")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="ad_menu")])
    await query.edit_message_text(
        f"✅ *Бейдж «Проверен»*\n\nСтоимость: *{VERIFIED_PRICE}₽/мес*\n\n"
        "• Бейдж ✅ виден в каталоге и у товаров\n"
        f"• Статус: {'✅ Активен' if is_ver else '❌ Не активен'}",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def advertise_page(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    s = sellers.get(uid, {})
    my_prods = [p for p in s.get("products", []) if p in products]
    if not my_prods:
        await query.edit_message_text(
            "📣 Нет товаров для рекламы.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="ad_menu")]]))
        return
    yoo_link = f"https://yoomoney.ru/transfer/quickpay?receiver={YOOMONEY_WALLET}&sum={AD_TOP_PRICE}&label=top_{uid}&targets=Топ+категории+SmartSalesAI"
    kb = []
    for pid in my_prods:
        p = products[pid]
        is_ad = "📣 " if pid in ad_products else ""
        kb.append([InlineKeyboardButton(f"{is_ad}{p['title'][:30]}", callback_data=f"toggle_ad_{pid}")])
    kb.append([InlineKeyboardButton(f"💳 Оплатить {AD_TOP_PRICE}₽/нед", url=yoo_link)])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="ad_menu")])
    await query.edit_message_text(
        f"📣 *Топ в категории* — *{AD_TOP_PRICE}₽/нед*\n\nТовары с 📣 первые в списке:",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

# ================================================================
# ИИ НАСТРОЙКИ
# ================================================================
async def ai_settings(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    s = sellers.get(uid, {})
    if not s.get("ai_paid"):
        yoo_link = f"https://yoomoney.ru/transfer/quickpay?receiver={YOOMONEY_WALLET}&sum={AI_PRICE}&label=ai_{uid}&targets=ИИ-помощник+SmartSalesAI"
        kb = [[InlineKeyboardButton(f"💳 Оплатить {AI_PRICE}₽", url=yoo_link)],
              [InlineKeyboardButton("✅ Я оплатил", callback_data="ai_paid_confirm")],
              [InlineKeyboardButton("◀️ Назад", callback_data="my_shop")]]
        await query.edit_message_text(
            f"🤖 *ИИ-помощник*\n\nСтоимость: *{AI_PRICE}₽/мес*\n💳 ЮMoney: `{YOOMONEY_WALLET}`",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        return
    ai_on = s.get("ai_enabled", False)
    timer_key = s.get("ai_timer", "2m")
    timer_label = AI_TIMERS.get(timer_key, ("2 минуты", 120))[0]
    kb = [
        [InlineKeyboardButton("🔴 Выключить" if ai_on else "🟢 Включить", callback_data="toggle_ai")],
        [InlineKeyboardButton("✏️ Изменить промпт", callback_data="edit_ai_prompt")],
        [InlineKeyboardButton(f"⏱ Таймер: {timer_label}", callback_data="ai_timer_settings")],
        [InlineKeyboardButton("◀️ Назад", callback_data="my_shop")],
    ]
    await query.edit_message_text(
        f"🤖 *ИИ-помощник*\n\nСтатус: {'✅ Работает' if ai_on else '❌ Выключен'}\n"
        f"⏱ Отвечает через: *{timer_label}*\n\n📝 Промпт:\n_{s.get('ai_prompt','')[:200]}_",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def buy_ai_page(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    seller = sellers.get(uid, {})
    if seller.get("ai_paid"):
        ai_on = seller.get("ai_enabled", False)
        kb = [[InlineKeyboardButton("🔴 Выключить" if ai_on else "🟢 Включить", callback_data="toggle_ai_main")],
              [InlineKeyboardButton("◀️ Назад", callback_data="back_main")]]
        await query.edit_message_text(
            f"🤖 *ИИ-помощник активен!*\nСтатус: {'✅ Работает' if ai_on else '❌ Выключен'}",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        return
    yoo_link = f"https://yoomoney.ru/transfer/quickpay?receiver={YOOMONEY_WALLET}&sum={AI_PRICE}&label=ai_{uid}&targets=ИИ-помощник+SmartSalesAI"
    kb = [[InlineKeyboardButton(f"💳 Оплатить {AI_PRICE}₽", url=yoo_link)],
          [InlineKeyboardButton("✅ Я оплатил", callback_data="ai_paid_confirm")],
          [InlineKeyboardButton("◀️ Назад", callback_data="back_main")]]
    await query.edit_message_text(
        f"🤖 *ИИ-помощник SmartSalesAI*\n\n"
        "• Отвечает покупателям 24/7\n• Знает все ваши товары\n"
        "• Убеждает купить\n• Работает пока вы спите\n\n"
        f"💰 *{AI_PRICE}₽/мес* · 💳 ЮMoney: `{YOOMONEY_WALLET}`",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

# ================================================================
# ПРОМОКОДЫ / СТАТИСТИКА
# ================================================================
async def my_stats(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    s = sellers.get(uid, {})
    my_prods = [p for p in s.get("products", []) if p in products]
    text = "📊 *Статистика магазина*\n\n"
    for pid in my_prods[:10]:
        p = products[pid]
        v = views_count.get(pid, 0)
        r = len(reviews.get(pid, []))
        text += f"• _{p['title'][:25]}_\n  👁 {v} просм. · 📝 {r} отз.\n"
    kb = [[InlineKeyboardButton("◀️ Назад", callback_data="my_shop")]]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def my_promos(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    my_codes = {k: v for k, v in promo_codes.items() if v["seller_id"] == uid}
    kb = [[InlineKeyboardButton("➕ Создать промокод", callback_data="create_promo")],
          [InlineKeyboardButton("◀️ Назад", callback_data="my_shop")]]
    text = "🎟 *Мои промокоды*\n\n"
    if not my_codes:
        text += "Нет промокодов."
    else:
        for code, v in my_codes.items():
            text += f"• `{code}` — {v['discount_pct']}%, осталось {v['uses_left']}\n"
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

# ================================================================
# ОБРАБОТКА СООБЩЕНИЙ
# ================================================================
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text or ""
    state = user_states.get(uid, "")
    all_users.add(uid)
    if text == "📖 Как работает бот":
        await help_command(update, ctx)
        return
    if text == "🛒 Каталог":
        await show_catalog_cmd(update, ctx)
        return
    # Пропустить фото для баннеров (пишем текст вместо фото)
    if text.lower() in ["пропустить", "skip"]:
        if state == "uploading_main_banner":
            user_states[uid] = None
            await update.message.reply_text(
                "❌ Баннер без фото не может быть активирован. Отправьте изображение.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="ad_main_banner")]]))
            return
        if state and state.startswith("uploading_cat_banner_"):
            user_states[uid] = None
            await update.message.reply_text(
                "❌ Баннер без фото не может быть активирован. Отправьте изображение.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="ad_cat_banner")]]))
            return

    if state == "searching":
        user_states[uid] = None
        await do_search(uid, text, update, ctx)
        return
    if state and state.startswith("chatting_"):
        parts = state.split("_")
        seller_id = int(parts[1])
        pid = int(parts[2])
        p = products.get(pid, {})
        buyer_name = update.effective_user.first_name or str(uid)
        try:
            kb = [[InlineKeyboardButton(f"↩️ Ответить {buyer_name}", callback_data=f"reply_to_{uid}")]]
            await ctx.bot.send_message(seller_id,
                f"💬 *{buyer_name}:*\n{text}\n_Товар: {p.get('title','')}_",
                parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        except Exception:
            pass
        await update.message.reply_text("✅ Отправлено!")
        return
    if state and state.startswith("replying_to_"):
        buyer_id = int(state.split("_")[-1])
        seller_name = update.effective_user.first_name or "Продавец"
        task = pending_ai_tasks.get(buyer_id)
        if task:
            task.cancel()
            pending_ai_tasks.pop(buyer_id, None)
        chat = active_chats.get(buyer_id, {})
        if chat:
            chat["ai_replied"] = True
        try:
            await ctx.bot.send_message(buyer_id, f"👤 *{seller_name}:*\n{text}", parse_mode="Markdown")
        except Exception:
            pass
        user_states[uid] = None
        await update.message.reply_text("✅ Ответ отправлен!")
        return
    if state and state.startswith("entering_promo_"):
        pid = int(state.split("_")[-1])
        code = text.strip().upper()
        promo = promo_codes.get(code)
        p = products.get(pid, {})
        if not promo or promo["uses_left"] <= 0:
            await update.message.reply_text(f"❌ Промокод *{code}* не найден.", parse_mode="Markdown")
        else:
            disc = promo["discount_pct"]
            old_price = p.get("price", 0)
            new_price = int(old_price * (1 - disc/100))
            promo_codes[code]["uses_left"] -= 1
            await update.message.reply_text(
                f"✅ *Промокод активирован!*\nСкидка: {disc}%\n~~{old_price}₽~~ → *{new_price}₽*",
                parse_mode="Markdown")
        user_states[uid] = None
        return
    if state and state.startswith("review_"):
        parts = state.split("_")
        pid = int(parts[1])
        rating = int(parts[2])
        buyer_name = update.effective_user.first_name or str(uid)
        if pid not in reviews:
            reviews[pid] = []
        reviews[pid].append({"buyer_id": uid, "buyer_name": buyer_name, "rating": rating, "text": text})
        top_sellers[products[pid]["seller_id"]] = top_sellers.get(products[pid]["seller_id"], 0) + 1
        user_states[uid] = None
        await update.message.reply_text(f"✅ Отзыв опубликован! {'⭐'*rating}")
        return
    if state == "add_title":
        user_temp[uid] = {"title": text, "photos": []}
        user_states[uid] = "add_desc"
        await update.message.reply_text("📝 Введите описание:")
        return
    if state == "add_desc":
        user_temp[uid]["description"] = text
        user_states[uid] = "add_price"
        await update.message.reply_text("💰 Введите цену в рублях:")
        return
    if state == "add_price":
        if not text.isdigit():
            await update.message.reply_text("❌ Только цифры!")
            return
        user_temp[uid]["price"] = int(text)
        user_states[uid] = "add_photos"
        await update.message.reply_text(
            "📷 Отправьте фото (до 10). Готово:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Выбрать категорию", callback_data="photos_done")]]))
        return
    if state == "set_ai_prompt":
        if uid in sellers:
            sellers[uid]["ai_prompt"] = text
        save_banners()
        user_states[uid] = None
        await update.message.reply_text("✅ Промпт ИИ обновлён!")
        return
    if state == "create_promo_code":
        code = text.strip().upper()
        if not re.match(r'^[A-Z0-9]{3,15}$', code):
            await update.message.reply_text("❌ Код: 3-15 символов, буквы и цифры.")
            return
        user_temp[uid]["promo_code"] = code
        user_states[uid] = "create_promo_disc"
        await update.message.reply_text("💰 Введите процент скидки (1-50):")
        return
    if state == "create_promo_disc":
        if not text.isdigit() or not 1 <= int(text) <= 50:
            await update.message.reply_text("❌ Введите число от 1 до 50.")
            return
        code = user_temp[uid].get("promo_code", "")
        disc = int(text)
        promo_codes[code] = {"seller_id": uid, "discount_pct": disc, "uses_left": 100}
        user_states[uid] = None
        await update.message.reply_text(f"✅ Промокод `{code}` создан! Скидка: {disc}%", parse_mode="Markdown")
        return
    # Подпись для основного баннера
    if state == "uploading_main_banner_caption":
        caption = "" if text.strip() == "-" else text.strip()
        file_id = user_temp.get(uid, {}).get("banner_photo")
        if file_id:
            state_store["catalog_banner"] = {"photo_id": file_id, "caption": caption, "seller_id": uid}
        save_banners()
        user_states[uid] = None
        await update.message.reply_text(
            "✅ *Основной баннер активирован!*\n\n"
            "Ваше изображение показывается всем при открытии каталога.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Реклама", callback_data="ad_menu")]]))
        return

    # Подпись для саб-баннера категории
    if state == "uploading_cat_banner_caption":
        caption = "" if text.strip() == "-" else text.strip()
        file_id = user_temp.get(uid, {}).get("cat_banner_photo")
        category = user_temp.get(uid, {}).get("cat_banner_category", "")
        if file_id and category:
            state_store["cat_banners"][category] = {"photo_id": file_id, "caption": caption, "seller_id": uid}
        save_banners()
        user_states[uid] = None
        await update.message.reply_text(
            f"✅ *Саб-баннер в {category} активирован!*\n\n"
            "Ваше изображение показывается сверху в этой категории.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Реклама", callback_data="ad_menu")]]))
        return

    await update.message.reply_text("Используйте /start")

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = user_states.get(uid, "")

    # Фото товара при добавлении
    if state == "add_photos":
        if uid not in user_temp:
            user_temp[uid] = {"photos": []}
        photos = user_temp[uid].setdefault("photos", [])
        if len(photos) >= 10:
            await update.message.reply_text("❌ Максимум 10 фото!")
            return
        photos.append(update.message.photo[-1].file_id)
        await update.message.reply_text(
            f"✅ Фото {len(photos)}/10 добавлено!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Выбрать категорию", callback_data="photos_done")]]))
        return

    # Фото для ОСНОВНОГО баннера каталога
    if state == "uploading_main_banner":
        file_id = update.message.photo[-1].file_id
        # Сохраняем фото и просим подпись
        if uid not in user_temp:
            user_temp[uid] = {}
        user_temp[uid]["banner_photo"] = file_id
        user_states[uid] = "uploading_main_banner_caption"
        await update.message.reply_text(
            "✅ Фото получено!\n\n"
            "Теперь напишите подпись под баннером\n"
            "(например: *Продаю аккаунты BS, пишите @username*) \n\n"
            "Или напишите «-» чтобы без подписи.",
            parse_mode="Markdown")
        return

    # Подпись для основного баннера (обрабатывается в handle_message, но фото нет — пустой return)

    # Фото для САБ-баннера категории
    if state and state.startswith("uploading_cat_banner_"):
        category = state[len("uploading_cat_banner_"):]
        file_id = update.message.photo[-1].file_id
        if uid not in user_temp:
            user_temp[uid] = {}
        user_temp[uid]["cat_banner_photo"] = file_id
        user_temp[uid]["cat_banner_category"] = category
        user_states[uid] = "uploading_cat_banner_caption"
        await update.message.reply_text(
            f"✅ Фото для *{category}* получено!\n\n"
            "Теперь напишите подпись под баннером\n"
            "(например: *Лучшие аккаунты BS, пишите @username*) \n\n"
            "Или напишите «-» чтобы без подписи.",
            parse_mode="Markdown")
        return

# ================================================================
# CALLBACK HANDLER
# ================================================================
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = update.effective_user.id
    all_users.add(uid)

    if data == "back_main":
        await query.answer()
        is_seller2 = uid in sellers
        kb2 = [
            [InlineKeyboardButton("🛒 Каталог товаров", callback_data="catalog"),
             InlineKeyboardButton("🔍 Поиск", callback_data="search")],
            [InlineKeyboardButton("🤖 Купить ИИ-помощника", callback_data="buy_ai")],
            [InlineKeyboardButton("❤️ Избранное", callback_data="favorites"),
             InlineKeyboardButton("🗂 Мои покупки", callback_data="my_purchases")],
            [InlineKeyboardButton("🏆 Топ продавцов", callback_data="top_sellers")],
        ]
        if is_seller2:
            kb2.insert(2, [InlineKeyboardButton("🏪 Мой магазин", callback_data="my_shop")])
        else:
            kb2.append([InlineKeyboardButton("📦 Стать продавцом", callback_data="become_seller")])
        online2, viewers2 = get_fake_online()
        text2 = (
            f"🎮 *SmartSalesAI* — цифровой магазин\n\n"
            f"🟢 Сейчас онлайн: *{online2} человек*\n"
            f"👁 Просматривают товары: *{viewers2}*\n\n"
            "⚡ Отвечаю клиентам за 3 секунды (24/7)\n"
            "💰 Продаю и консультирую как живой эксперт\n"
            "📦 Моментально выдаю товар после оплаты\n\n"
            "Твой бизнес больше не спит. Давай начнём!"
        )
        await safe_edit_text(query, uid, text2, InlineKeyboardMarkup(kb2))
    elif data == "catalog":
        await show_catalog(update, ctx)
    elif data == "search":
        await search_start(update, ctx)
    elif data == "favorites":
        await show_favorites(update, ctx)
    elif data == "top_sellers":
        await show_top_sellers(update, ctx)
    elif data == "buy_ai":
        await buy_ai_page(update, ctx)
    elif data.startswith("cp_"):
        parts = data.split("_")
        cat_idx, page_num = int(parts[1]), int(parts[2])
        await show_category(update, ctx, CATEGORIES[cat_idx], page_num)
    elif data.startswith("cat_") and not data.startswith("catpage_") and not data.startswith("cat_banner_"):
        await show_category(update, ctx, data[4:])
    elif data.startswith("product_"):
        parts = data.split("_")
        pid, idx = int(parts[1]), int(parts[2]) if len(parts) > 2 else 0
        await show_product(update, ctx, pid, idx)
    elif data.startswith("fav_"):
        pid = int(data[4:])
        if uid not in favorites:
            favorites[uid] = set()
        if pid in favorites[uid]:
            favorites[uid].remove(pid)
            await query.answer("💔 Убрано из избранного")
        else:
            favorites[uid].add(pid)
            await query.answer("❤️ Добавлено!")
        await show_product(update, ctx, pid)
    elif data.startswith("reviews_"):
        await show_reviews(update, ctx, int(data[8:]))
    elif data.startswith("leave_review_"):
        await query.answer()
        pid = int(data[13:])
        kb = [[
            InlineKeyboardButton("⭐", callback_data=f"rate_{pid}_1"),
            InlineKeyboardButton("⭐⭐", callback_data=f"rate_{pid}_2"),
            InlineKeyboardButton("⭐⭐⭐", callback_data=f"rate_{pid}_3"),
            InlineKeyboardButton("⭐⭐⭐⭐", callback_data=f"rate_{pid}_4"),
            InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data=f"rate_{pid}_5"),
        ], [InlineKeyboardButton("◀️ Назад", callback_data=f"reviews_{pid}")]]
        await query.edit_message_text("⭐ Выберите оценку:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("rate_"):
        await query.answer()
        parts = data.split("_")
        pid, rating = int(parts[1]), int(parts[2])
        user_states[uid] = f"review_{pid}_{rating}"
        await query.edit_message_text(
            f"✍️ Напишите текст отзыва {'⭐'*rating}:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data=f"reviews_{pid}")]]))
    elif data.startswith("promo_"):
        await promo_start(update, ctx, int(data[6:]))
    elif data.startswith("guarantee_"):
        parts = data.split("_")
        if len(parts) == 2:
            await guarantee_start(update, ctx, int(parts[1]))
        elif parts[1] == "ok":
            pid = int(parts[2])
            await query.answer("✅ Сделка подтверждена!")
            await query.edit_message_text(
                "✅ *Сделка подтверждена!* Оставьте отзыв:", parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📝 Отзыв", callback_data=f"leave_review_{pid}")],
                    [InlineKeyboardButton("◀️ Меню", callback_data="back_main")]]))
        elif parts[1] == "dispute":
            pid = int(parts[2])
            await query.answer()
            await query.edit_message_text(
                f"⚠️ *Спор открыт*\n\nСвяжитесь с @{ADMIN_USERNAME}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="back_main")]]))
    elif data.startswith("chat_seller_"):
        await start_chat(update, ctx, int(data[12:]))
    elif data == "become_seller":
        await query.answer()
        if uid not in sellers:
            sellers[uid] = {
                "name": update.effective_user.first_name or "Продавец",
                "username": update.effective_user.username or "",
                "ai_enabled": False, "ai_paid": False,
                "ai_prompt": "Ты продавец цифровых товаров. Будь дружелюбным и убедительным.",
                "products": []
            }
        await my_shop(update, ctx)
    elif data == "my_shop":
        await my_shop(update, ctx)
    elif data == "my_stats":
        await my_stats(update, ctx)
    elif data == "my_promos":
        await my_promos(update, ctx)
    elif data == "create_promo":
        await query.answer()
        user_states[uid] = "create_promo_code"
        user_temp[uid] = {}
        await query.edit_message_text("🎟 *Создание промокода*\n\nВведите код (3-15 символов):", parse_mode="Markdown")

    # --- РЕКЛАМНОЕ МЕНЮ ---
    elif data == "ad_menu":
        await ad_menu(update, ctx)

    # Основной баннер
    elif data == "ad_main_banner":
        await ad_main_banner_page(update, ctx)
    elif data == "upload_main_banner":
        await query.answer()
        user_states[uid] = "uploading_main_banner"
        await query.edit_message_text(
            "🖼 *Загрузка основного баннера*\n\n"
            "Отправьте изображение для баннера.\n"
            "На фото укажите ваш контакт (@username), цену и условия.\n\n"
            "После отправки фото — баннер сразу активируется!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="ad_main_banner")]]))
    elif data == "remove_main_banner":
        await query.answer()
        if state_store["catalog_banner"] and state_store["catalog_banner"].get("seller_id") == uid:
            state_store["catalog_banner"] = None
            save_banners()
        await query.answer("✅ Основной баннер снят")
        await ad_main_banner_page(update, ctx)

    # Саб-баннер
    elif data == "ad_cat_banner":
        await ad_cat_banner_page(update, ctx)
    elif data == "cat_banner_select_cat":
        await cat_banner_select_category(update, ctx)
    elif data.startswith("cat_banner_pick_"):
        category = data[16:]
        await query.answer()
        user_states[uid] = f"uploading_cat_banner_{category}"
        await query.edit_message_text(
            f"🎯 *Саб-баннер в {category}*\n\n"
            "Отправьте изображение для баннера.\n"
            "На фото укажите ваш контакт (@username), условия и что предлагаете.\n\n"
            "После отправки фото — баннер сразу активируется в этой категории!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="ad_cat_banner")]]))
    elif data.startswith("remove_cat_banner_"):
        await query.answer()
        category = data[18:]
        if category in state_store["cat_banners"] and state_store["cat_banners"][category].get("seller_id") == uid:
            del state_store["cat_banners"][category]
            save_banners()
        await query.answer(f"✅ Саб-баннер снят")
        await ad_cat_banner_page(update, ctx)

    elif data == "ad_broadcast":
        await ad_broadcast_page(update, ctx)
    elif data == "broadcast_select":
        await broadcast_select_product(update, ctx)
    elif data.startswith("req_broadcast_"):
        await query.answer()
        pid = int(data[14:])
        p = products.get(pid, {})
        try:
            await ctx.bot.send_message(ADMIN_ID,
                f"📢 *Запрос на рассылку!*\n👤 id: {uid}\n🛍 {p.get('title','')} — {p.get('price','')}₽\n\nЗапусти: /broadcast_{pid}_{uid}",
                parse_mode="Markdown")
        except Exception:
            pass
        await query.edit_message_text(
            "✅ *Заявка на рассылку принята!*\n\nРассылка будет запущена в течение 1 часа.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="ad_menu")]]))
    elif data == "ad_verified":
        await ad_verified_page(update, ctx)
    elif data == "req_verified":
        await query.answer()
        uname = update.effective_user.username or str(uid)
        try:
            await ctx.bot.send_message(ADMIN_ID,
                f"✅ *Запрос на верификацию!*\n👤 @{uname} (id: {uid})\n\nАктивируй: /verify_{uid}",
                parse_mode="Markdown")
        except Exception:
            pass
        await query.edit_message_text(
            "✅ Заявка отправлена! Активация в течение 1 часа.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="ad_menu")]]))
    elif data == "advertise":
        await advertise_page(update, ctx)
    elif data.startswith("toggle_ad_"):
        await query.answer()
        pid = int(data[10:])
        if pid in ad_products:
            ad_products.remove(pid)
            await query.answer("📣 Реклама выключена")
        else:
            ad_products.append(pid)
            await query.answer("📣 Товар теперь первый!")
        save_banners()
        await advertise_page(update, ctx)
    elif data == "add_product":
        await query.answer()
        user_states[uid] = "add_title"
        user_temp[uid] = {"photos": []}
        await query.edit_message_text("📝 *Добавление товара*\n\nВведите название:", parse_mode="Markdown")
    elif data.startswith("list_my_products"):
        await query.answer()
        page = int(data.split("_")[-1]) if data != "list_my_products" else 0
        s = sellers.get(uid, {})
        my_pids = [p for p in s.get("products", []) if p in products]
        if not my_pids:
            await query.edit_message_text(
                "📦 Нет товаров.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Добавить", callback_data="add_product")],
                    [InlineKeyboardButton("◀️ Назад", callback_data="my_shop")]]))
            return
        per_page = 15
        total = len(my_pids)
        start_i = page * per_page
        end_i = start_i + per_page
        page_pids = my_pids[start_i:end_i]
        text = f"📦 *Мои товары* ({start_i+1}–{min(end_i,total)} из {total}):\n\n"
        kb = []
        for pid in page_pids:
            p = products[pid]
            v = views_count.get(pid, 0)
            text += f"• {p['title'][:30]} — {p['price']}₽ (👁{v})\n"
            kb.append([InlineKeyboardButton(f"🗑 {p['title'][:28]}", callback_data=f"del_product_{pid}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"list_my_products_{page-1}"))
        if end_i < total:
            nav.append(InlineKeyboardButton("Далее ▶️", callback_data=f"list_my_products_{page+1}"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data="my_shop")])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "ai_settings":
        await ai_settings(update, ctx)
    elif data == "ai_paid_confirm":
        await query.answer()
        uname = update.effective_user.username or update.effective_user.first_name or str(uid)
        try:
            await ctx.bot.send_message(ADMIN_ID,
                f"💰 *Заявка на ИИ!*\n👤 @{uname} (id: {uid})\n\nАктивируй: /activate_{uid}",
                parse_mode="Markdown")
        except Exception:
            pass
        await query.edit_message_text(
            "✅ Заявка отправлена! Активация в течение 1 часа.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back_main")]]))
    elif data == "toggle_ai":
        await query.answer()
        if uid in sellers:
            sellers[uid]["ai_enabled"] = not sellers[uid].get("ai_enabled", False)
        save_banners()
        await ai_settings(update, ctx)
    elif data == "toggle_ai_main":
        await query.answer()
        if uid in sellers:
            sellers[uid]["ai_enabled"] = not sellers[uid].get("ai_enabled", False)
        await buy_ai_page(update, ctx)
    elif data == "ai_timer_settings":
        await query.answer()
        kb = []
        row = []
        for key, (label, secs) in AI_TIMERS.items():
            current = sellers.get(uid, {}).get("ai_timer", "2m")
            check = "✅ " if key == current else ""
            row.append(InlineKeyboardButton(f"{check}{label}", callback_data=f"set_timer_{key}"))
            if len(row) == 2:
                kb.append(row)
                row = []
        if row:
            kb.append(row)
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data="ai_settings")])
        await query.edit_message_text("⏱ *Таймер ИИ-ответа*:", parse_mode="Markdown",
                                       reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("set_timer_"):
        await query.answer()
        timer_key = data[10:]
        if timer_key in AI_TIMERS and uid in sellers:
            sellers[uid]["ai_timer"] = timer_key
            label = AI_TIMERS[timer_key][0]
            save_banners()
            await query.answer(f"✅ Таймер: {label}")
        await ai_settings(update, ctx)
    elif data == "edit_ai_prompt":
        await query.answer()
        user_states[uid] = "set_ai_prompt"
        await query.edit_message_text("✏️ Введите промпт для ИИ:")
    elif data == "photos_done":
        await query.answer()
        kb = [[InlineKeyboardButton(f"{CAT_EMOJI.get(c,'📦')} {c}", callback_data=f"addcat_{c}")] for c in CATEGORIES]
        await query.edit_message_text("📂 Выберите категорию:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("addcat_"):
        cat = data[7:]
        t = user_temp.get(uid, {})
        pid = product_counter[0]
        product_counter[0] += 1
        seller_name = sellers.get(uid, {}).get("name", "Продавец")
        products[pid] = {
            "title": t.get("title", ""), "description": t.get("description", ""),
            "price": t.get("price", 0), "category": cat,
            "seller_id": uid, "seller_name": seller_name, "photos": t.get("photos", [])
        }
        if uid not in sellers:
            sellers[uid] = {"name": seller_name, "username": "", "ai_enabled": False,
                            "ai_paid": False, "ai_prompt": "", "products": []}
        sellers[uid]["products"].append(pid)
        views_count[pid] = 0
        reviews[pid] = []
        user_states[uid] = None
        await query.answer("✅ Товар добавлен!")
        await query.edit_message_text(
            f"✅ *Товар добавлен!*\n\n📦 {t.get('title')}\n💰 {t.get('price')}₽\n📂 {cat}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏪 В магазин", callback_data="my_shop")]]))
    elif data.startswith("del_product_"):
        pid = int(data[12:])
        if pid in products and products[pid]["seller_id"] == uid:
            del products[pid]
            if uid in sellers and pid in sellers[uid]["products"]:
                sellers[uid]["products"].remove(pid)
        await query.answer("🗑 Удалено!")
        await my_shop(update, ctx)
    elif data.startswith("reply_to_"):
        buyer_id = int(data[9:])
        user_states[uid] = f"replying_to_{buyer_id}"
        await query.answer()
        await ctx.bot.send_message(uid, "✏️ Напишите ответ покупателю:")
    elif data == "my_purchases":
        await query.answer()
        await query.edit_message_text(
            "🗂 *Мои покупки*\n\nПока пусто.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back_main")]]))

# ================================================================
# ADMIN КОМАНДЫ
# ================================================================
async def handle_admin_commands(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    text = update.message.text or ""

    # Пропуск фото для баннеров
    uid = update.effective_user.id
    state = user_states.get(uid, "")
    if text.lower() == "пропустить":
        if state == "uploading_main_banner_photo":
            banner_data = user_temp.get(uid, {}).get("pending_banner", {})
            if banner_data:
                state_store["catalog_banner"] = banner_data
                user_states[uid] = None
                p = products.get(banner_data.get("pid"), {})
                await update.message.reply_text(
                    f"✅ *Основной баннер активирован без фото!*\n\n🛍 {p.get('title','')}",
                    parse_mode="Markdown")
            return
        if state and state.startswith("uploading_cat_banner_photo_"):
            category = state[len("uploading_cat_banner_photo_"):]
            banner_data = user_temp.get(uid, {}).get("pending_cat_banner", {})
            if banner_data:
                state_store["cat_banners"][category] = banner_data
                user_states[uid] = None
                p = products.get(banner_data.get("pid"), {})
                await update.message.reply_text(
                    f"✅ *Саб-баннер в {category} активирован без фото!*\n\n🛍 {p.get('title','')}",
                    parse_mode="Markdown")
            return

    if text.startswith("/activate_"):
        target_id = int(text.split("_")[1])
        if target_id not in sellers:
            sellers[target_id] = {"name": "Продавец", "username": "", "ai_enabled": True,
                                   "ai_paid": True, "ai_prompt": "Ты продавец.", "products": []}
        else:
            sellers[target_id]["ai_paid"] = True
            sellers[target_id]["ai_enabled"] = True
        save_banners()
        try:
            await ctx.bot.send_message(target_id, "🎉 *ИИ-помощник активирован!*", parse_mode="Markdown")
        except Exception:
            pass
        await update.message.reply_text(f"✅ ИИ активирован для {target_id}")
    elif text.startswith("/verify_"):
        target_id = int(text.split("_")[1])
        verified_sellers.add(target_id)
        try:
            await ctx.bot.send_message(target_id,
                "✅ *Бейдж «Проверен» активирован!*\n\nТеперь вашим товарам больше доверяют.",
                parse_mode="Markdown")
        except Exception:
            pass
        await update.message.reply_text(f"✅ Верификация активирована для {target_id}")
    elif text.startswith("/unverify_"):
        target_id = int(text.split("_")[1])
        verified_sellers.discard(target_id)
        await update.message.reply_text(f"✅ Верификация снята с {target_id}")
    elif text.startswith("/broadcast_"):
        parts = text.split("_")
        if len(parts) >= 3:
            pid = int(parts[1])
            p = products.get(pid, {})
            if not p:
                await update.message.reply_text("❌ Товар не найден")
                return
            msg_text = (
                f"📢 *Специальное предложение!*\n\n"
                f"🛍 *{p.get('title','')}*\n"
                f"📝 {p.get('description','')[:100]}...\n"
                f"💰 *{p.get('price','')}₽*\n\n"
                f"👤 Продавец: {p.get('seller_name','')}"
            )
            sent = 0
            for user_id in list(all_users):
                try:
                    await ctx.bot.send_message(
                        user_id, msg_text, parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("👀 Посмотреть", callback_data=f"product_{pid}_0")]
                        ]))
                    sent += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    pass
            await update.message.reply_text(f"✅ Рассылка отправлена {sent} пользователям!")
    elif text == "/stats":
        main_banner_active = "Да" if state_store.get("catalog_banner") else "Нет"
        cat_banners_count = len(state_store.get("cat_banners", {}))
        text_out = (
            f"📊 *Статистика бота*\n\n"
            f"👥 Всего пользователей: {len(all_users) + 852}\n"
            f"🛍 Товаров: {len(products)}\n"
            f"🏪 Продавцов: {len(sellers) + 148}\n"
            f"✅ Верифицированных: {len(verified_sellers)}\n"
            f"📣 Рекламных товаров (топ): {len(ad_products)}\n"
            f"🖼 Основной баннер: {main_banner_active}\n"
            f"🎯 Саб-баннеров: {cat_banners_count}"
        )
        await update.message.reply_text(text_out, parse_mode="Markdown")

async def about_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in last_bot_message:
        try:
            await ctx.bot.delete_message(chat_id=uid, message_id=last_bot_message[uid])
        except Exception:
            pass
    text = (
        "ℹ️ *О боте SmartSalesAI*\n\n"
        "🎮 *Что это такое?*\n"
        "SmartSalesAI — цифровой маркетплейс игровых товаров с ИИ-продавцом. "
        "Покупай и продавай аккаунты, валюту и предметы для Brawl Stars, PUBG, Roblox, CS2 и других игр.\n\n"
        "🤖 *Как работает ИИ-продавец?*\n"
        "Если продавец не отвечает — ИИ автоматически консультирует покупателя, "
        "рассказывает о товаре и помогает закрыть сделку. Работает 24/7.\n\n"
        "💰 *Монетизация для продавцов:*\n"
        "• ИИ-помощник — 500₽/мес\n"
        "• Баннер в каталоге — от 500₽\n"
        "• Саб-баннер в категории — от 150₽\n"
        "• Топ в категории — 200₽/нед\n"
        "• Бейдж Проверен — 300₽/мес\n\n"
        "📊 *Статистика:*\n"
        f"👥 Пользователей: {len(all_users) + 852}\n"
        f"🛍 Товаров: {len(products)}\n"
        f"🏪 Продавцов: {len(sellers) + 148}\n\n"
        "📩 *Контакт:* @evnnnu"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Начать", callback_data="back_main")]
    ])
    sent = await update.effective_message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    last_bot_message[uid] = sent.message_id

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("catalog", show_catalog_cmd))
    app.add_handler(MessageHandler(filters.COMMAND & (
        filters.Regex(r'^/activate_') |
        filters.Regex(r'^/verify_') |
        filters.Regex(r'^/unverify') |
        filters.Regex(r'^/broadcast_') |
        filters.Regex(r'^/stats$')
    ), handle_admin_commands))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("SmartSalesAI Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
