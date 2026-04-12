import os
import asyncio
import logging
import re
import random

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "1048682172"))
YOOMONEY_WALLET = "4100118679419062"
AI_PRICE = 500

groq_client = Groq(api_key=GROQ_API_KEY)

# --- ХРАНИЛИЩЕ ---
products = {}
product_counter = [1]
sellers = {}
active_chats = {}
pending_ai_tasks = {}
user_states = {}
user_temp = {}
ai_pending_users = set()

# Новые хранилища
reviews = {}        # pid -> [{buyer_id, buyer_name, rating, text}]
favorites = {}      # uid -> set of pids
views_count = {}    # pid -> int
promo_codes = {}    # code -> {seller_id, discount_pct, uses_left}
top_sellers = {}    # uid -> total_sales count
ad_products = []    # [pid] — рекламируемые товары (первые в списке)
guarantees = {}     # uid -> {pid, seller_id, amount, status}

PAGE_SIZE = 8

CATEGORIES = ["Brawl Stars", "PUBG Mobile", "Roblox", "Standoff 2", "Steam", "CS2"]
CAT_EMOJI = {"Brawl Stars": "🎯", "PUBG Mobile": "🔫", "Roblox": "🧱",
             "Standoff 2": "🔪", "Steam": "🎮", "CS2": "🏆"}

WELCOME_PHOTO = None  # можно задать file_id фото

def init_demo():
    sellers[ADMIN_ID] = {
        "name": "SmartSales", "username": "admin",
        "ai_enabled": True, "ai_paid": True,
        "ai_prompt": "Ты опытный продавец игровых аккаунтов. Расскажи о преимуществах товара, убеди купить, будь дружелюбным.",
        "products": []
    }
    top_sellers[ADMIN_ID] = 47

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
        {"cat": "Steam", "title": "Steam пополнение 500 рублей фаст", "desc": "Пополню кошелёк Steam на 500р. Активирую код в течение 15 минут.", "price": 580},
        {"cat": "Steam", "title": "Аккаунт Steam 47 игр + CS2 Prime", "desc": "47 игр, CS2 с Prime статусом, GTA V, RDR2. 2800 часов в играх.", "price": 4500},
        {"cat": "Steam", "title": "Steam 1000 рублей выгодно", "desc": "Пополнение Steam 1000р. Работаю быстро, более 300 продаж.", "price": 1100},
        {"cat": "Steam", "title": "Аккаунт 12 лет Steam + редкие игры", "desc": "Аккаунт с 2012 года, 89 игр, значки, торговые карточки.", "price": 3800},
        {"cat": "Steam", "title": "Steam пополнение 200 рублей фаст", "desc": "Пополню кошелёк Steam на 200р. Активирую код за 15 минут.", "price": 230},
        {"cat": "Steam", "title": "Steam 300 рублей быстро", "desc": "300р на Steam кошелёк. Работаю честно, более 200 продаж.", "price": 340},
        {"cat": "Steam", "title": "Аккаунт Steam 5 игр инди", "desc": "5 инди игр: Stardew Valley, Terraria, Celeste и др. Старый аккаунт.", "price": 350},
        {"cat": "Steam", "title": "Steam 400 рублей выгодно", "desc": "400р на кошелёк Steam. Ниже рыночной цены. Фаст.", "price": 380},
        {"cat": "Steam", "title": "Аккаунт Steam Dota 2 500 часов", "desc": "Аккаунт с Dota 2, 500+ часов. Несколько косметических предметов.", "price": 300},
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

    # Демо промокод
    promo_codes["SMART10"] = {"seller_id": ADMIN_ID, "discount_pct": 10, "uses_left": 100}
    promo_codes["SALE20"] = {"seller_id": ADMIN_ID, "discount_pct": 20, "uses_left": 50}

init_demo()

# --- HELPERS ---
def get_seller_rating(seller_id):
    total, count = 0, 0
    for pid in sellers.get(seller_id, {}).get("products", []):
        for r in reviews.get(pid, []):
            total += r["rating"]
            count += 1
    return round(total / count, 1) if count else 5.0

def stars(rating):
    full = int(rating)
    return "⭐" * full + ("" if rating == full else "")

