import os
import asyncio
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

products = {}
product_counter = [1]
sellers = {}
active_chats = {}
pending_ai_tasks = {}
user_states = {}
user_temp = {}
ai_pending_users = set()  # юзеры которые оплатили но ещё не подтверждены

CATEGORIES = ["Brawl Stars", "PUBG Mobile", "Roblox", "Standoff 2", "Steam", "CS2"]
CAT_EMOJI = {"Brawl Stars": "🎯", "PUBG Mobile": "🔫", "Roblox": "🧱",
             "Standoff 2": "🔪", "Steam": "🎮", "CS2": "🏆"}

def init_demo():
    sellers[ADMIN_ID] = {
        "name": "SmartSales", "username": "admin",
        "ai_enabled": True, "ai_paid": True,
        "ai_prompt": "Ты опытный продавец игровых аккаунтов. Расскажи о преимуществах товара, убеди купить, будь дружелюбным.",
        "products": []
    }

    demo_products = [
        # BRAWL STARS
        {"cat": "Brawl Stars", "title": "Аккаунт 45 бравлеров, Мортис макс", "desc": "45 бравлеров, Мортис 11, Эмбер 9, Байрон 10. Трофеи 32,000. Без привязки к номеру.", "price": 1800},
        {"cat": "Brawl Stars", "title": "Аккаунт 3 легендарки + Brawl Pass", "desc": "Леон, Сэнди, Корделиус. 28,500 трофеев. Активный Brawl Pass. Почта в комплекте.", "price": 2400},
        {"cat": "Brawl Stars", "title": "1000 гемов Brawl Stars фаст", "desc": "Пополнение через официальный аккаунт. Отправлю в течение 10 минут после оплаты.", "price": 600},
        {"cat": "Brawl Stars", "title": "Аккаунт 170 трофейных бравлеров 54к", "desc": "170 бравлеров включая всех легендарок. 54,200 трофеев. Аккаунт прокачан полностью.", "price": 8500},
        {"cat": "Brawl Stars", "title": "Brawl Pass + 80 гемов", "desc": "Сезонный Brawl Pass + 80 гемов в подарок. Введу код сразу после оплаты.", "price": 450},
        {"cat": "Brawl Stars", "title": "Аккаунт новый старт 12 бравлеров", "desc": "Чистый аккаунт 12 бравлеров, Шелли макс, Нита 9, Кольт 8. 4,500 трофеев. Дёшево!", "price": 300},

        # PUBG MOBILE
        {"cat": "PUBG Mobile", "title": "Аккаунт 68 уровень Conqueror сезон", "desc": "68 лвл, был Conqueror в прошлом сезоне. 2800+ матчей. 3 ультра скина. Безопасная передача.", "price": 3200},
        {"cat": "PUBG Mobile", "title": "600 UC PUBG фаст 10 минут", "desc": "Пополняю UC на ваш аккаунт. Нужен только ID игрока. Фаст — отправлю за 10 минут.", "price": 750},
        {"cat": "PUBG Mobile", "title": "1800 UC PUBG Mobile выгодно", "desc": "1800 UC — выгоднее чем покупать в магазине. Работаю быстро, более 200 продаж.", "price": 1900},
        {"cat": "PUBG Mobile", "title": "Аккаунт M17 ранг + Glacier M416", "desc": "Уровень M17, ранг Алмаз, легендарный скин M416 Glacier. 45 скинов персонажей.", "price": 5500},
        {"cat": "PUBG Mobile", "title": "Аккаунт 34 уровень, 8 скинов оружия", "desc": "34 уровень, 8 редких скинов оружия включая AKM Glacier. Хороший старт!", "price": 1200},

        # ROBLOX
        {"cat": "Roblox", "title": "800 Robux фаст официально", "desc": "Официальное пополнение 800 Robux. Введу на ваш аккаунт за 5 минут после оплаты.", "price": 650},
        {"cat": "Roblox", "title": "Аккаунт Roblox 2019 года + хаты", "desc": "Старый аккаунт 2019 года, куплено хат на 4500R, редкие предметы. Хорошая история.", "price": 1100},
        {"cat": "Roblox", "title": "2000 Robux по выгодной цене", "desc": "2000 Robux — дешевле официального магазина. Работаю честно, 150+ довольных клиентов.", "price": 1400},
        {"cat": "Roblox", "title": "Roblox Premium 1 месяц + 450R", "desc": "Активирую Premium подписку на 1 месяц + 450 Robux. Введу код сразу после оплаты.", "price": 550},
        {"cat": "Roblox", "title": "Аккаунт Adopt Me легендарные питомцы", "desc": "Аккаунт с 12 легендарными питомцами в Adopt Me: Нeon Dragon, Shadow Dragon. Топ!", "price": 2800},

        # STANDOFF 2
        {"cat": "Standoff 2", "title": "Аккаунт 42 уровень Золото ранг", "desc": "42 уровень, Золото в ранговых. 14 скинов оружия, 3 ножа. Почта в комплекте.", "price": 1600},
        {"cat": "Standoff 2", "title": "Нож Керамбит Crimson Web продажа", "desc": "Редкий нож Керамбит Crimson Web. Передам через трейд безопасно. Торг уместен.", "price": 3400},
        {"cat": "Standoff 2", "title": "Аккаунт 18 уровень старт дёшево", "desc": "18 уровень, 6 скинов, АК Vulcan. Хорошее начало для игры. Быстрая передача.", "price": 400},
        {"cat": "Standoff 2", "title": "Аккаунт 67 уровень Платина + ножи", "desc": "67 лвл, Платиновый ранг. 5 ножей включая Butterfly Fade. 38 скинов оружия.", "price": 6200},
        {"cat": "Standoff 2", "title": "Голдены монеты 5000 штук фаст", "desc": "Пополню голды на ваш аккаунт. 5000 монет. Моментально после оплаты.", "price": 850},

        # STEAM
        {"cat": "Steam", "title": "Steam пополнение 500 рублей фаст", "desc": "Пополню кошелёк Steam на 500р. Активирую код в течение 15 минут.", "price": 580},
        {"cat": "Steam", "title": "Аккаунт Steam 47 игр + CS2 Prime", "desc": "47 игр, CS2 с Prime статусом, GTA V, RDR2. 2800 часов в играх. Старый аккаунт.", "price": 4500},
        {"cat": "Steam", "title": "Steam 1000 рублей выгодно", "desc": "Пополнение Steam 1000р. Работаю быстро, более 300 продаж. Гарантия возврата.", "price": 1100},
        {"cat": "Steam", "title": "Аккаунт 12 лет Steam + редкие игры", "desc": "Аккаунт с 2012 года, 89 игр, значки, торговые карточки. Half-Life редкие издания.", "price": 3800},

        # CS2
        {"cat": "CS2", "title": "Аккаунт CS2 Prime MG2 ранг", "desc": "Prime статус, ранг MG2. 1200 часов. Скин AWP Asiimov Field Tested.", "price": 2200},
        {"cat": "CS2", "title": "AK-47 Redline FT продажа скина", "desc": "Скин AK-47 Redline Field Tested. Передам через трейд. Популярный и красивый скин.", "price": 900},
        {"cat": "CS2", "title": "Аккаунт CS2 Supreme + AWP Dragon Lore", "desc": "Supreme ранг! AWP Dragon Lore Field Tested. 3400 часов. Топовый аккаунт.", "price": 28000},
        {"cat": "CS2", "title": "CS2 Prime активация аккаунта", "desc": "Активирую Prime статус на вашем аккаунте. Безопасно и быстро. Фаст до 30 минут.", "price": 1400},
        {"cat": "CS2", "title": "Аккаунт CS2 Gold Nova 3, чистый", "desc": "Gold Nova 3, 680 часов. Чистый аккаунт без банов. 4 скина включая M4A4 Howl копия.", "price": 1800},
    ]

    for d in demo_products:
        pid = product_counter[0]
        product_counter[0] += 1
        products[pid] = {
            "title": d["title"],
            "description": d["desc"],
            "price": d["price"],
            "category": d["cat"],
            "seller_id": ADMIN_ID,
            "seller_name": "SmartSales",
            "photos": []
        }
        sellers[ADMIN_ID]["products"].append(pid)

