import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from data import users, products, get_user, ai_active, ai_prompts, pending_chats, ADMIN_ID, YOOMONEY
from ai import ask_ai

logging.basicConfig(level=logging.INFO)

# ══════════════════════════════════════
# START
# ══════════════════════════════════════
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username or update.effective_user.first_name
    get_user(uid, uname)
    
    kb = [
        [InlineKeyboardButton("🛒 Каталог товаров", callback_data="catalog")],
        [InlineKeyboardButton("🤖 ИИ-помощник", callback_data="ai_help")],
        [InlineKeyboardButton("📦 Мои покупки", callback_data="my_purchases")],
        [InlineKeyboardButton("👤 Кабинет продавца", callback_data="seller_cabinet")],
    ]
    await update.message.reply_text(
        "👋 Добро пожаловать в *SmartSalesAI*!\n\n"
        "🎮 Лучший маркетплейс цифровых товаров\n"
        "⚡️ Моментальная доставка · 🤖 ИИ-продавец · 🔒 Безопасные сделки",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

# ══════════════════════════════════════
# КАТАЛОГ
# ══════════════════════════════════════
CATEGORIES = ["Brawl Stars", "PUBG Mobile", "Roblox", "Standoff 2", "Steam", "CS2"]
CAT_EMOJI  = {"Brawl Stars":"🎯","PUBG Mobile":"🔫","Roblox":"🧱","Standoff 2":"🔪","Steam":"🎮","CS2":"🏆"}

async def catalog(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    kb = [[InlineKeyboardButton(f"{CAT_EMOJI.get(c,'🎮')} {c}", callback_data=f"cat_{c}")] for c in CATEGORIES]
    kb.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main")])
    await q.edit_message_text("🛒 *Выберите категорию:*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cat = q.data.replace("cat_", "")
    items = [p for p in products if p["category"] == cat]
    if not items:
        await q.edit_message_text("😔 В этой категории пока нет товаров.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="catalog")]]))
        return
    kb = [[InlineKeyboardButton(f"{p['name']} — {p['price']} ₸", callback_data=f"prod_{p['id']}")] for p in items]
    kb.append([InlineKeyboardButton("◀️ Назад", callback_data="catalog")])
    await q.edit_message_text(f"{CAT_EMOJI.get(cat,'🎮')} *{cat}*\n\nВыберите товар:", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def product(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.replace("prod_", ""))
    p = next((x for x in products if x["id"] == pid), None)
    if not p:
        await q.edit_message_text("❌ Товар не найден.")
        return
    text = (
        f"🎮 *{p['name']}*\n\n"
        f"📝 {p['desc']}\n\n"
        f"💰 Цена: *{p['price']} ₸*\n"
        f"⚡️ Доставка: {p.get('delivery','Моментально')}\n"
        f"👤 Продавец: {p['seller']}\n"
        f"⭐️ Рейтинг: 5.0"
    )
    kb = [
        [InlineKeyboardButton("💰 Купить", callback_data=f"buy_{pid}"),
         InlineKeyboardButton("💬 Написать продавцу", callback_data=f"chat_{p['seller_id']}_{pid}")],
        [InlineKeyboardButton("◀️ Назад", callback_data=f"cat_{p['category']}")]
    ]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pid = int(q.data.replace("buy_", ""))
    p = next((x for x in products if x["id"] == pid), None)
    if not p:
        return
    text = (
        f"💳 *Оплата товара*\n\n"
        f"Товар: {p['name']}\n"
        f"Сумма: *{p['price']} ₸*\n\n"
        f"Для оплаты напишите продавцу — он пришлёт реквизиты.\n\n"
        f"После договорённости нажмите «Написать продавцу» 👇"
    )
    kb = [
        [InlineKeyboardButton("💬 Написать продавцу", callback_data=f"chat_{p['seller_id']}_{pid}")],
        [InlineKeyboardButton("◀️ Назад", callback_data=f"prod_{pid}")]
    ]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# ══════════════════════════════════════
# ЧАТ С ПРОДАВЦОМ + ИИ
# ══════════════════════════════════════
async def start_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split("_")
    seller_id = int(parts[1])
    pid = int(parts[2])
    buyer_id = update.effective_user.id
    buyer_name = update.effective_user.username or update.effective_user.first_name
    p = next((x for x in products if x["id"] == pid), None)
    product_name = p["name"] if p else "товар"
    
    pending_chats[buyer_id] = {
        "seller_id": seller_id,
        "product_id": pid,
        "product_name": product_name,
        "time": asyncio.get_event_loop().time()
    }
    users[buyer_id]["chatting_with"] = seller_id
    
    await q.edit_message_text(
        f"💬 *Чат с продавцом*\n\nПишите сообщение — продавец ответит вам.\n"
        f"Если продавец не ответит в течение минуты, ИИ-помощник ответит вместо него.\n\n"
        f"👇 Напишите ваш вопрос:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Выйти из чата", callback_data="exit_chat")]]),
        parse_mode="Markdown"
    )
    
    try:
        await ctx.bot.send_message(
            seller_id,
            f"💬 *Новый покупатель!*\n\n"
            f"👤 @{buyer_name} спрашивает про: *{product_name}*\n\n"
            f"Ответьте на это сообщение — оно дойдёт до покупателя.\n"
            f"(Ваш ID покупателя: `{buyer_id}`)",
            parse_mode="Markdown"
        )
    except:
        pass

async def exit_chat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    if uid in users:
        users[uid]["chatting_with"] = None
    if uid in pending_chats:
        del pending_chats[uid]
    kb = [[InlineKeyboardButton("🏠 Главное меню", callback_data="main")]]
    await q.edit_message_text("✅ Вы вышли из чата.", reply_markup=InlineKeyboardMarkup(kb))

# ══════════════════════════════════════
# ОБРАБОТКА СООБЩЕНИЙ В ЧАТЕ
# ══════════════════════════════════════
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    uname = update.effective_user.username or update.effective_user.first_name
    get_user(uid, uname)
    
    # Режим ИИ-помощника
    if users[uid].get("ai_mode"):
        await update.message.chat.send_action("typing")
        reply = await ask_ai(text, "Ты помощник цифрового магазина SmartSalesAI. Помогаешь выбрать игровые товары. Отвечай кратко на русском.")
        kb = [[InlineKeyboardButton("🏠 Главное меню", callback_data="main_exit_ai")]]
        await update.message.reply_text(f"🤖 {reply}", reply_markup=InlineKeyboardMarkup(kb))
        return
    
    # Режим настройки промпта продавца
    if users[uid].get("setting_prompt"):
        ai_prompts[uid] = text
        users[uid]["setting_prompt"] = False
        await update.message.reply_text(
            "✅ Промпт сохранён! Теперь ваш ИИ будет использовать его.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ В кабинет", callback_data="seller_cabinet")]])
        )
        return
    
    # Чат покупателя с продавцом
    if users[uid].get("chatting_with"):
        seller_id = users[uid]["chatting_with"]
        chat_info = pending_chats.get(uid, {})
        
        try:
            await ctx.bot.send_message(
                seller_id,
                f"💬 Покупатель @{uname} пишет:\n\n{text}\n\n(Ответьте прямо здесь)"
            )
        except:
            pass
        
        await update.message.reply_text("✉️ Сообщение отправлено продавцу. Ожидайте ответа...")
        
        # Таймер 60 сек для ИИ
        await asyncio.sleep(60)
        
        if uid in pending_chats and pending_chats[uid].get("waiting_ai"):
            return
        
        if uid in pending_chats:
            pending_chats[uid]["waiting_ai"] = True
            product_name = chat_info.get("product_name", "товар")
            seller_prompt = ai_prompts.get(seller_id, "")
            
            if ai_active.get(seller_id):
                seller_products = [p["name"] for p in products if p["seller_id"] == seller_id]
                prompt = (
                    f"Ты ИИ-продавец магазина SmartSalesAI. {seller_prompt} "
                    f"Товары продавца: {', '.join(seller_products)}. "
                    f"Покупатель спрашивает про {product_name}. "
                    f"Отвечай убедительно, помогай купить, на русском языке."
                )
                reply = await ask_ai(text, prompt)
                await ctx.bot.send_message(uid, f"🤖 *ИИ-продавец:*\n\n{reply}", parse_mode="Markdown")
        return
    
    # Продавец отвечает покупателю (через reply или команду /reply ID текст)
    if text.startswith("/reply"):
        parts = text.split(" ", 2)
        if len(parts) == 3:
            try:
                buyer_id = int(parts[1])
                msg = parts[2]
                if buyer_id in pending_chats:
                    del pending_chats[buyer_id]
                await ctx.bot.send_message(buyer_id, f"💬 *Продавец отвечает:*\n\n{msg}", parse_mode="Markdown")
                await update.message.reply_text("✅ Ответ отправлен покупателю!")
            except:
                await update.message.reply_text("❌ Ошибка. Формат: /reply ID сообщение")
        return