# --- ГЛАВНОЕ МЕНЮ ---
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_states[uid] = None
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

    online = random.randint(70, 80)
    viewers = random.randint(12, 28)
    text = (
        f"🎮 *SmartSalesAI* — цифровой магазин\n\n"
        f"🟢 Сейчас онлайн: *{online} человек*\n"
        f"👁 Просматривают товары: *{viewers}*\n\n"
        "⚡ Отвечаю клиентам за 3 секунды (24/7)\n"
        "💰 Продаю и консультирую как живой эксперт\n"
        "📦 Моментально выдаю товар после оплаты\n\n"
        "Твой бизнес больше не спит. Давай начнём!"
    )
    await update.effective_message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# --- ПОИСК ---
async def search_start(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    user_states[uid] = "searching"
    await query.edit_message_text(
        "🔍 *Поиск товаров*\n\nВведите название или ключевое слово:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back_main")]])
    )

async def do_search(uid, query_text, update, ctx):
    q = query_text.lower()
    found = [(pid, p) for pid, p in products.items()
             if q in p["title"].lower() or q in p["description"].lower() or q in p["category"].lower()]
    if not found:
        await update.message.reply_text(
            f"😔 По запросу *{query_text}* ничего не найдено.\n\nПопробуйте другой запрос или /start",
            parse_mode="Markdown"
        )
        return
    kb = []
    for pid, p in found[:15]:
        kb.append([InlineKeyboardButton(f"{p['title']} — {p['price']}₽", callback_data=f"product_{pid}_0")])
    kb.append([InlineKeyboardButton("🔍 Новый поиск", callback_data="search"),
               InlineKeyboardButton("◀️ Меню", callback_data="back_main")])
    await update.message.reply_text(
        f"🔍 По запросу *{query_text}* найдено {len(found)} товаров:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# --- ИЗБРАННОЕ ---
async def show_favorites(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    fav = favorites.get(uid, set())
    if not fav:
        await query.edit_message_text(
            "❤️ *Избранное пусто*\n\nДобавляйте товары нажав ❤️ в карточке товара.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Каталог", callback_data="catalog"),
                                                InlineKeyboardButton("◀️ Назад", callback_data="back_main")]])
        )
        return
    kb = []
    for pid in fav:
        p = products.get(pid)
        if p:
            kb.append([InlineKeyboardButton(f"{p['title']} — {p['price']}₽", callback_data=f"product_{pid}_0")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="back_main")])
    await query.edit_message_text(
        f"❤️ *Избранное* — {len(fav)} товаров:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# --- ТОП ПРОДАВЦОВ ---
async def show_top_sellers(update, ctx):
    query = update.callback_query
    await query.answer()
    sorted_sellers = sorted(
        [(uid, s) for uid, s in sellers.items()],
        key=lambda x: top_sellers.get(x[0], 0), reverse=True
    )[:10]
    total_online = random.randint(70, 80)
    text = f"🏆 *Топ продавцов SmartSalesAI*\n🟢 Сейчас онлайн: {total_online} покупателей\n\n"
    medals = ["🥇", "🥈", "🥉"] + ["4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    for i, (uid, s) in enumerate(sorted_sellers):
        rating = get_seller_rating(uid)
        sales = top_sellers.get(uid, 0)
        ai_badge = "🤖" if s.get("ai_enabled") else ""
        text += f"{medals[i]} *{s['name']}* {ai_badge}\n"
        text += f"   ⭐ {rating} · 📦 {sales} продаж\n\n"
    await query.edit_message_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back_main")]])
    )

# --- КАТАЛОГ ---
async def show_catalog(update, ctx):
    query = update.callback_query
    await query.answer()
    kb = [[InlineKeyboardButton(f"{CAT_EMOJI.get(c,'📦')} {c}", callback_data=f"cat_{c}")] for c in CATEGORIES]
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="back_main")])
    await query.edit_message_text("📂 *Выберите категорию:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def show_category(update, ctx, category, page=0):
    query = update.callback_query
    await query.answer()
    # Рекламные товары первыми
    ad_items = [(pid, products[pid]) for pid in ad_products if products.get(pid, {}).get("category") == category]
    reg_items = [(pid, p) for pid, p in products.items() if p["category"] == category and pid not in ad_products]
    items = ad_items + reg_items
    if not items:
        await query.edit_message_text(
            "😔 Нет товаров.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="catalog")]])
        )
        return
    total = len(items)
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_items = items[start:end]
    kb = []
    for pid, p in page_items:
        ad_badge = "📣 " if pid in ad_products else ""
        fav_count = sum(1 for f in favorites.values() if pid in f)
        rev_count = len(reviews.get(pid, []))
        label = f"{ad_badge}{p['title']} — {p['price']}₽"
        if rev_count > 0:
            avg = sum(r["rating"] for r in reviews[pid]) / rev_count
            label += f" ⭐{avg:.1f}"
        kb.append([InlineKeyboardButton(label, callback_data=f"product_{pid}_0")])
    cat_idx = CATEGORIES.index(category) if category in CATEGORIES else 0
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"cp_{cat_idx}_{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("Далее ▶️", callback_data=f"cp_{cat_idx}_{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("🔙 К категориям", callback_data="catalog")])
    showing = f"{start+1}–{min(end,total)} из {total}"
    cat_online = random.randint(8, 25)
    await query.edit_message_text(
        f"{CAT_EMOJI.get(category,'📦')} *{category}* — {total} товаров\n_{showing}_ · 🟢 {cat_online} онлайн\n\nВыберите товар:",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )

async def show_product(update, ctx, pid, photo_idx=0):
    query = update.callback_query
    await query.answer()
    p = products.get(pid)
    if not p:
        await query.edit_message_text("Товар не найден.")
        return
    # Считаем просмотры
    views_count[pid] = views_count.get(pid, 0) + 1
    # Уведомляем продавца о просмотре (не спамим — только каждые 5)
    if views_count[pid] % 5 == 0:
        try:
            await ctx.bot.send_message(
                p["seller_id"],
                f"👁 Ваш товар *{p['title']}* просмотрели {views_count[pid]} раз!",
                parse_mode="Markdown"
            )
        except:
            pass
    seller = sellers.get(p["seller_id"], {})
    uid = update.effective_user.id
    is_fav = pid in favorites.get(uid, set())
    fav_btn = "💔 Убрать из избранного" if is_fav else "❤️ В избранное"
    ai_badge = "\n🤖 _ИИ-продавец онлайн 24/7_" if seller.get("ai_enabled") else ""
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
        f"👤 Продавец: {p['seller_name']} ⭐{seller_rating}"
        f"{rev_text}"
        f"{ai_badge}\n"
        f"👁 Просмотров: {views_count.get(pid, 0)}\n"
        f"🔥 Смотрят прямо сейчас: *{random.randint(2, 7)} человека*"
    )
    kb = [
        [InlineKeyboardButton("💬 Написать продавцу", callback_data=f"chat_seller_{pid}")],
        [InlineKeyboardButton("🎟 Ввести промокод", callback_data=f"promo_{pid}"),
         InlineKeyboardButton(fav_btn, callback_data=f"fav_{pid}")],
        [InlineKeyboardButton("📝 Отзывы", callback_data=f"reviews_{pid}"),
         InlineKeyboardButton("🤝 Гарантия сделки", callback_data=f"guarantee_{pid}")],
        [InlineKeyboardButton("◀️ Назад", callback_data=f"cat_{p['category']}")],
    ]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

# --- ОТЗЫВЫ ---
async def show_reviews(update, ctx, pid):
    query = update.callback_query
    await query.answer()
    p = products.get(pid, {})
    rev_list = reviews.get(pid, [])
    if not rev_list:
        text = f"📝 *Отзывы о товаре*\n_{p.get('title','')}_\n\nОтзывов пока нет. Будьте первым!"
    else:
        avg = sum(r["rating"] for r in rev_list) / len(rev_list)
        text = f"📝 *Отзывы* — {p.get('title','')}\n⭐ Средняя оценка: {avg:.1f}/5\n\n"
        for r in rev_list[-5:]:
            text += f"{'⭐'*r['rating']} *{r['buyer_name']}*\n{r['text']}\n\n"
    kb = [
        [InlineKeyboardButton("✍️ Оставить отзыв", callback_data=f"leave_review_{pid}")],
        [InlineKeyboardButton("◀️ Назад", callback_data=f"product_{pid}_0")],
    ]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

# --- ПРОМОКОД ---
async def promo_start(update, ctx, pid):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    user_states[uid] = f"entering_promo_{pid}"
    await query.edit_message_text(
        "🎟 *Введите промокод*\n\nЕсли у вас есть промокод — введите его и получите скидку:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data=f"product_{pid}_0")]])
    )

