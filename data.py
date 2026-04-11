import os
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
ADMIN_ID       = int(os.environ.get("ADMIN_ID", "1234567890"))
YOOMONEY       = "4100118679419062"

# Хранение пользователей в памяти
users = {}

def get_user(uid, uname=""):
    if uid not in users:
        users[uid] = {
            "username": uname,
            "purchases": [],
            "ai_mode": False,
            "chatting_with": None,
            "setting_prompt": False,
            "adding_product": None,
        }
    return users[uid]

# ИИ статус продавцов
ai_active  = {}   # seller_id: True/False
ai_prompts = {}   # seller_id: prompt string

# Активные чаты (ожидание ответа продавца)
pending_chats = {}  # buyer_id: {seller_id, product_id, product_name, time}

# Товары
products = [
    {
        "id": 1,
        "seller_id": ADMIN_ID,
        "seller": "SmartSales",
        "category": "Brawl Stars",
        "name": "1000 Гемов Brawl Stars",
        "price": 3500,
        "desc": "Официальное пополнение через аккаунт. Быстро и безопасно.",
        "delivery": "Моментально"
    },
    {
        "id": 2,
        "seller_id": ADMIN_ID,
        "seller": "SmartSales",
        "category": "Brawl Stars",
        "name": "Brawl Pass Season",
        "price": 2800,
        "desc": "Brawl Pass на 1 сезон. Эксклюзивные награды и скины.",
        "delivery": "Моментально"
    },
    {
        "id": 3,
        "seller_id": ADMIN_ID,
        "seller": "SmartSales",
        "category": "PUBG Mobile",
        "name": "600 UC PUBG Mobile",
        "price": 4200,
        "desc": "Пополнение UC на ваш аккаунт. Нужен только ID игрока.",
        "delivery": "~5 минут"
    },
    {
        "id": 4,
        "seller_id": ADMIN_ID,
        "seller": "SmartSales",
        "category": "PUBG Mobile",
        "name": "1800 UC PUBG Mobile",
        "price": 11500,
        "desc": "Выгодный пакет UC. Экономия 15% по сравнению с магазином.",
        "delivery": "~5 минут"
    },
    {
        "id": 5,
        "seller_id": ADMIN_ID,
        "seller": "SmartSales",
        "category": "Roblox",
        "name": "800 Robux",
        "price": 2500,
        "desc": "Официальное пополнение Robux. Нужен только username.",
        "delivery": "Моментально"
    },
    {
        "id": 6,
        "seller_id": ADMIN_ID,
        "seller": "SmartSales",
        "category": "Steam",
        "name": "Steam Wallet 1000₸",
        "price": 1200,
        "desc": "Пополнение кошелька Steam. Любые игры и DLC.",
        "delivery": "~10 минут"
    },
    {
        "id": 7,
        "seller_id": ADMIN_ID,
        "seller": "SmartSales",
        "category": "CS2",
        "name": "CS2 Prime Status",
        "price": 8900,
        "desc": "Prime статус для CS2. Меньше читеров, лучшие дропы.",
        "delivery": "~30 минут"
    },
    {
        "id": 8,
        "seller_id": ADMIN_ID,
        "seller": "SmartSales",
        "category": "Standoff 2",
        "name": "1000 Голды Standoff 2",
        "price": 1800,
        "desc": "Золото для Standoff 2. Скины, кейсы, операции.",
        "delivery": "Моментально"
    },
]