# ══════════════════════════════════════
# ИИ-ПОМОЩНИК
# ══════════════════════════════════════
async def ai_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    users[uid]["ai_mode"] = True
    await q.edit_message_text(
        "🤖 *ИИ-помощник SmartSalesAI*\n\n"
        "Я помогу вам выбрать товар! Спросите меня:\n"
        "• Какие товары есть для Brawl Stars?\n"
        "• Что лучше купить для PUBG?\n"
        "• Как работает доставка?\n\n"
        "💬 Напишите ваш вопрос:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Выйти", callback_data="main_exit_ai")]]),
        parse_mode="Markdown"
    )

async def exit_ai(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    users[uid]["ai_mode"] = False
    await main_menu(update, ctx)

# ══════════════════════════════════════
# КАБИНЕТ ПРОДАВЦА
# ══════════════════════════════════════
async def seller_cabinet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    uname = update.effective_user.username or update.effective_user.first_name
    get_user(uid, uname)
    
    my_products = [p for p in products if p["seller_id"] == uid]
    ai_status = "✅ Активен" if ai_active.get(uid) else "❌ Не активен"
    
    text = (
        f"👤 *Кабинет продавца*\n\n"
        f"📦 Моих товаров: {len(my_products)}\n"
        f"🤖 ИИ-продавец: {ai_status}\n\n"
    )
    kb = [
        [InlineKeyboardButton("📦 Мои товары", callback_data="my_products"),
         InlineKeyboardButton("➕ Добавить товар", callback_data="add_product")],
        [InlineKeyboardButton("🤖 ИИ-продавец", callback_data="ai_seller")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="main")]
    ]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def ai_seller(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    
    if ai_active.get(uid):
        current_prompt = ai_prompts.get(uid, "Не задан")
        text = (
            f"🤖 *ИИ-продавец активен!*\n\n"
            f"Ваш промпт:\n_{current_prompt}_\n\n"
            f"ИИ автоматически отвечает покупателям если вы не ответили за 60 секунд."
        )
        kb = [
            [InlineKeyboardButton("✏️ Изменить промпт", callback_data="set_prompt")],
            [InlineKeyboardButton("◀️ Назад", callback_data="seller_cabinet")]
        ]
    else:
        text = (
            f"🤖 *ИИ-продавец SmartSalesAI*\n\n"
            f"Ваш личный ИИ-помощник который:\n"
            f"• Отвечает покупателям пока вы спите 💤\n"
            f"• Знает все ваши товары 📦\n"
            f"• Убеждает купить именно у вас 💰\n"
            f"• Работает 24/7 без выходных ⚡️\n\n"
            f"💳 Стоимость: *500 руб/мес*\n\n"
            f"Оплата через ЮMoney: `{YOOMONEY}`\n"
            f"После оплаты нажмите «Я оплатил ✅»"
        )
        pay_url = f"https://yoomoney.ru/quickpay/confirm?receiver={YOOMONEY}&sum=500&label=ai_{uid}&targets=ИИ-продавец+SmartSalesAI"
        kb = [
            [InlineKeyboardButton("💳 Оплатить 500 руб", url=pay_url)],
            [InlineKeyboardButton("✅ Я оплатил", callback_data="paid_ai")],
            [InlineKeyboardButton("◀️ Назад", callback_data="seller_cabinet")]
        ]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def paid_ai(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    uname = update.effective_user.username or str(uid)
    
    try:
        await ctx.bot.send_message(
            ADMIN_ID,
            f"💰 *Запрос на активацию ИИ-продавца*\n\n"
            f"👤 @{uname} (ID: `{uid}`)\n"
            f"Для активации: `/activate {uid}`",
            parse_mode="Markdown"
        )
    except:
        pass
    
    await q.edit_message_text(
        "⏳ *Заявка отправлена!*\n\n"
        "Мы проверим оплату и активируем ИИ-продавца в течение 1 часа.\n\n"
        "По вопросам: @SmartSalesAI_kz_bot",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="seller_cabinet")]]),
        parse_mode="Markdown"
    )