# --- ГАРАНТИЯ ---
async def guarantee_start(update, ctx, pid):
    query = update.callback_query
    await query.answer()
    p = products.get(pid, {})
    kb = [
        [InlineKeyboardButton("✅ Подтвердить получение", callback_data=f"guarantee_ok_{pid}")],
        [InlineKeyboardButton("❌ Открыть спор", callback_data=f"guarantee_dispute_{pid}")],
        [InlineKeyboardButton("◀️ Назад", callback_data=f"product_{pid}_0")],
    ]
    await query.edit_message_text(
        f"🤝 *Гарантия сделки*\n\n"
        f"Товар: _{p.get('title','')}_\n"
        f"Цена: *{p.get('price',0)}₽*\n\n"
        f"Как работает:\n"
        f"1. Вы оплачиваете товар продавцу\n"
        f"2. Получаете товар\n"
        f"3. Нажимаете «Подтвердить получение»\n\n"
        f"Если что-то пошло не так — нажмите «Открыть спор» и мы разберёмся.",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )

# --- ЧАТ ---
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
        f"💬 *Чат с {p['seller_name']}*\n\n"
        f"Товар: _{p['title']}_\n"
        f"Цена: *{p['price']}₽*\n\n"
        f"✍️ Напишите сообщение.\n"
        f"⏱ Если не ответит 2 мин — ответит ИИ.\n\n/start — выйти",
        parse_mode="Markdown"
    )
    try:
        kb = [[InlineKeyboardButton(f"↩️ Ответить {buyer_name}", callback_data=f"reply_to_{uid}")]]
        await ctx.bot.send_message(
            seller_id,
            f"📩 *Новый покупатель!*\n👤 {buyer_name}\n🛍 *{p['title']}* — {p['price']}₽",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
        )
    except:
        pass
    if uid in pending_ai_tasks:
        pending_ai_tasks[uid].cancel()
    task = asyncio.create_task(ai_reply_after_delay(ctx, uid, pid, buyer_name))
    pending_ai_tasks[uid] = task

async def ai_reply_after_delay(ctx, buyer_id, pid, buyer_name):
    await asyncio.sleep(120)
    chat = active_chats.get(buyer_id)
    if not chat or chat.get("ai_replied"):
        return
    p = products.get(pid, {})
    seller = sellers.get(chat["seller_id"], {})
    if not seller.get("ai_enabled") or not seller.get("ai_paid"):
        return
    prompt = seller.get("ai_prompt", "Ты продавец цифровых товаров.")
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": f"{prompt}\nТовар: {p.get('title','')}. {p.get('description','')}. Цена: {p.get('price','')}₽. Отвечай кратко на русском."},
                {"role": "user", "content": f"Покупатель {buyer_name} интересуется. Поприветствуй и предложи купить."}
            ],
            max_tokens=300
        )
        ai_text = resp.choices[0].message.content
        chat["ai_replied"] = True
        await ctx.bot.send_message(buyer_id, f"🤖 *ИИ-продавец:*\n\n{ai_text}", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"AI error: {e}")