init_demo()

# --- ГЛАВНОЕ МЕНЮ ---
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_states[uid] = None
    is_seller = uid in sellers
    kb = [
        [InlineKeyboardButton("🛒 Каталог товаров", callback_data="catalog")],
        [InlineKeyboardButton("🤖 Купить ИИ-помощника", callback_data="buy_ai")],
        [InlineKeyboardButton("🗂 Мои покупки", callback_data="my_purchases")],
    ]
    if is_seller:
        kb.insert(2, [InlineKeyboardButton("🏪 Мой магазин", callback_data="my_shop")])
    else:
        kb.append([InlineKeyboardButton("📦 Стать продавцом", callback_data="become_seller")])
    await update.effective_message.reply_text(
        "👋 Добро пожаловать в *SmartSalesAI*!\n\n"
        "🎮 Цифровой магазин игровых товаров\n"
        "🤖 ИИ-продавец работает 24/7\n\n"
        "Выберите действие:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# --- ПОКУПКА ИИ ---
async def buy_ai_page(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    seller = sellers.get(uid, {})
    if seller.get("ai_paid"):
        ai_on = seller.get("ai_enabled", False)
        kb = [
            [InlineKeyboardButton("🔴 Выключить" if ai_on else "🟢 Включить", callback_data="toggle_ai_main")],
            [InlineKeyboardButton("✏️ Настроить промпт", callback_data="edit_ai_prompt_main")],
            [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
        ]
        await query.edit_message_text(
            f"🤖 *Ваш ИИ-помощник активен!*\n\n"
            f"Статус: {'✅ Работает' if ai_on else '❌ Выключен'}\n\n"
            f"ИИ автоматически отвечает покупателям если вы не ответили 2 минуты.",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
        )
        return
    yoo_link = f"https://yoomoney.ru/transfer/quickpay?receiver={YOOMONEY_WALLET}&sum={AI_PRICE}&label=ai_{uid}&targets=ИИ-помощник+SmartSalesAI"
    kb = [
        [InlineKeyboardButton(f"💳 Оплатить {AI_PRICE}₽ через ЮMoney", url=yoo_link)],
        [InlineKeyboardButton("✅ Я оплатил — жду активацию", callback_data="ai_paid_confirm")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
    ]
    await query.edit_message_text(
        f"🤖 *ИИ-помощник SmartSalesAI*\n\n"
        f"Ваш личный ИИ-продавец который:\n"
        f"• Отвечает покупателям пока вы спите 😴\n"
        f"• Знает все ваши товары и их плюсы\n"
        f"• Убеждает купить именно у вас 💪\n"
        f"• Работает 24/7 без выходных\n"
        f"• Отвечает за 3 секунды вместо вас\n\n"
        f"💰 Стоимость: *{AI_PRICE}₽/мес*\n"
        f"💳 ЮMoney: `{YOOMONEY_WALLET}`\n\n"
        f"После оплаты нажмите «Я оплатил» — активирую вручную в течение 1 часа.",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )

# --- КАТАЛОГ ---
async def show_catalog(update, ctx):
    query = update.callback_query
    await query.answer()
    kb = [[InlineKeyboardButton(f"{CAT_EMOJI.get(c,'📦')} {c}", callback_data=f"cat_{c}")] for c in CATEGORIES]
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="back_main")])
    await query.edit_message_text("📂 *Выберите категорию:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def show_category(update, ctx, category):
    query = update.callback_query
    await query.answer()
    items = [(pid, p) for pid, p in products.items() if p["category"] == category]
    if not items:
        await query.edit_message_text(
            "😔 Нет товаров.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="catalog")]])
        )
        return
    kb = []
    for pid, p in items:
        kb.append([InlineKeyboardButton(f"{p['title']} — {p['price']}₽", callback_data=f"product_{pid}_0")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="catalog")])
    await query.edit_message_text(
        f"{CAT_EMOJI.get(category,'📦')} *{category}* — {len(items)} товаров\n\nВыберите товар:",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )

async def show_product(update, ctx, pid, photo_idx=0):
    query = update.callback_query
    await query.answer()
    p = products.get(pid)
    if not p:
        await query.edit_message_text("Товар не найден.")
        return
    seller = sellers.get(p["seller_id"], {})
    ai_badge = "\n🤖 _ИИ-продавец онлайн 24/7_" if seller.get("ai_enabled") else ""
    text = (
        f"🛍 *{p['title']}*\n\n"
        f"📝 {p['description']}\n\n"
        f"💰 Цена: *{p['price']}₽*\n"
        f"👤 Продавец: {p['seller_name']}"
        f"{ai_badge}"
    )
    kb = [
        [InlineKeyboardButton("💬 Написать продавцу", callback_data=f"chat_seller_{pid}")],
        [InlineKeyboardButton("◀️ Назад", callback_data=f"cat_{p['category']}")],
    ]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

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
        f"✍️ Напишите сообщение продавцу.\n"
        f"⏱ Если не ответит 2 мин — ответит ИИ.\n\n"
        f"/start — выйти",
        parse_mode="Markdown"
    )
    try:
        kb = [[InlineKeyboardButton(f"↩️ Ответить {buyer_name}", callback_data=f"reply_to_{uid}")]]
        await ctx.bot.send_message(
            seller_id,
            f"📩 *Новый покупатель!*\n\n"
            f"👤 {buyer_name}\n"
            f"🛍 *{p['title']}* — {p['price']}₽\n\n"
            f"Нажмите кнопку чтобы ответить:",
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
    prompt = seller.get("ai_prompt", "Ты продавец цифровых товаров. Будь дружелюбным.")
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": f"{prompt}\nТовар: {p.get('title','')}. {p.get('description','')}. Цена: {p.get('price','')}₽. Отвечай кратко на русском, убедительно."},
                {"role": "user", "content": f"Покупатель {buyer_name} написал и ждёт ответа. Поприветствуй, расскажи о товаре и предложи купить."}
            ],
            max_tokens=300
        )
        ai_text = resp.choices[0].message.content
        chat["ai_replied"] = True
        await ctx.bot.send_message(buyer_id, f"🤖 *ИИ-продавец:*\n\n{ai_text}", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"AI error: {e}")

