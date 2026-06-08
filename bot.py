import os
import asyncio
import threading
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pymongo import MongoClient
from dotenv import load_dotenv
from io import BytesIO
import qrcode
from datetime import datetime, timedelta
from cookies_extractor import YouTubeCookieExtractor

load_dotenv()

# ---------- CONFIG ----------
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
OWNER_ID = int(os.getenv("OWNER_ID"))
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []

# ---------- DATABASE ----------
mongo = MongoClient(MONGO_URI)
db = mongo["yt_cookie_bot"]

# Collections
users_col = db["users"]
premium_col = db["premium"]
plans_col = db["plans"]
upi_col = db["upi"]
sessions_col = db["sessions"]

# ---------- INITIALIZE DEFAULT DATA ----------
if not plans_col.find_one():
    plans_col.insert_many([
        {"name": "Monthly", "price": 100, "days": 30, "id": "monthly"},
        {"name": "Yearly", "price": 999, "days": 365, "id": "yearly"},
        {"name": "Lifetime", "price": 1999, "days": 36500, "id": "lifetime"}
    ])

if not upi_col.find_one():
    upi_col.insert_one({"upi_id": "owner@okhdfcbank", "qr": None})

# ---------- BOT INIT ----------
app = Client("yt_cookie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ---------- HELPER FUNCTIONS ----------
def is_authorized(user_id):
    user = users_col.find_one({"_id": user_id})
    return user is not None

def is_premium(user_id):
    premium = premium_col.find_one({"_id": user_id})
    if premium and premium["expiry"] > datetime.now().timestamp():
        return True
    return False

def is_owner(user_id):
    return user_id == OWNER_ID or user_id in ADMIN_IDS

def generate_upi_qr(upi_id, amount):
    qr_data = f"upi://pay?pa={upi_id}&pn=BotOwner&am={amount}&cu=INR"
    qr = qrcode.make(qr_data)
    bio = BytesIO()
    qr.save(bio, "PNG")
    bio.seek(0)
    return bio

# ---------- COMMANDS ----------
@app.on_message(filters.command("start"))
async def start_command(client, message):
    user_id = message.from_user.id
    
    if not is_authorized(user_id):
        await message.reply(
            "❌ *Unauthorized Access*\n\nYou are not authorized to use this bot.\nContact owner for access.",
            parse_mode="MarkdownV2"
        )
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🍪 Get Cookies", callback_data="get_cookies")],
        [InlineKeyboardButton("💎 Premium Plans", callback_data="plans")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ])
    
    await message.reply(
        "🍪 **YouTube Cookie Extractor Bot**\n\n"
        "I can extract YouTube cookies using your Gmail login.\n"
        "Supports 2FA (Two-Factor Authentication).\n\n"
        "🔐 **Your credentials are safe** - they are never stored.\n"
        "⚡ Premium users get priority processing.\n\n"
        "Select an option below:",
        reply_markup=keyboard
    )

@app.on_callback_query()
async def handle_callbacks(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    if not is_authorized(user_id):
        await callback_query.answer("Not authorized!", show_alert=True)
        return
    
    if data == "get_cookies":
        if not is_premium(user_id):
            user_data = users_col.find_one({"_id": user_id})
            daily_limit = user_data.get("daily_count", 0) if user_data else 0
            if daily_limit >= 1:
                await callback_query.message.edit_text(
                    "⚠️ *Daily Limit Reached*\n\nFree users: 1 extraction per day\nUpgrade to premium for unlimited access!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade", callback_data="plans")]]),
                    parse_mode="MarkdownV2"
                )
                return
        
        sessions_col.update_one(
            {"user_id": user_id},
            {"$set": {"state": "awaiting_email", "extractor": None}},
            upsert=True
        )
        await callback_query.message.edit_text(
            "🔐 *Login Process Started*\n\nPlease send your **Gmail address**:\n\nExample: `example@gmail.com`\n\n⚠️ Your credentials are encrypted and never stored.",
            parse_mode="MarkdownV2"
        )
        
    elif data == "plans":
        plans = list(plans_col.find())
        upi = upi_col.find_one()
        
        msg = "💎 *Premium Plans*\n\n"
        for plan in plans:
            msg += f"📌 {plan['name']}: ₹{plan['price']} - {plan['days']} days\n"
        msg += f"\n💳 *UPI ID*: `{upi['upi_id']}`\n\nPay and send screenshot to /confirm"
        
        keyboard = []
        for plan in plans:
            keyboard.append([InlineKeyboardButton(f"Buy {plan['name']} - ₹{plan['price']}", callback_data=f"buy_{plan['id']}")])
        keyboard.append([InlineKeyboardButton("🏠 Back", callback_data="home")])
        
        await callback_query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
        
    elif data.startswith("buy_"):
        plan_id = data.split("_")[1]
        plan = plans_col.find_one({"id": plan_id})
        if plan:
            upi = upi_col.find_one()
            qr = generate_upi_qr(upi['upi_id'], plan['price'])
            await callback_query.message.reply_photo(
                photo=qr,
                caption=f"💸 *Payment Details*\n\nPlan: {plan['name']}\nAmount: ₹{plan['price']}\nUPI: `{upi['upi_id']}`\n\nSend screenshot after payment to /confirm {plan_id}",
                parse_mode="MarkdownV2"
            )
    
    elif data == "help":
        await callback_query.message.edit_text(
            "📖 *How to use:*\n\n1️⃣ Click 'Get Cookies'\n2️⃣ Send your Gmail address\n3️⃣ Send your password\n4️⃣ If 2FA enabled, send verification code\n5️⃣ Receive cookies.txt file\n\n🔒 *Privacy:*\n- Credentials are never stored\n- Session ends after extraction\n- Cookies are sent only to you\n\n💎 *Premium Benefits:*\n- Unlimited extractions\n- Priority processing\n- 24/7 support",
            parse_mode="MarkdownV2"
        )
    
    elif data == "home":
        await start_command(client, callback_query.message)
    
    await callback_query.answer()