# --- МОЙ МАГАЗИН ---
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
    kb = [
        [InlineKeyboardButton("➕ Добавить товар", callback_data="add_product"),
         InlineKeyboardButton("📦 Мои товары", callback_data="list_my_products")],
        [InlineKeyboardButton(f"🤖 ИИ: {ai_status}", callback_data="ai_settings"),
         InlineKeyboardButton("🎟 Промокоды", callback_data="my_promos")],
        [InlineKeyboardButton("📣 Реклама товара", callback_data="advertise"),
         InlineKeyboardButton("📊 Статистика", callback_data="my_stats")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
    ]
    await query.edit_message_text(
        f"🏪 *Мой магазин*\n\n"
        f"👤 {s.get('name','')}\n"
        f"📦 Товаров: {len(my_prods)}\n"
        f"⭐ Рейтинг: {rating}\n"
        f"📦 Продаж: {sales}\n"
        f"👁 Просмотров: {total_views}\n"
        f"📝 Отзывов: {total_reviews}\n"
        f"🤖 ИИ: {ai_status}",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )

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
    kb = [
        [InlineKeyboardButton("➕ Создать промокод", callback_data="create_promo")],
        [InlineKeyboardButton("◀️ Назад", callback_data="my_shop")],
    ]
    text = "🎟 *Мои промокоды*\n\n"
    if not my_codes:
        text += "Нет промокодов. Создайте первый!"
    else:
        for code, v in my_codes.items():
            text += f"• `{code}` — скидка {v['discount_pct']}%, осталось {v['uses_left']} использований\n"
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def advertise_page(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    s = sellers.get(uid, {})
    my_prods = [p for p in s.get("products", []) if p in products]
    if not my_prods:
        await query.edit_message_text(
            "📣 Нет товаров для рекламы. Сначала добавьте товар.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="my_shop")]])
        )
        return
    kb = []
    for pid in my_prods:
        p = products[pid]
        is_ad = "📣 " if pid in ad_products else ""
        kb.append([InlineKeyboardButton(f"{is_ad}{p['title'][:30]}", callback_data=f"toggle_ad_{pid}")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="my_shop")])
    await query.edit_message_text(
        "📣 *Реклама товаров*\n\nТовары с 📣 показываются первыми в категории.\nНажмите на товар чтобы включить/выключить рекламу:",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )

async def ai_settings(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    s = sellers.get(uid, {})
    if not s.get("ai_paid"):
        yoo_link = f"https://yoomoney.ru/transfer/quickpay?receiver={YOOMONEY_WALLET}&sum={AI_PRICE}&label=ai_{uid}&targets=ИИ-помощник+SmartSalesAI"
        kb = [
            [InlineKeyboardButton(f"💳 Оплатить {AI_PRICE}₽", url=yoo_link)],
            [InlineKeyboardButton("✅ Я оплатил", callback_data="ai_paid_confirm")],
            [InlineKeyboardButton("◀️ Назад", callback_data="my_shop")],
        ]
        await query.edit_message_text(
            f"🤖 *ИИ-помощник*\n\nСтоимость: *{AI_PRICE}₽/мес*\n💳 ЮMoney: `{YOOMONEY_WALLET}`",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
        )
        return
    ai_on = s.get("ai_enabled", False)
    kb = [
        [InlineKeyboardButton("🔴 Выключить" if ai_on else "🟢 Включить", callback_data="toggle_ai")],
        [InlineKeyboardButton("✏️ Изменить промпт", callback_data="edit_ai_prompt")],
        [InlineKeyboardButton("◀️ Назад", callback_data="my_shop")],
    ]
    await query.edit_message_text(
        f"🤖 *ИИ-помощник*\n\nСтатус: {'✅ Работает' if ai_on else '❌ Выключен'}\n\n"
        f"📝 Промпт:\n_{s.get('ai_prompt','')[:200]}_",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )

async def buy_ai_page(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    seller = sellers.get(uid, {})
    if seller.get("ai_paid"):
        ai_on = seller.get("ai_enabled", False)
        kb = [
            [InlineKeyboardButton("🔴 Выключить" if ai_on else "🟢 Включить", callback_data="toggle_ai_main")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
        ]
        await query.edit_message_text(
            f"🤖 *ИИ-помощник активен!*\nСтатус: {'✅ Работает' if ai_on else '❌ Выключен'}",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
        )
        return
    yoo_link = f"https://yoomoney.ru/transfer/quickpay?receiver={YOOMONEY_WALLET}&sum={AI_PRICE}&label=ai_{uid}&targets=ИИ-помощник+SmartSalesAI"
    kb = [
        [InlineKeyboardButton(f"💳 Оплатить {AI_PRICE}₽", url=yoo_link)],
        [InlineKeyboardButton("✅ Я оплатил", callback_data="ai_paid_confirm")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
    ]
    await query.edit_message_text(
        f"🤖 *ИИ-помощник SmartSalesAI*\n\n"
        f"• Отвечает покупателям 24/7\n• Знает все ваши товары\n"
        f"• Убеждает купить\n• Работает пока вы спите\n\n"
        f"💰 *{AI_PRICE}₽/мес* · 💳 ЮMoney: `{YOOMONEY_WALLET}`",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )

# --- СООБЩЕНИЯ ---
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text or ""
    state = user_states.get(uid, "")

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
            await ctx.bot.send_message(
                seller_id,
                f"💬 *{buyer_name}:*\n{text}\n_Товар: {p.get('title','')}_",
                parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
            )
        except:
            pass
        await update.message.reply_text("✅ Отправлено! Ожидайте ответа...")
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
        except:
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
            await update.message.reply_text(
                f"❌ Промокод *{code}* не найден или уже не действует.",
                parse_mode="Markdown"
            )
        else:
            disc = promo["discount_pct"]
            old_price = p.get("price", 0)
            new_price = int(old_price * (1 - disc/100))
            promo_codes[code]["uses_left"] -= 1
            await update.message.reply_text(
                f"✅ *Промокод активирован!*\n\n"
                f"Скидка: {disc}%\n"
                f"Цена: ~~{old_price}₽~~ → *{new_price}₽*\n\n"
                f"Напишите продавцу и сообщите что использовали промокод `{code}`.",
                parse_mode="Markdown"
            )
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
        await update.message.reply_text(
            f"✅ Отзыв опубликован! {'⭐'*rating}\n\nСпасибо за обратную связь!",
        )
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
            "📷 Отправьте фото (до 10). Когда готово:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Выбрать категорию", callback_data="photos_done")]])
        )
        return
    if state == "set_ai_prompt":
        if uid in sellers:
            sellers[uid]["ai_prompt"] = text
        user_states[uid] = None
        await update.message.reply_text("✅ Промпт ИИ обновлён!")
        return
    if state == "create_promo_code":
        code = text.strip().upper()
        if not re.match(r'^[A-Z0-9]{3,15}$', code):
            await update.message.reply_text("❌ Код должен быть от 3 до 15 символов, только буквы и цифры.")
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
        await update.message.reply_text(
            f"✅ Промокод `{code}` создан!\nСкидка: {disc}%\nИспользований: 100",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text("Используйте /start")

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if user_states.get(uid) == "add_photos":
        if uid not in user_temp:
            user_temp[uid] = {"photos": []}
        photos = user_temp[uid].setdefault("photos", [])
        if len(photos) >= 10:
            await update.message.reply_text("❌ Максимум 10 фото!")
            return
        photos.append(update.message.photo[-1].file_id)
        await update.message.reply_text(
            f"✅ Фото {len(photos)}/10 добавлено!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Выбрать категорию", callback_data="photos_done")]])
        )

