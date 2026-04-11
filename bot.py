import os
import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "1048682172"))
YOOMONEY_WALLET = "4100118679419062"
AI_PRICE = 500  # рублей

groq_client = Groq(api_key=GROQ_API_KEY)

# --- ХРАНИЛИЩЕ ---
products = {}
product_counter = [1]
sellers = {}
active_chats = {}
pending_ai_tasks = {}
user_states = {}
user_temp = {}

CATEGORIES = ["Brawl Stars", "PUBG Mobile", "Roblox", "Standoff 2", "Steam", "CS2", "Другое"]
CAT_EMOJI = {"Brawl Stars": "🎯", "PUBG Mobile": "🔫", "Roblox": "🧱",
             "Standoff 2": "🔪", "Steam": "🎮", "CS2": "🏆", "Другое": "📦"}

def init_demo():
    sellers[ADMIN_ID] = {
        "name": "SmartSales", "username": "admin",
        "ai_enabled": True,
        "ai_prompt": "Ты продавец цифровых товаров. Будь дружелюбным, расскажи о товаре, убеди купить.",
        "products": [], "ai_paid": True,
        "delivery_data": {}
    }
    demo = [
        {"title": "1000 Гемов Brawl Stars", "description": "Официальное пополнение через аккаунт. Безопасно и быстро!", "price": 3500, "category": "Brawl Stars", "delivery": "Свяжитесь с продавцом после оплаты"},
        {"title": "Brawl Pass Season", "description": "Brawl Pass на 1 сезон. Все награды и скины включены.", "price": 2800, "category": "Brawl Stars", "delivery": "Свяжитесь с продавцом после оплаты"},
        {"title": "600 UC PUBG Mobile", "description": "Пополнение UC на ваш аккаунт. ~5 минут.", "price": 4200, "category": "PUBG Mobile", "delivery": "Свяжитесь с продавцом после оплаты"},
        {"title": "800 Robux", "description": "Официальное пополнение Robux. Моментально.", "price": 2500, "category": "Roblox", "delivery": "Свяжитесь с продавцом после оплаты"},
        {"title": "Steam Wallet 1000₸", "description": "Пополнение кошелька Steam.", "price": 1200, "category": "Steam", "delivery": "Свяжитесь с продавцом после оплаты"},
        {"title": "CS2 Prime Status", "description": "Prime статус для CS2. Улучшенный матчмейкинг.", "price": 8900, "category": "CS2", "delivery": "Свяжитесь с продавцом после оплаты"},
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
    is_seller = uid in sellers
    kb = [
        [InlineKeyboardButton("🛒 Каталог товаров", callback_data="catalog")],
        [InlineKeyboardButton("🗂 Мои покупки", callback_data="my_purchases")],
    ]
    if is_seller:
        kb.insert(1, [InlineKeyboardButton("🏪 Мой магазин", callback_data="my_shop")])
    else:
        kb.append([InlineKeyboardButton("📦 Стать продавцом", callback_data="become_seller")])
    msg = update.effective_message
    await msg.reply_text(
        "👋 Добро пожаловать в *SmartSalesAI*!\n\nЦифровой магазин игровых товаров.\nВыберите действие:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
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
        kb = [[InlineKeyboardButton("◀️ Назад", callback_data="catalog")]]
        await query.edit_message_text("😔 В этой категории пока нет товаров.", reply_markup=InlineKeyboardMarkup(kb))
        return
    kb = []
    for pid, p in items:
        ai_badge = "🤖" if sellers.get(p["seller_id"], {}).get("ai_enabled") else ""
        kb.append([InlineKeyboardButton(f"{ai_badge} {p['title']} — {p['price']}₸", callback_data=f"product_{pid}_0")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="catalog")])
    await query.edit_message_text(
        f"{CAT_EMOJI.get(category,'📦')} *{category}*\n\nВыберите товар:",
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
    ai_badge = "🤖 ИИ-продавец активен" if seller.get("ai_enabled") else ""
    photos = p.get("photos", [])
    text = (
        f"🛍 *{p['title']}*\n\n"
        f"📝 {p['description']}\n\n"
        f"💰 Цена: *{p['price']}₸*\n"
        f"📂 {p['category']}\n"
        f"👤 Продавец: {p['seller_name']}\n"
        f"{ai_badge}"
    )
    kb = []
    # Навигация по фото
    if photos:
        nav = []
        if photo_idx > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"product_{pid}_{photo_idx-1}"))
        nav.append(InlineKeyboardButton(f"📷 {photo_idx+1}/{len(photos)}", callback_data="noop"))
        if photo_idx < len(photos)-1:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"product_{pid}_{photo_idx+1}"))
        kb.append(nav)
    kb.append([InlineKeyboardButton("💬 Написать продавцу", callback_data=f"chat_seller_{pid}")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data=f"cat_{p['category']}")])
    markup = InlineKeyboardMarkup(kb)
    if photos and photo_idx < len(photos):
        try:
            await ctx.bot.send_photo(
                update.effective_chat.id,
                photo=photos[photo_idx],
                caption=text,
                parse_mode="Markdown",
                reply_markup=markup
            )
            await query.message.delete()
        except:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
    else:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)

