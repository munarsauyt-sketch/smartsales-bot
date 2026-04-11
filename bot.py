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

groq_client = Groq(api_key=GROQ_API_KEY)

# --- ДАННЫЕ ---
# products[id] = {title, description, price, category, seller_id, seller_name, photos:[]}
products = {}
product_counter = [1]

# sellers[user_id] = {name, username, ai_enabled, ai_prompt, products:[ids]}
sellers = {}

# chats[buyer_id] = {seller_id, product_id, waiting_since, ai_replied}
active_chats = {}

# pending_ai[buyer_id] = asyncio.Task
pending_ai_tasks = {}

# user states
user_states = {}  # user_id: state string
user_temp = {}    # user_id: temp data dict

CATEGORIES = ["Brawl Stars", "PUBG Mobile", "Roblox", "Standoff 2", "Steam", "CS2", "Другое"]
CAT_EMOJI = {"Brawl Stars": "🎯", "PUBG Mobile": "🔫", "Roblox": "🧱", "Standoff 2": "🔪", "Steam": "🎮", "CS2": "🏆", "Другое": "📦"}

# Добавим тестовые товары от админа
def init_demo():
    sellers[ADMIN_ID] = {"name": "SmartSales", "username": "admin", "ai_enabled": True,
                          "ai_prompt": "Ты продавец цифровых товаров. Будь дружелюбным, расскажи о товаре, убеди купить.", "products": []}
    demo = [
        {"title": "1000 Гемов Brawl Stars", "description": "Официальное пополнение через аккаунт. Безопасно и быстро!", "price": 3500, "category": "Brawl Stars"},
        {"title": "Brawl Pass Season", "description": "Brawl Pass на 1 сезон. Все награды и скины включены.", "price": 2800, "category": "Brawl Stars"},
        {"title": "600 UC PUBG Mobile", "description": "Пополнение UC на ваш аккаунт. ~5 минут.", "price": 4200, "category": "PUBG Mobile"},
        {"title": "800 Robux", "description": "Официальное пополнение Robux. Моментально.", "price": 2500, "category": "Roblox"},
        {"title": "Steam Wallet 1000₸", "description": "Пополнение кошелька Steam.", "price": 1200, "category": "Steam"},
        {"title": "CS2 Prime Status", "description": "Prime статус для CS2. Улучшенный матчмейкинг.", "price": 8900, "category": "CS2"},
    ]
    for d in demo:
        pid = product_counter[0]
        product_counter[0] += 1
        products[pid] = {**d, "seller_id": ADMIN_ID, "seller_name": "SmartSales", "photos": []}
        sellers[ADMIN_ID]["products"].append(pid)

init_demo()