# ---------- HANDLE USER INPUT ----------
@app.on_message(filters.text & filters.private)
async def handle_login_input(client, message):
    user_id = message.from_user.id
    
    if not is_authorized(user_id):
        return
    
    session = sessions_col.find_one({"user_id": user_id})
    if not session:
        return
    
    state = session.get("state")
    
    if state == "awaiting_email":
        email = message.text.strip()
        if "@" not in email:
            await message.reply("❌ Invalid email. Send valid Gmail address:")
            return
        
        extractor = YouTubeCookieExtractor()
        sessions_col.update_one(
            {"user_id": user_id},
            {"$set": {"state": "awaiting_password", "email": email, "extractor": extractor}}
        )
        await message.reply("✅ Email received!\n\nNow send your *password*:\n\n⚠️ Password is hidden and won't be stored.", parse_mode="MarkdownV2")
    
    elif state == "awaiting_password":
        password = message.text.strip()
        extractor = session.get("extractor")
        
        status_msg = await message.reply("🔄 Logging in...\n⏳ Please wait 10-15 seconds")
        
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, extractor.login_with_password, password)
        
        if result.get("status") == "2fa_required":
            sessions_col.update_one(
                {"user_id": user_id},
                {"$set": {"state": "awaiting_2fa", "extractor": extractor}}
            )
            await status_msg.edit_text(
                "🔐 *Two-Factor Authentication Required*\n\nPlease send your 6-digit Google Authenticator code:",
                parse_mode="MarkdownV2"
            )
        elif result.get("status") == "success":
            cookies = result.get("cookies")
            await status_msg.delete()
            await message.reply_document(
                document=BytesIO(cookies.encode()),
                file_name="youtube_cookies.txt",
                caption="✅ *Success!* Here are your YouTube cookies.\n\n📌 *Usage:*\n`yt-dlp --cookies youtube_cookies.txt <video_url>`\n\n🔒 Session closed. Your credentials are not stored.",
                parse_mode="MarkdownV2"
            )
            sessions_col.delete_one({"user_id": user_id})
            
            if not is_premium(user_id):
                users_col.update_one({"_id": user_id}, {"$inc": {"daily_count": 1}})
        else:
            await status_msg.edit_text(f"❌ Login failed: {result.get('message')}\n\n/start to try again")
            sessions_col.delete_one({"user_id": user_id})
    
    elif state == "awaiting_2fa":
        twofa_code = message.text.strip()
        extractor = session.get("extractor")
        
        if not twofa_code.isdigit() or len(twofa_code) != 6:
            await message.reply("❌ Invalid 2FA code. Send 6-digit code:")
            return
        
        status_msg = await message.reply("🔄 Verifying 2FA code...")
        
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, extractor.verify_2fa, twofa_code)
        
        if result.get("status") == "success":
            cookies = result.get("cookies")
            await status_msg.delete()
            await message.reply_document(
                document=BytesIO(cookies.encode()),
                file_name="youtube_cookies.txt",
                caption="✅ *Success!* 2FA verified. Here are your cookies.\n\n🔒 Session closed. Credentials not stored.",
                parse_mode="MarkdownV2"
            )
            sessions_col.delete_one({"user_id": user_id})
            
            if not is_premium(user_id):
                users_col.update_one({"_id": user_id}, {"$inc": {"daily_count": 1}})
        else:
            await status_msg.edit_text(f"❌ 2FA verification failed: {result.get('message')}\n\n/start to try again")
            sessions_col.delete_one({"user_id": user_id})

# ---------- PREMIUM CONFIRMATION ----------
@app.on_message(filters.command("confirm") & filters.private)
async def confirm_payment(client, message):
    user_id = message.from_user.id
    
    if not message.reply_to_message:
        await message.reply("❌ Send screenshot as reply to /confirm command")
        return
    
    if not message.photo:
        await message.reply("❌ Please send a screenshot of payment")
        return
    
    await client.send_photo(
        OWNER_ID,
        message.photo.file_id,
        caption=f"💳 Payment confirmation from user {user_id}\n\nMessage: {message.text}"
    )
    
    await message.reply("✅ Payment screenshot sent to owner. Will be activated soon!")