# --- СООБЩЕНИЯ ---
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text or ""
    state = user_states.get(uid, "")

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
                f"💬 *{buyer_name}:*\n{text}\n\n_Товар: {p.get('title','')}_",
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

    if state == "add_title":
        user_temp[uid] = {"title": text, "photos": []}
        user_states[uid] = "add_desc"
        await update.message.reply_text("📝 Введите описание:")
        return
    if state == "add_desc":
        user_temp[uid]["description"] = text
        user_states[uid] = "add_price"
        await update.message.reply_text("💰 Введите цену в рублях (только цифры):")
        return
    if state == "add_price":
        if not text.isdigit():
            await update.message.reply_text("❌ Только цифры!")
            return
        user_temp[uid]["price"] = int(text)
        user_states[uid] = "add_photos"
        await update.message.reply_text(
            "📷 Отправьте фото товара (до 10 штук).\nКогда готово — нажмите кнопку:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Готово — выбрать категорию", callback_data="photos_done")]])
        )
        return
    if state == "set_ai_prompt" or state == "set_ai_prompt_main":
        if uid in sellers:
            sellers[uid]["ai_prompt"] = text
        user_states[uid] = None
        await update.message.reply_text("✅ Промпт ИИ обновлён!")
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
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Готово — выбрать категорию", callback_data="photos_done")]])
        )