async def set_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    users[uid]["setting_prompt"] = True
    await q.edit_message_text(
        "✏️ *Настройка промпта ИИ-продавца*\n\n"
        "Напишите инструкцию для вашего ИИ. Например:\n\n"
        "_«Ты вежливый продавец. Всегда предлагай скидку при покупке от 2 товаров. Отвечай на казахском и русском.»_\n\n"
        "Напишите ваш промпт:",
        parse_mode="Markdown"
    )

async def my_products(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    my_p = [p for p in products if p["seller_id"] == uid]
    if not my_p:
        text = "📦 У вас пока нет товаров.\n\nДобавьте первый товар!"
    else:
        text = "📦 *Ваши товары:*\n\n" + "\n".join([f"• {p['name']} — {p['price']} ₸" for p in my_p])
    kb = [
        [InlineKeyboardButton("➕ Добавить товар", callback_data="add_product")],
        [InlineKeyboardButton("◀️ Назад", callback_data="seller_cabinet")]
    ]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def add_product(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    users[uid]["adding_product"] = {"step": "name"}
    await q.edit_message_text(
        "➕ *Добавление товара*\n\n"
        "Шаг 1/4: Напишите *название* товара:",
        parse_mode="Markdown"
    )

# ══════════════════════════════════════
# МОИ ПОКУПКИ
# ══════════════════════════════════════
async def my_purchases(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    purchases = users.get(uid, {}).get("purchases", [])
    if not purchases:
        text = "📦 У вас пока нет покупок."
    else:
        text = "📦 *Ваши покупки:*\n\n" + "\n".join([f"• {p}" for p in purchases])
    await q.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="main")]]),
        parse_mode="Markdown"
    )