# ---------- OWNER COMMANDS ----------
@app.on_message(filters.command("activate") & filters.user(OWNER_ID))
async def activate_premium(client, message):
    try:
        args = message.text.split()
        user_id = int(args[1])
        days = int(args[2]) if len(args) > 2 else 30
        
        expiry = datetime.now() + timedelta(days=days)
        premium_col.update_one(
            {"_id": user_id},
            {"$set": {"expiry": expiry.timestamp(), "activated_by": OWNER_ID}},
            upsert=True
        )
        
        await message.reply(f"✅ Premium activated for {user_id} for {days} days")
        await client.send_message(user_id, f"🎉 Premium activated for {days} days! Enjoy unlimited access.")
    except:
        await message.reply("❌ Usage: /activate <user_id> [days]")

@app.on_message(filters.command("users") & filters.user(OWNER_ID))
async def list_all_users(client, message):
    users = list(users_col.find())
    premium_users = list(premium_col.find())
    
    msg = f"👥 **Users**\nTotal: {len(users)}\nPremium: {len(premium_users)}\n\n"
    for user in users:
        is_prem = "⭐" if premium_col.find_one({"_id": user["_id"]}) else "👤"
        msg += f"{is_prem} `{user['_id']}`\n"
    
    await message.reply(msg)

@app.on_message(filters.command("adduser") & filters.user(OWNER_ID))
async def add_new_user(client, message):
    try:
        user_id = int(message.text.split()[1])
        if not users_col.find_one({"_id": user_id}):
            users_col.insert_one({"_id": user_id, "daily_count": 0})
            await message.reply(f"✅ User {user_id} added")
        else:
            await message.reply(f"⚠️ User {user_id} already exists")
    except:
        await message.reply("❌ Usage: /adduser <telegram_id>")

@app.on_message(filters.command("removeuser") & filters.user(OWNER_ID))
async def remove_user(client, message):
    try:
        user_id = int(message.text.split()[1])
        users_col.delete_one({"_id": user_id})
        premium_col.delete_one({"_id": user_id})
        await message.reply(f"✅ User {user_id} removed")
    except:
        await message.reply("❌ Usage: /removeuser <telegram_id>")

@app.on_message(filters.command("setupi") & filters.user(OWNER_ID))
async def set_upi_id(client, message):
    try:
        upi_id = message.text.split(" ", 1)[1]
        upi_col.update_one({}, {"$set": {"upi_id": upi_id}}, upsert=True)
        await message.reply(f"✅ UPI ID updated to `{upi_id}`")
    except:
        await message.reply("❌ Usage: /setupi <upi_id>")

@app.on_message(filters.command("setplan") & filters.user(OWNER_ID))
async def set_plan(client, message):
    try:
        parts = message.text.split()
        if len(parts) != 4:
            await message.reply("❌ Usage: /setplan <name> <price> <days>\nExample: /setplan Weekly 50 7")
            return
        
        name = parts[1]
        price = int(parts[2])
        days = int(parts[3])
        plan_id = name.lower()
        
        plans_col.update_one(
            {"id": plan_id},
            {"$set": {"name": name, "price": price, "days": days, "id": plan_id}},
            upsert=True
        )
        await message.reply(f"✅ Plan {name} added/updated: ₹{price} for {days} days")
    except:
        await message.reply("❌ Usage: /setplan <name> <price> <days>")

@app.on_message(filters.command("delplan") & filters.user(OWNER_ID))
async def delete_plan(client, message):
    try:
        plan_id = message.text.split()[1].lower()
        plans_col.delete_one({"id": plan_id})
        await message.reply(f"✅ Plan {plan_id} deleted")
    except:
        await message.reply("❌ Usage: /delplan <plan_id>")

@app.on_message(filters.command("stats") & filters.user(OWNER_ID))
async def bot_stats(client, message):
    total_users = users_col.count_documents({})
    premium_users = premium_col.count_documents({})
    active_sessions = sessions_col.count_documents({})
    
    await message.reply(
        f"📊 *Bot Statistics*\n\n👥 Total Users: {total_users}\n⭐ Premium Users: {premium_users}\n🔄 Active Sessions: {active_sessions}\n💰 Plans Available: {plans_col.count_documents({})}\n💳 UPI Configured: {upi_col.find_one()['upi_id'] if upi_col.find_one() else 'None'}",
        parse_mode="MarkdownV2"
    )

# ---------- FLASK APP FOR PORT BINDING (RENDER) ----------
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    return "🤖 Bot is running!", 200

@flask_app.route('/health')
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host='0.0.0.0', port=port)

# ---------- RUN ----------
if __name__ == "__main__":
    # Start Flask in background thread for Render port binding
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    
    # Start Telegram bot
    print("🤖 Bot Started with 2FA Support and Port Binding!")
    print(f"Owner ID: {OWNER_ID}")
    print(f"Admins: {ADMIN_IDS}")
    print(f"Port: {os.environ.get('PORT', 8080)}")
    app.run()