# --- ЧАТ С ПРОДАВЦОМ ---
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
    active_chats[uid] = {
        "seller_id": seller_id, "product_id": pid,
        "ai_replied": False
    }
    user_states[uid] = f"chatting_{seller_id}_{pid}"
    buyer_name = update.effective_user.first_name or str(uid)
    await query.edit_message_text(
        f"💬 *Чат с продавцом {p['seller_name']}*\n\n"
        f"Товар: _{p['title']}_\n\n"
        f"✍️ Напишите ваше сообщение.\n"
        f"⏱ Если продавец не ответит 2 мин — ответит ИИ.\n\n"
        f"/start — выйти из чата",
        parse_mode="Markdown"
    )
    try:
        kb = [[InlineKeyboardButton(f"↩️ Ответить {buyer_name}", callback_data=f"reply_to_{uid}")]]
        await ctx.bot.send_message(
            seller_id,
            f"📩 *Новый покупатель!*\n👤 {buyer_name}\n🛍 Товар: *{p['title']}*\n\nОжидает ответа...",
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
                {"role": "system", "content": f"{prompt}\nТовар: {p.get('title','')}. {p.get('description','')}. Цена: {p.get('price','')}₸. Говори кратко и убедительно на русском."},
                {"role": "user", "content": f"Покупатель {buyer_name} интересуется товаром. Поприветствуй и предложи купить."}
            ],
            max_tokens=250
        )
        ai_text = resp.choices[0].message.content
        chat["ai_replied"] = True
        await ctx.bot.send_message(buyer_id, f"🤖 *ИИ-продавец:*\n\n{ai_text}", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"AI error: {e}")

# --- ОБРАБОТКА СООБЩЕНИЙ ---
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text or ""
    state = user_states.get(uid, "")

    # Чат покупателя с продавцом
    if state and state.startswith("chatting_"):
        parts = state.split("_")
        seller_id = int(parts[1])
        pid = int(parts[2])
        p = products.get(pid, {})
        buyer_name = update.effective_user.first_name or str(uid)
        chat = active_chats.get(uid, {})
        # Отменить ИИ если ещё не ответил — покупатель написал, продолжаем ждать продавца
        try:
            kb = [[InlineKeyboardButton(f"↩️ Ответить {buyer_name}", callback_data=f"reply_to_{uid}")]]
            await ctx.bot.send_message(
                seller_id,
                f"💬 *{buyer_name}* [{p.get('title','')}]:\n{text}",
                parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
            )
        except:
            pass
        await update.message.reply_text("✅ Отправлено. Ожидайте ответа продавца...")
        return

    # Продавец отвечает покупателю
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
        await update.message.reply_text("✅ Ответ отправлен покупателю!")
        return

    # Добавление товара
    if state == "add_title":
        user_temp[uid] = {"title": text, "photos": []}
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
            await update.message.reply_text("❌ Только цифры!")
            return
        user_temp[uid]["price"] = int(text)
        user_states[uid] = "add_delivery"
        await update.message.reply_text(
            "📦 Введите данные для выдачи товара после оплаты:\n"
            "(например: логин/пароль, ключ активации, ссылка)\n\n"
            "Эти данные покупатель получит автоматически после подтверждения оплаты."
        )
        return
    if state == "add_delivery":
        user_temp[uid]["delivery"] = text
        user_states[uid] = "add_photos"
        await update.message.reply_text(
            "📷 Отправьте фото товара (до 10 штук).\n"
            "Когда закончите — нажмите кнопку ниже.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Готово, выбрать категорию", callback_data="photos_done")]])
        )
        return
    if state == "add_photos":
        await update.message.reply_text(
            "📷 Отправляйте фото. Когда закончите — нажмите кнопку выше.",
        )
        return

    # Промпт ИИ
    if state == "set_ai_prompt":
        if uid in sellers:
            sellers[uid]["ai_prompt"] = text
            user_states[uid] = None
            await update.message.reply_text("✅ Промпт ИИ обновлён!")
        return

    await update.message.reply_text("Используйте /start")