# --- МОЙ МАГАЗИН ---
async def my_shop(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    s = sellers.get(uid, {})
    ai_status = "✅ Активен" if s.get("ai_enabled") and s.get("ai_paid") else "❌ Не активен"
    my_prods = [p for p in s.get("products", []) if p in products]
    kb = [
        [InlineKeyboardButton("➕ Добавить товар", callback_data="add_product")],
        [InlineKeyboardButton("📦 Мои товары", callback_data="list_my_products")],
        [InlineKeyboardButton(f"🤖 ИИ-помощник: {ai_status}", callback_data="ai_settings")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
    ]
    await query.edit_message_text(
        f"🏪 *Мой магазин*\n\n"
        f"👤 {s.get('name','Продавец')}\n"
        f"📦 Товаров: {len(my_prods)}\n"
        f"🤖 ИИ-помощник: {ai_status}",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )

async def become_seller(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    if uid not in sellers:
        sellers[uid] = {
            "name": update.effective_user.first_name or "Продавец",
            "username": update.effective_user.username or "",
            "ai_enabled": False, "ai_paid": False,
            "ai_prompt": "Ты продавец цифровых товаров. Будь дружелюбным и убедительным.",
            "products": []
        }
    await my_shop(update, ctx)

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

# --- CALLBACKS ---
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = update.effective_user.id

    if data == "noop":
        await query.answer()
    elif data == "catalog":
        await show_catalog(update, ctx)
    elif data == "back_main":
        await query.answer()
        await start(update, ctx)
    elif data == "buy_ai":
        await buy_ai_page(update, ctx)
    elif data.startswith("cat_"):
        await show_category(update, ctx, data[4:])
    elif data.startswith("product_"):
        parts = data.split("_")
        pid, idx = int(parts[1]), int(parts[2]) if len(parts) > 2 else 0
        await show_product(update, ctx, pid, idx)
    elif data.startswith("chat_seller_"):
        await start_chat(update, ctx, int(data[12:]))
    elif data == "become_seller":
        await become_seller(update, ctx)
    elif data == "my_shop":
        await my_shop(update, ctx)
    elif data == "add_product":
        await query.answer()
        uid2 = update.effective_user.id
        user_states[uid2] = "add_title"
        user_temp[uid2] = {"photos": []}
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
            text += f"• {p['title']} — {p['price']}₽\n"
            kb.append([InlineKeyboardButton(f"🗑 {p['title'][:28]}", callback_data=f"del_product_{pid}")])
        kb.append([InlineKeyboardButton("◀️ Назад", callback_data="my_shop")])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
    elif data == "ai_settings":
        await ai_settings(update, ctx)
    elif data == "ai_paid_confirm":
        await query.answer()
        ai_pending_users.add(uid)
        uname = update.effective_user.username or update.effective_user.first_name or str(uid)
        try:
            await ctx.bot.send_message(
                ADMIN_ID,
                f"💰 *Заявка на ИИ-помощника!*\n\n"
                f"👤 @{uname}\n"
                f"🆔 ID: `{uid}`\n\n"
                f"Активируй командой: `/activate_{uid}`",
                parse_mode="Markdown"
            )
        except:
            pass
        await query.edit_message_text(
            "✅ *Заявка отправлена!*\n\n"
            "Активация в течение 1 часа после проверки оплаты.\n"
            "Мы уведомим вас когда ИИ будет активирован 🤖",
            parse_mode="Markdown",
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
        await query.edit_message_text(
            "✏️ Введите промпт для ИИ:\n\n"
            "Пример: _Ты опытный продавец игровых аккаунтов. Расскажи о плюсах товара, убеди купить._",
            parse_mode="Markdown"
        )
    elif data == "edit_ai_prompt_main":
        await query.answer()
        user_states[uid] = "set_ai_prompt_main"
        await query.edit_message_text(
            "✏️ Введите промпт для ИИ:\n\n"
            "Пример: _Ты опытный продавец. Рассказывай о преимуществах, убеждай купить._",
            parse_mode="Markdown"
        )
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
            "title": t.get("title", ""),
            "description": t.get("description", ""),
            "price": t.get("price", 0),
            "category": cat,
            "seller_id": uid,
            "seller_name": seller_name,
            "photos": t.get("photos", [])
        }
        if uid not in sellers:
            sellers[uid] = {"name": seller_name, "username": "", "ai_enabled": False, "ai_paid": False, "ai_prompt": "", "products": []}
        sellers[uid]["products"].append(pid)
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
        ai_pending_users.discard(target_id)
        try:
            await ctx.bot.send_message(
                target_id,
                "🎉 *ИИ-помощник активирован!*\n\n"
                "Теперь ИИ автоматически отвечает вашим покупателям если вы не ответили 2 минуты.\n\n"
                "Настроить промпт: /start → Мой магазин → ИИ-помощник",
                parse_mode="Markdown"
            )
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