# --- ГЛАВНОЕ МЕНЮ ---
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_states[uid] = None
    kb = [
        [InlineKeyboardButton("🛒 Каталог товаров", callback_data="catalog")],
        [InlineKeyboardButton("📦 Стать продавцом", callback_data="become_seller")],
        [InlineKeyboardButton("🗂 Мои покупки", callback_data="my_purchases")],
    ]
    if uid == ADMIN_ID or uid in sellers:
        kb.insert(1, [InlineKeyboardButton("🏪 Мой магазин", callback_data="my_shop")])
    await update.effective_message.reply_text(
        "👋 Добро пожаловать в *SmartSalesAI*!\n\nЦифровой магазин игровых товаров.\nВыберите действие:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# --- КАТАЛОГ ---
async def show_catalog(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = [[InlineKeyboardButton(f"{CAT_EMOJI.get(c,'📦')} {c}", callback_data=f"cat_{c}")] for c in CATEGORIES]
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="back_main")])
    await query.edit_message_text("📂 *Выберите категорию:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def show_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE, category: str):
    query = update.callback_query
    await query.answer()
    items = [(pid, p) for pid, p in products.items() if p["category"] == category]
    if not items:
        kb = [[InlineKeyboardButton("◀️ Назад", callback_data="catalog")]]
        await query.edit_message_text("😔 В этой категории пока нет товаров.", reply_markup=InlineKeyboardMarkup(kb))
        return
    kb = []
    for pid, p in items:
        kb.append([InlineKeyboardButton(f"{p['title']} — {p['price']}₸", callback_data=f"product_{pid}")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="catalog")])
    await query.edit_message_text(
        f"{CAT_EMOJI.get(category,'📦')} *{category}*\n\nВыберите товар:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def show_product(update: Update, ctx: ContextTypes.DEFAULT_TYPE, pid: int):
    query = update.callback_query
    await query.answer()
    p = products.get(pid)
    if not p:
        await query.edit_message_text("Товар не найден.")
        return
    seller = sellers.get(p["seller_id"], {})
    ai_badge = "🤖 ИИ-продавец активен" if seller.get("ai_enabled") else ""
    text = (
        f"🛍 *{p['title']}*\n\n"
        f"📝 {p['description']}\n\n"
        f"💰 Цена: *{p['price']}₸*\n"
        f"📦 Категория: {p['category']}\n"
        f"👤 Продавец: {p['seller_name']}\n"
        f"{ai_badge}"
    )
    kb = [
        [InlineKeyboardButton("💬 Написать продавцу", callback_data=f"chat_seller_{pid}")],
        [InlineKeyboardButton("◀️ Назад", callback_data=f"cat_{p['category']}")],
    ]
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

# --- ЧАТ С ПРОДАВЦОМ ---
async def start_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE, pid: int):
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
    active_chats[uid] = {"seller_id": seller_id, "product_id": pid, "waiting_since": asyncio.get_event_loop().time(), "ai_replied": False}
    user_states[uid] = f"chatting_{seller_id}_{pid}"
    await query.edit_message_text(
        f"💬 *Чат с продавцом {p['seller_name']}*\n\n"
        f"Товар: {p['title']}\n\n"
        f"Напишите ваше сообщение. Если продавец не ответит в течение 2 минут — ответит ИИ-помощник.\n\n"
        f"Для выхода напишите /start",
        parse_mode="Markdown"
    )
    # Уведомить продавца
    buyer = update.effective_user
    buyer_name = buyer.first_name or buyer.username or str(uid)
    try:
        await ctx.bot.send_message(
            seller_id,
            f"📩 *Новый покупатель!*\n\n"
            f"👤 {buyer_name} интересуется товаром: *{p['title']}*\n"
            f"💬 Ожидает ответа...\n\n"
            f"Ответьте через /reply_{uid}",
            parse_mode="Markdown"
        )
    except:
        pass
    # Запустить таймер ИИ
    if uid in pending_ai_tasks:
        pending_ai_tasks[uid].cancel()
    task = asyncio.create_task(ai_reply_after_delay(ctx, uid, pid, buyer_name))
    pending_ai_tasks[uid] = task

async def ai_reply_after_delay(ctx, buyer_id, pid, buyer_name):
    await asyncio.sleep(120)  # 2 минуты
    chat = active_chats.get(buyer_id)
    if not chat or chat.get("ai_replied"):
        return
    p = products.get(pid, {})
    seller = sellers.get(chat["seller_id"], {})
    if not seller.get("ai_enabled"):
        return
    prompt = seller.get("ai_prompt", "Ты продавец цифровых товаров.")
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": f"{prompt}\nТовар: {p.get('title','')}. {p.get('description','')}. Цена: {p.get('price','')}₸."},
                {"role": "user", "content": f"Покупатель {buyer_name} написал и ждёт ответа. Поприветствуй и расскажи о товаре."}
            ],
            max_tokens=300
        )
        ai_text = resp.choices[0].message.content
        chat["ai_replied"] = True
        await ctx.bot.send_message(buyer_id, f"🤖 *ИИ-продавец:*\n\n{ai_text}", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"AI error: {e}")