# Обработка фото
async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    state = user_states.get(uid, "")
    if state == "add_photos":
        if uid not in user_temp:
            user_temp[uid] = {"photos": []}
        if "photos" not in user_temp[uid]:
            user_temp[uid]["photos"] = []
        photos = user_temp[uid]["photos"]
        if len(photos) >= 10:
            await update.message.reply_text("❌ Максимум 10 фото!")
            return
        file_id = update.message.photo[-1].file_id
        photos.append(file_id)
        count = len(photos)
        await update.message.reply_text(
            f"✅ Фото {count}/10 добавлено!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Готово, выбрать категорию", callback_data="photos_done")]])
        )
    else:
        await update.message.reply_text("Используйте /start")

# --- МОЙ МАГАЗИН ---
async def my_shop(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    s = sellers.get(uid, {})
    prod_count = len(s.get("products", []))
    ai_status = "✅ Активен" if s.get("ai_enabled") and s.get("ai_paid") else "❌ Не активен"
    kb = [
        [InlineKeyboardButton("➕ Добавить товар", callback_data="add_product")],
        [InlineKeyboardButton("📦 Мои товары", callback_data="list_my_products")],
        [InlineKeyboardButton(f"🤖 ИИ-продавец: {ai_status}", callback_data="ai_settings")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_main")],
    ]
    await query.edit_message_text(
        f"🏪 *Мой магазин*\n\n👤 {s.get('name','')}\n📦 Товаров: {prod_count}\n🤖 ИИ: {ai_status}",
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
            "products": [], "delivery_data": {}
        }
    await my_shop(update, ctx)

async def add_product_start(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    user_states[uid] = "add_title"
    user_temp[uid] = {"photos": []}
    await query.edit_message_text("📝 *Добавление товара*\n\nВведите название:", parse_mode="Markdown")

async def list_my_products(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    s = sellers.get(uid, {})
    my_pids = s.get("products", [])
    if not my_pids:
        kb = [[InlineKeyboardButton("➕ Добавить товар", callback_data="add_product")],
              [InlineKeyboardButton("◀️ Назад", callback_data="my_shop")]]
        await query.edit_message_text("📦 Нет товаров.", reply_markup=InlineKeyboardMarkup(kb))
        return
    text = "📦 *Мои товары:*\n\n"
    kb = []
    for pid in my_pids:
        p = products.get(pid)
        if p:
            ph = f" 📷{len(p.get('photos',[]))}" if p.get('photos') else ""
            text += f"• {p['title']} — {p['price']}₸{ph}\n"
            kb.append([InlineKeyboardButton(f"🗑 {p['title'][:25]}", callback_data=f"del_product_{pid}")])
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="my_shop")])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

async def ai_settings(update, ctx):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    s = sellers.get(uid, {})
    ai_paid = s.get("ai_paid", False)
    ai_on = s.get("ai_enabled", False)
    if not ai_paid:
        yoo_link = f"https://yoomoney.ru/transfer/quickpay?receiver={YOOMONEY_WALLET}&sum={AI_PRICE}&label=ai_{uid}&targets=ИИ-продавец+SmartSalesAI"
        kb = [
            [InlineKeyboardButton(f"💳 Оплатить {AI_PRICE} руб через ЮMoney", url=yoo_link)],
            [InlineKeyboardButton("✅ Я оплатил", callback_data="ai_paid_confirm")],
            [InlineKeyboardButton("◀️ Назад", callback_data="my_shop")],
        ]
        await query.edit_message_text(
            f"🤖 *ИИ-продавец SmartSalesAI*\n\n"
            f"Ваш личный ИИ который:\n"
            f"• Отвечает покупателям пока вы спите\n"
            f"• Знает все ваши товары\n"
            f"• Убеждает купить именно у вас\n"
            f"• Работает 24/7\n\n"
            f"💰 Стоимость: *{AI_PRICE} руб/мес*\n"
            f"💳 ЮMoney: `{YOOMONEY_WALLET}`\n\n"
            f"После оплаты нажмите «Я оплатил»",
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
        )
        return
    toggle_text = "🔴 Выключить ИИ" if ai_on else "🟢 Включить ИИ"
    prompt = s.get("ai_prompt", "Не задан")
    kb = [
        [InlineKeyboardButton(toggle_text, callback_data="toggle_ai")],
        [InlineKeyboardButton("✏️ Изменить промпт", callback_data="edit_ai_prompt")],
        [InlineKeyboardButton("◀️ Назад", callback_data="my_shop")],
    ]
    await query.edit_message_text(
        f"🤖 *ИИ-продавец*\n\n"
        f"Статус: {'✅ Активен' if ai_on else '❌ Выключен'}\n\n"
        f"📝 Промпт:\n_{prompt[:200]}_\n\n"
        f"ИИ отвечает если вы не ответили 2 минуты.",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )

# --- CALLBACK HANDLER ---
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
    elif data.startswith("cat_"):
        await show_category(update, ctx, data[4:])
    elif data.startswith("product_"):
        parts = data.split("_")
        pid = int(parts[1])
        idx = int(parts[2]) if len(parts) > 2 else 0
        await show_product(update, ctx, pid, idx)
    elif data.startswith("chat_seller_"):
        await start_chat(update, ctx, int(data[12:]))
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
    elif data == "ai_paid_confirm":
        await query.answer()
        # Уведомить админа
        uname = update.effective_user.username or update.effective_user.first_name
        try:
            await ctx.bot.send_message(
                ADMIN_ID,
                f"💰 *Заявка на ИИ-продавца!*\n\n👤 @{uname} (id: {uid})\n\nАктивируй: /activate_{uid}",
                parse_mode="Markdown"
            )
        except:
            pass
        await query.edit_message_text(
            "✅ Заявка отправлена!\n\nАктивация в течение 1 часа после проверки оплаты.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="my_shop")]])
        )
    elif data == "toggle_ai":
        await query.answer()
        if uid in sellers:
            sellers[uid]["ai_enabled"] = not sellers[uid].get("ai_enabled", False)
        await ai_settings(update, ctx)
    elif data == "edit_ai_prompt":
        await query.answer()
        user_states[uid] = "set_ai_prompt"
        await query.edit_message_text(
            "✏️ Введите промпт для ИИ-продавца:\n\n"
            "Пример: _Ты опытный продавец. Рассказывай о преимуществах, убеждай купить, отвечай на вопросы._",
            parse_mode="Markdown"
        )
    elif data == "photos_done":
        await query.answer()
        kb = [[InlineKeyboardButton(c, callback_data=f"addcat_{c}")] for c in CATEGORIES]
        await query.edit_message_text("📂 Выберите категорию товара:", reply_markup=InlineKeyboardMarkup(kb))
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
            "delivery": t.get("delivery", ""),
            "category": cat,
            "seller_id": uid,
            "seller_name": seller_name,
            "photos": t.get("photos", [])
        }
        if uid not in sellers:
            sellers[uid] = {"name": seller_name, "username": "", "ai_enabled": False, "ai_paid": False, "ai_prompt": "", "products": []}
        sellers[uid]["products"].append(pid)
        user_states[uid] = None
        ph_count = len(t.get("photos", []))
        await query.answer("✅ Товар добавлен!")
        await query.edit_message_text(
            f"✅ *Товар добавлен!*\n\n📦 {t.get('title')}\n💰 {t.get('price')}₸\n📂 {cat}\n📷 Фото: {ph_count}",
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
        await ctx.bot.send_message(uid, f"✏️ Напишите ответ покупателю:")
    elif data == "my_purchases":
        await query.answer()
        await query.edit_message_text(
            "🗂 *Мои покупки*\n\nИстория пока пуста.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="back_main")]])
        )

# Команда активации ИИ для админа
async def handle_activate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != ADMIN_ID:
        return
    text = update.message.text
    if text.startswith("/activate_"):
        target_id = int(text.split("_")[1])
        if target_id in sellers:
            sellers[target_id]["ai_paid"] = True
            sellers[target_id]["ai_enabled"] = True
            try:
                await ctx.bot.send_message(target_id, "🎉 *ИИ-продавец активирован!*\n\nТеперь ИИ будет отвечать вашим покупателям автоматически.", parse_mode="Markdown")
            except:
                pass
            await update.message.reply_text(f"✅ ИИ активирован для {target_id}")
        else:
            await update.message.reply_text("❌ Продавец не найден")

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