# ══════════════════════════════════════
# ГЛАВНОЕ МЕНЮ (callback)
# ══════════════════════════════════════
async def main_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    if uid in users:
        users[uid]["ai_mode"] = False
        users[uid]["chatting_with"] = None
    kb = [
        [InlineKeyboardButton("🛒 Каталог товаров", callback_data="catalog")],
        [InlineKeyboardButton("🤖 ИИ-помощник", callback_data="ai_help")],
        [InlineKeyboardButton("📦 Мои покупки", callback_data="my_purchases")],
        [InlineKeyboardButton("👤 Кабинет продавца", callback_data="seller_cabinet")],
    ]
    await q.edit_message_text(
        "🏠 *Главное меню SmartSalesAI*\n\n"
        "🎮 Лучший маркетплейс цифровых товаров",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

# ══════════════════════════════════════
# ADMIN КОМАНДЫ
# ══════════════════════════════════════
async def activate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    args = ctx.args
    if not args:
        await update.message.reply_text("Использование: /activate USER_ID")
        return
    try:
        target_id = int(args[0])
        ai_active[target_id] = True
        await update.message.reply_text(f"✅ ИИ активирован для пользователя {target_id}")
        try:
            await ctx.bot.send_message(
                target_id,
                "🎉 *ИИ-продавец активирован!*\n\n"
                "Теперь ваш ИИ будет автоматически отвечать покупателям.\n"
                "Настройте промпт в Кабинете продавца → ИИ-продавец.",
                parse_mode="Markdown"
            )
        except:
            pass
    except:
        await update.message.reply_text("❌ Ошибка")

# ══════════════════════════════════════
# ДОБАВЛЕНИЕ ТОВАРА (через сообщения)
# ══════════════════════════════════════
async def handle_add_product(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username or update.effective_user.first_name
    text = update.message.text
    step_data = users[uid].get("adding_product", {})
    step = step_data.get("step")
    
    if step == "name":
        users[uid]["adding_product"]["name"] = text
        users[uid]["adding_product"]["step"] = "category"
        cats = "\n".join([f"{i+1}. {c}" for i, c in enumerate(CATEGORIES)])
        await update.message.reply_text(f"Шаг 2/4: Выберите категорию (напишите номер):\n\n{cats}")
    
    elif step == "category":
        try:
            idx = int(text) - 1
            users[uid]["adding_product"]["category"] = CATEGORIES[idx]
            users[uid]["adding_product"]["step"] = "price"
            await update.message.reply_text("Шаг 3/4: Напишите *цену* в тенге (только число):", parse_mode="Markdown")
        except:
            await update.message.reply_text("❌ Введите номер от 1 до 6")
    
    elif step == "price":
        try:
            price = int(text)
            users[uid]["adding_product"]["price"] = price
            users[uid]["adding_product"]["step"] = "desc"
            await update.message.reply_text("Шаг 4/4: Напишите *описание* товара:", parse_mode="Markdown")
        except:
            await update.message.reply_text("❌ Введите число")
    
    elif step == "desc":
        d = users[uid]["adding_product"]
        new_id = max([p["id"] for p in products], default=0) + 1
        products.append({
            "id": new_id,
            "seller_id": uid,
            "seller": uname,
            "category": d["category"],
            "name": d["name"],
            "price": d["price"],
            "desc": text,
            "delivery": "Моментально"
        })
        users[uid]["adding_product"] = None
        await update.message.reply_text(
            f"✅ *Товар добавлен!*\n\n"
            f"📦 {d['name']}\n"
            f"💰 {d['price']} ₸\n"
            f"🎮 {d['category']}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ В кабинет", callback_data="seller_cabinet")]]),
            parse_mode="Markdown"
        )

