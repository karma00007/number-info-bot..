#!/usr/bin/env python3
import os
import sqlite3
import requests
import json
import logging
import traceback
import secrets
import string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
)
from telegram.error import TelegramError

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8953664897:AAH0iiPRVvr9-DevH6QQNdmhVh3stRP393Q")
OWNER_IDS = {6236556853}
_oe = os.environ.get("OWNER_ID", "")
if _oe:
    for x in _oe.split(","):
        if x.strip().isdigit():
            OWNER_IDS.add(int(x.strip()))

DEFAULT_CREDITS = 5
REFERRAL_BONUS = 3
REFERRED_BONUS = 2

# ───────── NEW API (AllPrintHub) ─────────
BASE = "https://api.allprinthub.in/api"
KEY = "30day"

API_PARAMS = {
    "num_info": "num",
    "vehicle_full": "xr",
    "vehicle_to_number": "xr",
    "pan2dob_name": "pan2dob_name",
    "aadhaar2pan": "aadhaar2pan"
}

DB_PATH = "credits.db"
BRAND = "SHIVNSU//-💀👾🙈"
BOT_USERNAME = os.environ.get("BOT_USERNAME", "Aurosarvar_bot")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0"}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        credits INTEGER DEFAULT 5,
        username TEXT, full_name TEXT,
        referred_by INTEGER,
        referrals INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS codes (
        code TEXT PRIMARY KEY,
        credits INTEGER,
        max_uses INTEGER DEFAULT 1,
        used INTEGER DEFAULT 0,
        created_by INTEGER
    )""")
    conn.commit()
    conn.close()

def get_user(uid, username="", full_name="", referred_by=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT credits, referrals, referred_by FROM users WHERE user_id=?", (uid,))
    row = c.fetchone()
    if row is None:
        bonus = DEFAULT_CREDITS
        ref = referred_by
        if ref and ref != uid and ref not in (None, 0):
            bonus = DEFAULT_CREDITS + REFERRED_BONUS
        c.execute(
            "INSERT INTO users (user_id, credits, username, full_name, referred_by, referrals) VALUES (?,?,?,?,?,0)",
            (uid, bonus, username or "", full_name or "", ref)
        )
        if ref and ref != uid:
            c.execute("UPDATE users SET credits = credits + ?, referrals = referrals + 1 WHERE user_id=?",
                      (REFERRAL_BONUS, ref))
        conn.commit()
        credits, referrals = bonus, 0
        ref_by = ref
    else:
        credits, referrals, ref_by = row
        if username or full_name:
            c.execute("UPDATE users SET username=?, full_name=? WHERE user_id=?",
                      (username or "", full_name or "", uid))
            conn.commit()
    conn.close()
    return {"credits": credits, "referrals": referrals or 0, "referred_by": ref_by}

def set_credits(uid, credits):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM users WHERE user_id=?", (uid,))
    if not c.fetchone():
        c.execute("INSERT INTO users (user_id, credits) VALUES (?,?)", (uid, credits))
    else:
        c.execute("UPDATE users SET credits=? WHERE user_id=?", (credits, uid))
    conn.commit()
    conn.close()

def add_credits(uid, amount):
    info = get_user(uid)
    new = info["credits"] + amount
    set_credits(uid, new)
    return new

def use_credit(uid):
    if uid in OWNER_IDS:
        return True
    info = get_user(uid)
    if info["credits"] <= 0:
        return False
    set_credits(uid, info["credits"] - 1)
    return True

def is_owner(uid):
    return uid in OWNER_IDS

def create_code(credits, max_uses, created_by):
    code = "SHIV" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO codes (code, credits, max_uses, used, created_by) VALUES (?,?,?,0,?)",
              (code, credits, max_uses, created_by))
    conn.commit()
    conn.close()
    return code

def redeem_code(uid, code):
    code = code.strip().upper()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT credits, max_uses, used FROM codes WHERE code=?", (code,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False, "Invalid code"
    credits, max_uses, used = row
    if used >= max_uses:
        conn.close()
        return False, "Code already used up"
    c.execute("UPDATE codes SET used = used + 1 WHERE code=?", (code,))
    conn.commit()
    conn.close()
    new = add_credits(uid, credits)
    return True, f"+{credits} credits! Balance: {new}"

def find_by_username(username: str):
    username = username.lstrip("@").lower()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, credits, username, full_name, referrals FROM users WHERE lower(username)=?", (username,))
    row = c.fetchone()
    conn.close()
    return row

def list_users(limit=20):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, credits, username, full_name, referrals FROM users ORDER BY user_id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

def api_get(endpoint, value):
    try:
        param_name = API_PARAMS.get(endpoint, "query")
        url = f"{BASE}?={endpoint}&key={KEY}&{param_name}={value}"
        logger.info(f"API: {url}")
        r = requests.get(url, headers=HEADERS, timeout=30)
        
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}"}
            
        text = r.text.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return r.json()
            except Exception:
                return {"report": text[:3500]}
        return {"report": text[:3500]}
    except Exception as e:
        return {"error": str(e)}

def format_result(data):
    if not data:
        return "❌ No data found!"
    if isinstance(data, dict) and data.get("error"):
        return f"❌ {data.get('error')}"
    if isinstance(data, dict) and data.get("report"):
        rep = data["report"]
        if len(rep) > 3500:
            rep = rep[:3500] + "\n... (truncated)"
        return f"<pre>{rep}</pre>\n\n⚡ Powered by <b>{BRAND}</b>"
    try:
        if isinstance(data, dict):
            def clean(obj):
                if isinstance(obj, dict):
                    for k in list(obj.keys()):
                        if "powered" in k.lower() or "ronak" in k.lower():
                            obj[k] = BRAND
                        else:
                            clean(obj[k])
                elif isinstance(obj, list):
                    for i in obj:
                        clean(i)
            clean(data)
        text = json.dumps(data, indent=2, ensure_ascii=False)
        text = text.replace("@Ronak_api", BRAND).replace("Ronak_api", BRAND)
        if len(text) > 3200:
            text = text[:3200] + "\n... (truncated)"
        return f"<pre>{text}</pre>\n\n⚡ Powered by <b>{BRAND}</b>"
    except Exception:
        return str(data)[:3200]

def main_menu_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📱 Phone", callback_data="mode:num_info"),
            InlineKeyboardButton("🪪 Aadhaar→PAN", callback_data="mode:aadhaar2pan"),
        ],
        [
            InlineKeyboardButton("💳 PAN→DOB", callback_data="mode:pan2dob_name"),
            InlineKeyboardButton("🚗 Vehicle Full", callback_data="mode:vehicle_full"),
        ],
        [
            InlineKeyboardButton("🚘 Veh→Num", callback_data="mode:vehicle_to_number"),
            InlineKeyboardButton("💰 Credits", callback_data="credits"),
        ],
        [
            InlineKeyboardButton("🔗 Refer & Earn", callback_data="refer"),
            InlineKeyboardButton("🎟 Redeem Code", callback_data="redeem"),
        ],
        [
            InlineKeyboardButton("👑 Owner", callback_data="owner"),
            InlineKeyboardButton("ℹ️ Bot Help", callback_data="help"),
        ],
        [
            InlineKeyboardButton("👤 My Account", callback_data="account"),
        ],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    referred_by = None
    if context.args:
        arg = context.args[0]
        if arg.startswith("ref") and arg[3:].isdigit():
            referred_by = int(arg[3:])
    info = get_user(user.id, user.username or "", user.full_name or "", referred_by)
    context.user_data["mode"] = None
    context.user_data.pop("await_redeem", None)

    if is_owner(user.id):
        credit_line = "👑 <b>Owner — Unlimited credits</b>"
    else:
        credit_line = f"💰 Credits: <b>{info['credits']}</b>"

    text = (
        f"💀 <b>OSINT INFO BOT</b>\n\n"
        f"{credit_line}\n\n"
        f"CHAL RE RNDI KE OPTION CHOOSE KAR 👇\n\n"
        f"⚡ Powered by <b>{BRAND}</b>"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu_kb())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    info = get_user(user.id, user.username or "", user.full_name or "")

    if data == "menu":
        await query.message.reply_text("💀 Menu:", reply_markup=main_menu_kb())
        return

    if data == "credits":
        if is_owner(user.id):
            await query.message.reply_text("👑 Owner — Unlimited credits")
        else:
            await query.message.reply_text(f"💰 Your credits: <b>{info['credits']}</b>", parse_mode="HTML")
        return

    if data == "refer":
        link = f"https://t.me/{BOT_USERNAME}?start=ref{user.id}"
        text = (
            f"🔗 <b>Refer & Earn</b>\n\n"
            f"Apna link share karo:\n<code>{link}</code>\n\n"
            f"✅ Har successful referral pe <b>+{REFERRAL_BONUS}</b> credits\n"
            f"✅ Naye user ko <b>+{REFERRED_BONUS}</b> bonus\n\n"
            f"📊 Your referrals: <b>{info['referrals']}</b>"
        )
        await query.message.reply_text(text, parse_mode="HTML")
        return

    if data == "redeem":
        context.user_data["await_redeem"] = True
        await query.message.reply_text("🎟 Redeem code bhejo:")
        return

    if data == "owner":
        text = (
            f"👑 <b>Owner</b>\n\n"
            f"Brand: <b>{BRAND}</b>\n"
            f"Telegram: @Auroo188\n"
            f"ID: <code>6236556853</code>\n\n"
            f"Credits / help ke liye contact: @Auroo188"
        )
        await query.message.reply_text(text, parse_mode="HTML")
        return

    if data == "help":
        text = (
            "ℹ️ <b>Bot Help</b>\n\n"
            "📱 Phone — 10 digit mobile\n"
            "🪪 Aadhaar→PAN — 12 digit Aadhaar\n"
            "💳 PAN→DOB — e.g. ABCDE1234F\n"
            "🚗 Vehicle Full — e.g. KL41V3504\n"
            "🚘 Veh→Num — e.g. KL41V3504\n\n"
            "🔗 Refer — link share karke credits kamao\n"
            "🎟 Redeem — code se credits lo\n\n"
            f"<b>Owner commands:</b>\n"
            f"/addcredit ID AMOUNT\n"
            f"/setcredit ID AMOUNT\n"
            f"/checkcredit ID\n"
            f"/gencode CREDITS MAX_USES\n"
            f"/find @username\n"
            f"/users [limit]\n\n"
            f"⚡ {BRAND}"
        )
        await query.message.reply_text(text, parse_mode="HTML")
        return

    if data == "account":
        uname = f"@{user.username}" if user.username else "—"
        if is_owner(user.id):
            bal = "Unlimited ∞"
        else:
            bal = str(info["credits"])
        text = (
            f"👤 <b>My Account</b>\n\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"👤 Username: {uname}\n"
            f"📛 Name: {user.full_name or '—'}\n"
            f"💰 Credits: <b>{bal}</b>\n"
            f"📊 Referrals: <b>{info['referrals']}</b>\n\n"
            f"⚡ {BRAND}"
        )
        await query.message.reply_text(text, parse_mode="HTML")
        return

    if data.startswith("mode:"):
        cmd = data.split(":", 1)[1]
        context.user_data["mode"] = cmd
        prompts = {
            "num_info":         "📱 10 digit mobile number bhejo:",
            "aadhaar2pan":      "🪪 12 digit Aadhaar bhejo:",
            "pan2dob_name":     "💳 PAN bhejo (e.g. CNKPK7230D):",
            "vehicle_full":     "🚗 Vehicle number bhejo (e.g. KL41V3504):",
            "vehicle_to_number":"🚘 Vehicle number bhejo (e.g. KL41V3504):",
        }
        await query.message.reply_text(
            f"🔍 {prompts.get(cmd, 'Value bhejo:')}\n\n⚡ Powered by <b>{BRAND}</b>",
            parse_mode="HTML"
        )

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    tag = "✅ Owner" if is_owner(uid) else "User"
    await update.message.reply_text(f"🆔 <code>{uid}</code>\n{tag}", parse_mode="HTML")

async def addcredit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return await update.message.reply_text("❌ Owner only")
    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /addcredit USER_ID AMOUNT")
    try:
        t, a = int(context.args[0]), int(context.args[1])
    except ValueError:
        return await update.message.reply_text("❌ Invalid")
    bal = add_credits(t, a)
    await update.message.reply_text(f"✅ <code>{t}</code> +{a}\nBalance: <b>{bal}</b>", parse_mode="HTML")

async def setcredit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return await update.message.reply_text("❌ Owner only")
    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /setcredit USER_ID AMOUNT")
    try:
        t, a = int(context.args[0]), int(context.args[1])
    except ValueError:
        return await update.message.reply_text("❌ Invalid")
    set_credits(t, a)
    await update.message.reply_text(f"✅ <code>{t}</code> = <b>{a}</b>", parse_mode="HTML")

async def checkcredit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return await update.message.reply_text("❌ Owner only")
    if not context.args:
        return await update.message.reply_text("Usage: /checkcredit USER_ID")
    try:
        t = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("❌ Invalid")
    info = get_user(t)
    await update.message.reply_text(
        f"<code>{t}</code>\nCredits: <b>{info['credits']}</b>\nReferrals: {info['referrals']}",
        parse_mode="HTML"
    )

async def gencode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return await update.message.reply_text("❌ Owner only")
    if len(context.args) < 1:
        return await update.message.reply_text("Usage: /gencode CREDITS [MAX_USES]\nExample: /gencode 10 5")
    try:
        credits = int(context.args[0])
        max_uses = int(context.args[1]) if len(context.args) > 1 else 1
    except ValueError:
        return await update.message.reply_text("❌ Invalid")
    code = create_code(credits, max_uses, update.effective_user.id)
    await update.message.reply_text(
        f"🎟 Code: <code>{code}</code>\nCredits: {credits}\nMax uses: {max_uses}",
        parse_mode="HTML"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    get_user(user.id, user.username or "", user.full_name or "")

    if context.user_data.get("await_redeem"):
        context.user_data["await_redeem"] = False
        ok, msg = redeem_code(user.id, text)
        icon = "✅" if ok else "❌"
        await update.message.reply_text(f"{icon} {msg}")
        return

    mode = context.user_data.get("mode")
    clean = text.replace(" ", "").replace("+91", "").replace("-", "")

    if clean.isdigit() and len(clean) == 10 and not mode:
        if not use_credit(user.id):
            return await update.message.reply_text(f"❌ Credits khatam! Free: {DEFAULT_CREDITS}")
        msg = await update.message.reply_text("⏳ Searching...")
        data = api_get("num_info", clean)
        left = "∞" if is_owner(user.id) else str(get_user(user.id)["credits"])
        result = format_result(data) + f"\n💰 Left: <b>{left}</b>"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu")]])
        try:
            await msg.edit_text(result, parse_mode="HTML", reply_markup=kb)
        except TelegramError:
            await msg.edit_text(str(data)[:4000], reply_markup=kb)
        return

    if mode:
        if not use_credit(user.id):
            context.user_data["mode"] = None
            return await update.message.reply_text("❌ Credits khatam!")
        value = text.strip()

        if mode in ("pan2dob_name", "vehicle_full", "vehicle_to_number"):
            value = value.upper().replace(" ", "")
        elif mode == "aadhaar2pan":
            value = value.replace(" ", "").replace("-", "")
        elif mode == "num_info":
            value = value.replace(" ", "").replace("+91", "").replace("-", "")

        msg = await update.message.reply_text("⏳ Searching...")
        data = api_get(mode, value)
        context.user_data["mode"] = None
        left = "∞" if is_owner(user.id) else str(get_user(user.id)["credits"])
        result = format_result(data) + f"\n💰 Left: <b>{left}</b>"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="menu")]])
        try:
            await msg.edit_text(result, parse_mode="HTML", reply_markup=kb)
        except TelegramError:
            await msg.edit_text(str(data)[:4000], reply_markup=kb)
        return

    await update.message.reply_text("CHAL RE RNDI KE OPTION CHOOSE KAR 👇", reply_markup=main_menu_kb())

async def error_handler(update, context):
    logger.error(f"{context.error}\n{traceback.format_exc()}")

async def find_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return await update.message.reply_text("❌ Owner only")
    if not context.args:
        return await update.message.reply_text("Usage: /find @username\nExample: /find @Auroo188")
    uname = context.args[0]
    row = find_by_username(uname)
    if not row:
        return await update.message.reply_text(
            f"❌ @{uname.lstrip('@')} database mein nahi mila.\n"
            "Pehle us user ne bot pe /start kiya hona chahiye."
        )
    uid, credits, username, full_name, referrals = row
    await update.message.reply_text(
        f"👤 <b>User found</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"Username: @{username or '—'}\n"
        f"Name: {full_name or '—'}\n"
        f"💰 Credits: <b>{credits}</b>\n"
        f"📊 Referrals: {referrals or 0}",
        parse_mode="HTML"
    )

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return await update.message.reply_text("❌ Owner only")
    limit = 50
    if context.args and context.args[0].isdigit():
        limit = min(int(context.args[0]), 100)
    rows = list_users(limit)
    if not rows:
        return await update.message.reply_text("Abhi koi user nahi (kisi ne /start nahi kiya).")
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    lines = [f"👥 <b>Bot users</b> (Total: {total}, Showing: {len(rows)})\n"]
    for row in rows:
        uid, credits, username, full_name, referrals = row
        uname = f"@{username}" if username else "—"
        lines.append(f"• <code>{uid}</code> | {uname} | Credits: {credits} | Ref: {referrals or 0}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", myid))
    app.add_handler(CommandHandler("addcredit", addcredit_cmd))
    app.add_handler(CommandHandler("setcredit", setcredit_cmd))
    app.add_handler(CommandHandler("checkcredit", checkcredit_cmd))
    app.add_handler(CommandHandler("gencode", gencode_cmd))
    app.add_handler(CommandHandler("find", find_cmd))
    app.add_handler(CommandHandler("users", users_cmd))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    logger.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()