# --- CALLBACKS ---
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = update.effective_user.id

    if data == "back_main":
        await query.answer()
        await start(update, ctx)
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
    elif data.startswith("cat_") and not data.startswith("catpage_"):
        await show_category(update, ctx, data[4:])
    elif data.startswith("product_"):
        parts = data.split("_")
        pid, idx = int(parts[1]), int(parts[2]) if len(parts) > 2 else 0
        await show_product(update, ctx, pid, idx)
    elif data.startswith("fav_"):
        await query.answer()
        pid = int(data[4:])
        if uid not in favorites:
            favorites[uid] = set()
        if pid in favorites[uid]:
            favorites[uid].remove(pid)
            await query.answer("💔 Убрано из избранного")
        else:
            favorites[uid].add(pid)
            await query.answer("❤️ Добавлено в избранное!")
        await show_product(update, ctx, pid)
    elif data.startswith("reviews_"):
        pid = int(data[8:])
        await show_reviews(update, ctx, pid)
    elif data.startswith("leave_review_"):
        await query.answer()
        pid = int(data[13:])
        user_states[uid] = f"review_rate_{pid}"
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
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data=f"reviews_{pid}")]])
        )
    elif data.startswith("promo_"):
        pid = int(data[6:])
        await promo_start(update, ctx, pid)
    elif data.startswith("guarantee_"):
        parts = data.split("_")
        if len(parts) == 2:
            await guarantee_start(update, ctx, int(parts[1]))
        elif parts[1] == "ok":
            pid = int(parts[2])
            p = products.get(pid, {})
            await query.answer("✅ Сделка подтверждена!")
            await query.edit_message_text(
                "✅ *Сделка подтверждена!*\n\nСпасибо за покупку. Оставьте отзыв:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📝 Оставить отзыв", callback_data=f"leave_review_{pid}")],
                    [InlineKeyboardButton("◀️ Меню", callback_data="back_main")]
                ])
            )
        elif parts[1] == "dispute":
            pid = int(parts[2])
            await query.answer()
            await query.edit_message_text(
                "⚠️ *Спор открыт*\n\nОпишите проблему и свяжитесь с администратором:\n@SmartSalesAI_kz_bot\n\nМы разберёмся в течение 24 часов.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Меню", callback_data="back_main")]])
            )
    elif data.startswith("chat_seller_"):
        await start_chat(update, ctx, int(data[12:]))
    elif data == "become_seller":
        await query.answer()
        uid2 = update.effective_user.id
        if uid2 not in sellers:
            sellers[uid2] = {
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
        await query.edit_message_text(
            "🎟 *Создание промокода*\n\nВведите код (только буквы и цифры, 3-15 символов):\nПример: SALE10",
            parse_mode="Markdown"
        )
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
            await query.answer("📣 Товар теперь первый в списке!")
        await advertise_page(update, ctx)
    elif data == "add_product":
        await query.answer()
        user_states[uid] = "add_title"
        user_temp[uid] = {"photos": []}
        await query.edit_message_text("📝 *Добавление товара*\n\nВведите название:", parse_mode="Markdown")
    elif data == "list_my_products":
        await query.answer()
        s = sellers.get(uid, {})
        my_pids = [p for p in s.get("products", []) if p in products]
        if not my_pids:
            await query.edit_message_text(
                "📦 Нет товаров.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Добавить", callback_data="add_product")],
                    [InlineKeyboardButton("◀️ Назад", callback_data="my_shop")]
                ])
            )
            return
        text = "📦 *Мои товары:*\n\n"
        kb = []
        for pid in my_pids:
            p = products[pid]
            v = views_count.get(pid, 0)
            text += f"• {p['title']} — {p['price']}₽ (👁{v})\n"
            kb.append([InlineKeyboardButton(f"🗑 {p['title'][:28]}", callback_data=f"del_product_{pid}")])
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data="my_shop")])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "ai_settings":
        await ai_settings(update, ctx)
    elif data == "ai_paid_confirm":
        await query.answer()
        uname = update.effective_user.username or update.effective_user.first_name or str(uid)
        try:
            await ctx.bot.send_message(
                ADMIN_ID,
                f"💰 *Заявка на ИИ!*\n👤 @{uname} (id: {uid})\n\nАктивируй: /activate_{uid}",
                parse_mode="Markdown"
            )
        except:
            pass
        await query.edit_message_text(
            "✅ Заявка отправлена!\nАктивация в течение 1 часа.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back_main")]])
        )
    elif data == "toggle_ai":
        await query.answer()
        if uid in sellers:
            sellers[uid]["ai_enabled"] = not sellers[uid].get("ai_enabled", False)
        await ai_settings(update, ctx)
    elif data == "toggle_ai_main":
        await query.answer()
        if uid in sellers:
            sellers[uid]["ai_enabled"] = not sellers[uid].get("ai_enabled", False)
        await buy_ai_page(update, ctx)
    elif data == "edit_ai_prompt":
        await query.answer()
        user_states[uid] = "set_ai_prompt"
        await query.edit_message_text("✏️ Введите промпт для ИИ:", parse_mode="Markdown")
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
            sellers[uid] = {"name": seller_name, "username": "", "ai_enabled": False, "ai_paid": False, "ai_prompt": "", "products": []}
        sellers[uid]["products"].append(pid)
        views_count[pid] = 0
        reviews[pid] = []
        user_states[uid] = None
        await query.answer("✅ Товар добавлен!")
        await query.edit_message_text(
            f"✅ *Товар добавлен!*\n\n📦 {t.get('title')}\n💰 {t.get('price')}₽\n📂 {cat}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏪 В магазин", callback_data="my_shop")]])
        )
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
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back_main")]])
        )

async def handle_activate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    text = update.message.text
    if text.startswith("/activate_"):
        target_id = int(text.split("_")[1])
        if target_id not in sellers:
            sellers[target_id] = {"name": "Продавец", "username": "", "ai_enabled": True, "ai_paid": True, "ai_prompt": "Ты продавец цифровых товаров.", "products": []}
        else:
            sellers[target_id]["ai_paid"] = True
            sellers[target_id]["ai_enabled"] = True
        try:
            await ctx.bot.send_message(target_id, "🎉 *ИИ-помощник активирован!*", parse_mode="Markdown")
        except:
            pass
        await update.message.reply_text(f"✅ ИИ активирован для {target_id}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r'^/activate_'), handle_activate))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("SmartSalesAI Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