# ══════════════════════════════════════
# ROUTER
# ══════════════════════════════════════
async def router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uname = update.effective_user.username or update.effective_user.first_name
    get_user(uid, uname)
    
    if users[uid].get("adding_product"):
        await handle_add_product(update, ctx)
    else:
        await handle_message(update, ctx)

# ══════════════════════════════════════
# MAIN
# ══════════════════════════════════════
def main():
    from data import TELEGRAM_TOKEN
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("activate", activate))
    app.add_handler(CallbackQueryHandler(catalog, pattern="^catalog$"))
    app.add_handler(CallbackQueryHandler(category, pattern="^cat_"))
    app.add_handler(CallbackQueryHandler(product, pattern="^prod_"))
    app.add_handler(CallbackQueryHandler(buy, pattern="^buy_"))
    app.add_handler(CallbackQueryHandler(start_chat, pattern="^chat_"))
    app.add_handler(CallbackQueryHandler(exit_chat, pattern="^exit_chat$"))
    app.add_handler(CallbackQueryHandler(ai_help, pattern="^ai_help$"))
    app.add_handler(CallbackQueryHandler(exit_ai, pattern="^main_exit_ai$"))
    app.add_handler(CallbackQueryHandler(main_menu, pattern="^main$"))
    app.add_handler(CallbackQueryHandler(seller_cabinet, pattern="^seller_cabinet$"))
    app.add_handler(CallbackQueryHandler(ai_seller, pattern="^ai_seller$"))
    app.add_handler(CallbackQueryHandler(paid_ai, pattern="^paid_ai$"))
    app.add_handler(CallbackQueryHandler(set_prompt, pattern="^set_prompt$"))
    app.add_handler(CallbackQueryHandler(my_products, pattern="^my_products$"))
    app.add_handler(CallbackQueryHandler(add_product, pattern="^add_product$"))
    app.add_handler(CallbackQueryHandler(my_purchases, pattern="^my_purchases$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, router))
    
    print("🤖 SmartSalesAI Bot запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