# --- ОБРАБОТКА СООБЩЕНИЙ В ЧАТЕ ---
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    state = user_states.get(uid, "")

    # Чат с продавцом
    if state and state.startswith("chatting_"):
        parts = state.split("_")
        seller_id = int(parts[1])
        pid = int(parts[2])
        p = products.get(pid, {})
        buyer_name = update.effective_user.first_name or str(uid)
        # Отменить ИИ таймер если продавец уже ответил вручную — нет, таймер для продавца
        # Переслать продавцу
        try:
            kb = [[InlineKeyboardButton(f"↩️ Ответить {buyer_name}", callback_data=f"reply_to_{uid}")]]
            await ctx.bot.send_message(
                seller_id,
                f"💬 *{buyer_name}* [{p.get('title','')}]:\n{text}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        except:
            pass
        await update.message.reply_text("✅ Сообщение отправлено продавцу. Ожидайте ответа...")
        return

    # Продавец отвечает покупателю
    if state and state.startswith("replying_to_"):
        buyer_id = int(state.split("_")[-1])
        seller_name = update.effective_user.first_name or "Продавец"
        # Отменить ИИ задачу
        task = pending_ai_tasks.get(buyer_id)
        if task:
            task.cancel()
            pending_ai_tasks.pop(buyer_id, None)
        chat = active_chats.get(buyer_id, {})
        chat["ai_replied"] = True
        try:
            await ctx.bot.send_message(buyer_id, f"👤 *{seller_name}:*\n{text}", parse_mode="Markdown")
        except:
            pass
        user_states[uid] = None
        await update.message.reply_text("✅ Ответ отправлен покупателю!")
        return

    # Добавление товара — шаги
    if state == "add_title":
        user_temp[uid] = {"title": text}
        user_states[uid] = "add_desc"
        await update.message.reply_text("📝 Введите описание товара:")
        return
    if state == "add_desc":
        user_temp[uid]["description"] = text
        user_states[uid] = "add_price"
        await update.message.reply_text("💰 Введите цену в тенге (только цифры):")
        return
    if state == "add_price":
        if not text.isdigit():
            await update.message.reply_text("❌ Введите только цифры!")
            return
        user_temp[uid]["price"] = int(text)
        user_states[uid] = "add_cat"
        kb = [[InlineKeyboardButton(c, callback_data=f"addcat_{c}")] for c in CATEGORIES]
        await update.message.reply_text("📂 Выберите категорию:", reply_markup=InlineKeyboardMarkup(kb))
        return

    # Настройка AI промпта
    if state == "set_ai_prompt":
        if uid in sellers:
            sellers[uid]["ai_prompt"] = text
            user_states[uid] = None
            await update.message.reply_text("✅ Промпт ИИ-продавца обновлён!")
        return

    await update.message.reply_text("Используйте /start для главного меню.")

# --- МОЙ МАГАЗИН ---
async def my_shop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    if uid not in sellers:
        sellers[uid] = {"name": update.effective_user.first_name or "Продавец",
                        "username": update.effective_user.username or "",
                        "ai_enabled": False, "ai_prompt": "", "products": []}
    s = sellers[uid]
    prod_count = len(s["products"])
    ai_status = "✅ Активен" if s.get("ai_enabled") else "❌ Не активен"
    kb = [
        [InlineKeyboardButton("➕ Добавить товар", callback_data="add_product")],
        [InlineKeyboardButton("📦 Мои товары", callback_data="list_my_products")],
        [InlineKeyboardButton(f"🤖 ИИ-продавец: {ai_status}", callback_data="ai_settings")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
    ]
    await query.edit_message_text(
        f"🏪 *Мой магазин*\n\n"
        f"👤 {s['name']}\n"
        f"📦 Товаров: {prod_count}\n"
        f"🤖 ИИ-продавец: {ai_status}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def become_seller(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    if uid not in sellers:
        sellers[uid] = {"name": update.effective_user.first_name or "Продавец",
                        "username": update.effective_user.username or "",
                        "ai_enabled": False, "ai_prompt": "", "products": []}
    await my_shop(update, ctx)

async def add_product_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    user_states[uid] = "add_title"
    user_temp[uid] = {}
    await query.edit_message_text("📝 *Добавление товара*\n\nВведите название товара:", parse_mode="Markdown")

async def list_my_products(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    s = sellers.get(uid, {})
    my_pids = s.get("products", [])
    if not my_pids:
        kb = [[InlineKeyboardButton("➕ Добавить товар", callback_data="add_product")],
              [InlineKeyboardButton("◀️ Назад", callback_data="my_shop")]]
        await query.edit_message_text("📦 У вас пока нет товаров.", reply_markup=InlineKeyboardMarkup(kb))
        return
    text = "📦 *Мои товары:*\n\n"
    kb = []
    for pid in my_pids:
        p = products.get(pid)
        if p:
            text += f"• {p['title']} — {p['price']}₸\n"
            kb.append([InlineKeyboardButton(f"🗑 Удалить: {p['title'][:20]}", callback_data=f"del_product_{pid}")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="my_shop")])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def ai_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    s = sellers.get(uid, {})
    ai_on = s.get("ai_enabled", False)
    toggle_text = "🔴 Выключить ИИ" if ai_on else "🟢 Включить ИИ"
    current_prompt = s.get("ai_prompt", "Не задан")
    kb = [
        [InlineKeyboardButton(toggle_text, callback_data="toggle_ai")],
        [InlineKeyboardButton("✏️ Изменить промпт", callback_data="edit_ai_prompt")],
        [InlineKeyboardButton("◀️ Назад", callback_data="my_shop")],
    ]
    await query.edit_message_text(
        f"🤖 *Настройки ИИ-продавца*\n\n"
        f"Статус: {'✅ Активен' if ai_on else '❌ Не активен'}\n\n"
        f"📝 Текущий промпт:\n_{current_prompt}_\n\n"
        f"ИИ автоматически отвечает покупателям если вы не ответили в течение 2 минут.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# --- CALLBACK HANDLER ---
async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = update.effective_user.id

    if data == "catalog":
        await show_catalog(update, ctx)
    elif data == "back_main":
        await query.answer()
        await start(update, ctx)
    elif data.startswith("cat_"):
        cat = data[4:]
        await show_category(update, ctx, cat)
    elif data.startswith("product_"):
        pid = int(data[8:])
        await show_product(update, ctx, pid)
    elif data.startswith("chat_seller_"):
        pid = int(data[12:])
        await start_chat(update, ctx, pid)
    elif data == "become_seller":
        await become_seller(update, ctx)
    elif data == "my_shop":
        await my_shop(update, ctx)
    elif data == "add_product":
        await add_product_start(update, ctx)
    elif data == "list_my_products":
        await list_my_products(update, ctx)
    elif data == "ai_settings":
        await ai_settings(update, ctx)
    elif data == "toggle_ai":
        await query.answer()
        if uid in sellers:
            sellers[uid]["ai_enabled"] = not sellers[uid].get("ai_enabled", False)
        await ai_settings(update, ctx)
    elif data == "edit_ai_prompt":
        await query.answer()
        user_states[uid] = "set_ai_prompt"
        await query.edit_message_text(
            "✏️ Введите промпт для вашего ИИ-продавца.\n\n"
            "Пример: *Ты опытный продавец игровых аккаунтов. Рассказывай о преимуществах товара, "
            "будь дружелюбным и убедительным.*",
            parse_mode="Markdown"
        )
    elif data.startswith("addcat_"):
        cat = data[7:]
        t = user_temp.get(uid, {})
        t["category"] = cat
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
            "photos": []
        }
        if uid not in sellers:
            sellers[uid] = {"name": seller_name, "username": "", "ai_enabled": False, "ai_prompt": "", "products": []}
        sellers[uid]["products"].append(pid)
        user_states[uid] = None
        await query.answer("✅ Товар добавлен!")
        await query.edit_message_text(
            f"✅ *Товар добавлен!*\n\n"
            f"📦 {t.get('title')}\n"
            f"💰 {t.get('price')}₸\n"
            f"📂 {cat}",
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
        await list_my_products(update, ctx)
    elif data.startswith("reply_to_"):
        buyer_id = int(data[9:])
        user_states[uid] = f"replying_to_{buyer_id}"
        await query.answer()
        await ctx.bot.send_message(uid, f"✏️ Напишите ответ покупателю (id: {buyer_id}):")
    elif data == "my_purchases":
        await query.answer()
        await query.edit_message_text(
            "🗂 *Мои покупки*\n\nИстория покупок пока пуста.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back_main")]])
        )

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
