import os
import random
import asyncio
import sqlite3
import requests
import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from deep_translator import GoogleTranslator

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# NEW BUY ALERT FEATURE
from buy_alert import start_buy_alert_monitor

MAGICEDEN_COLLECTION = "suolala_"
MAGICEDEN_LIST_URL = "https://api-mainnet.magiceden.dev/v2/collections/{}/listings?offset=0&limit=100"

# ===== BOT TOKEN =====
TOKEN = os.getenv("BOT_TOKEN")

# ===== OPENROUTER (IMAGE GENERATION) =====
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Cooldown & lock system
user_last_generation = {}   # {user_id: timestamp}
is_generating = False
GENERATE_COOLDOWN_SECONDS = 600  # 10 minutes per user

# Fixed character prefix — always the meme girl
MEME_GIRL_PREFIX = (
    "chibi 3D anime girl, long straight dark blue-black hair, "
    "purple to teal gradient zip-up hoodie with letter S on chest, "
    "teal jogger pants, teal sneakers, brown eyes, cute chubby face, "
    "3D render clay style, white background, "
)


# ===== TIMEZONE =====
CHINA_TZ = ZoneInfo("Asia/Shanghai")

# ===== MEMORY (FIXED GM/GN) =====
KNOWN_CHATS_FILE = "known_chats.txt"
KNOWN_CHATS = set()
LAST_GM_DATE = None
LAST_GN_DATE = None
USED_MOTIVATIONS = {}

# Load chat IDs safely (handles empty lines)
if os.path.exists(KNOWN_CHATS_FILE):
    try:
        with open(KNOWN_CHATS_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        KNOWN_CHATS.add(int(line))
                    except ValueError:
                        pass
        print(f"[STARTUP] Loaded {len(KNOWN_CHATS)} chat ID(s) from {KNOWN_CHATS_FILE}")
    except Exception as e:
        print(f"[STARTUP] Error loading chat IDs: {e}")

# ===== DATABASE =====
db = sqlite3.connect("weekly_stats.db", check_same_thread=False)
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS stats (
    user_id INTEGER,
    chat_id INTEGER,
    year_week TEXT,
    count INTEGER,
    PRIMARY KEY (user_id, chat_id, year_week)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT
)
""")
db.commit()

def current_week():
    y, w, _ = datetime.utcnow().isocalendar()
    return f"{y}-W{w:02d}"

# ===== DELETE HELPER =====
async def delete_after_delay(message, delay=300):
    """Delete a message after specified delay in seconds"""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception as e:
        print(f"Failed to delete message: {e}")
        pass  # Message might already be deleted or bot lacks permission

# ===== SAVE CHAT (FIXED) =====
def remember_chat(update: Update):
    if update and update.effective_chat:
        cid = update.effective_chat.id
        if cid not in KNOWN_CHATS:
            KNOWN_CHATS.add(cid)
            with open(KNOWN_CHATS_FILE, "a") as f:
                f.write(str(cid) + "\n")

# ===== QR HELPER =====
async def send_qr_if_exists(update, name):
    path = f"qrcodes/{name}.jpg"
    if os.path.exists(path):
        await update.message.reply_photo(photo=open(path, "rb"))

# ===== TRANSLATE =====
async def translate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❗ Reply to a message and type /translate")
        return

    original = update.message.reply_to_message.text
    if not original:
        await update.message.reply_text("❗ Nothing to translate")
        return

    try:
        translated = GoogleTranslator(source="auto", target="en").translate(original)
        flag = "🇬🇧"

        if translated.strip().lower() == original.strip().lower():
            translated = GoogleTranslator(source="auto", target="zh-CN").translate(original)
            flag = "🇨🇳"

        sent = await update.message.reply_text(f"{flag} Translation:\n{translated}")
        await asyncio.sleep(40)
        await sent.delete()
    except:
        await update.message.reply_text("❌ Translation failed")

# ===== MESSAGE TRACKER =====
async def track_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.message.from_user.is_bot:
        return
    if update.effective_chat.type == "private":
        return

    user = update.effective_user

    cur.execute("""
    INSERT INTO users (user_id, username, first_name)
    VALUES (?, ?, ?)
    ON CONFLICT(user_id)
    DO UPDATE SET username=excluded.username, first_name=excluded.first_name
    """, (user.id, user.username, user.first_name))

    cur.execute("""
    INSERT INTO stats (user_id, chat_id, year_week, count)
    VALUES (?, ?, ?, 1)
    ON CONFLICT(user_id, chat_id, year_week)
    DO UPDATE SET count = count + 1
    """, (user.id, update.effective_chat.id, current_week()))

    db.commit()

# ===== BASIC COMMANDS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_chat(update)
    await update.message.reply_text(
        "🤖 SUOLALA Bot 🐉\n"
        "Official Solana China meme coin 🇨🇳🔥\n\n"
        "Commands:\n"
        "/price /chart /buy /memes /stickers\n"
        "/x /community /nft /contract /website /rules\n"
        "/suolala /motivate /count /top /randomnft /translate\n"
        "/generate <idea> — AI meme image 🎨"
    )

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_chat(update)
    await update.message.reply_text(
        "💰 SUOLALA Price\n"
        "https://dexscreener.com/solana/79Qaq5b1JfC8bFuXkAvXTR67fRPmMjMVNkEA3bb8bLzi"
    )
    await send_qr_if_exists(update, "price")

async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_chat(update)
    await update.message.reply_text(
        "📈 SUOLALA Chart\n"
        "https://dexscreener.com/solana/79Qaq5b1JfC8bFuXkAvXTR67fRPmMjMVNkEA3bb8bLzi"
    )
    await send_qr_if_exists(update, "chart")

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_chat(update)

    await context.bot.send_animation(
        chat_id=update.effective_chat.id,
        animation=open("buy.gif", "rb"),
        caption=
    "╔══════════════════════════════╗\n"
    "        🚀 HOW TO BUY SUOLALA\n"
    "╚══════════════════════════════╝\n\n"
    "👛 ① Create a Phantom Wallet\n"
    "💰 ② Buy SOL & fund your wallet\n"
    "🪐 ③ Open Jupiter Exchange\n"
    "🔗 https://jup.ag\n"
    "📋 ④ Paste the SUOLALA Contract\n"
    "🔁 ⑤ Swap SOL ➜ SUOLALA\n\n"
    "═══════════════════════════════\n"
    "📜 OFFICIAL CONTRACT ADDRESS\n"
    "CY1P83KnKwFYostvjQcoR2HJLyEJWRBRaVQmYyyD3cR8\n"
    "═══════════════════════════════"
    )
    await send_qr_if_exists(update, "buy")

async def memes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_chat(update)
    await update.message.reply_text("😂 Memes\nhttps://t.me/suolala_memes")
    await send_qr_if_exists(update, "memes")

async def stickers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_chat(update)
    await update.message.reply_text(
        "🧧 Stickers\n"
        "Static: https://t.me/addstickers/suolalastickers\n"
        "Animated: https://t.me/addstickers/Suolala_cto\n"
        "Animated: https://t.me/addstickers/suolalaanimatedstickers"
    )

async def x(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_chat(update)
    await update.message.reply_text("🐦 X\nhttps://x.com/suolalax")
    await send_qr_if_exists(update, "x")


async def community(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_chat(update)
    await update.message.reply_text(
        "👥 Community\nhttps://twitter.com/i/communities/1980324795851186529"
    )
    await send_qr_if_exists(update, "community")
    
async def nft(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_chat(update)

    caption = (
        "🚀 索拉拉 | Suolala NFT is LIVE\n\n"
        "索拉拉 is the premier Chinese ticker on Solana, inspired by Lily Liu "
        "and built by real builders 🔨💜\n\n"
        "💡 CTO Project\n"
        "❌ No VC\n"
        "❌ No whales\n"
        "✅ Community-driven\n\n"
        "After months where many memecoins died, 索拉拉 is still alive — "
        "powered purely by belief and builders.\n\n"
        "🎨 Why Suolala NFT?\n"
        "• Strengthen community unity\n"
        "• Increase brand visibility\n"
        "• 📢 Burn 索拉拉 tokens\n\n"
        "• 🔥 All mint tokens are burned\n"
        "🔗 BUY here:\n"
        "https://magiceden.io/marketplace/suolala_\n\n"
        "🏃 让我们奔跑吧索拉拉们\n"
        "Built by builders. Alive by belief."
    )

    with open("nft.jpg", "rb") as photo:
        await update.message.reply_photo(
            photo=photo,
            caption=caption
        )

async def contract(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_chat(update)
    await update.message.reply_text(
        "📜 Contract\nCY1P83KnKwFYostvjQcoR2HJLyEJWRBRaVQmYyyD3cR8"
    )
    await send_qr_if_exists(update, "contract")

async def website(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_chat(update)
    
    # Check if newweb.png exists
    if os.path.exists("newweb.png"):
        with open("newweb.png", "rb") as photo:
            await update.message.reply_photo(
                photo=photo,
                caption="🌐 SUOLALA NEW WEBSITE\nhttps://suolala.netlify.app/"
            )
    else:
        # Send text only if image doesn't exist
        await update.message.reply_text(
            "🌐 SUOLALA NEW WEBSITE\nhttps://suolala.netlify.app/"
        )

async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_chat(update)
    await update.message.reply_text(
        "📌 Rules\nNo spam | No scams | No fake links | Respect all"
    )

# ===== RANDOM IMAGE =====
async def suolala(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_chat(update)
    IMAGE_DIR = "girls"
    img = random.choice([f for f in os.listdir(IMAGE_DIR) if f.lower().endswith(("jpg","png","jpeg"))])
    await update.message.reply_photo(open(f"{IMAGE_DIR}/{img}", "rb"))

# ===== MOTIVATIONS (ALL 70) =====
MOTIVATIONS = [
    "🐉 SUOLALA is built by those who stay 💎",
    "💎 Holding SUOLALA means trusting your own vision 🔮",
    "🔥 Strong hands don't look for exits — they build 🛡️",
    "🚀 SUOLALA moves when patience beats panic ⏳",
    "🧠 Calm minds protect SUOLALA better than hype 🧘",
    "💪 If holding was easy, everyone would own SUOLALA 🐉",
    "⏰ Time rewards SUOLALA believers 💎",
    "🌊 Noise fades. SUOLALA remains 🛡️",
    "🐲 SUOLALA doesn't rush — it rises ⬆️",
    "📈 Price moves fast. Conviction lasts longer 🧠",
    "💎 Staying is harder than buying — that's the edge ⚔️",
    "🔥 Belief turns SUOLALA from meme to movement 🚀",
    "🛡️ Calm holders build lasting SUOLALA value 💎",
    "⏳ Staying power beats timing luck 🍀",
    "🐉 Those who stay define SUOLALA 💎",
    "🧠 Discipline keeps SUOLALA strong 🎯",
    "🚀 Growth rewards patience in SUOLALA 🌱",
    "💪 Weak hands react. Strong hands remain 🛡️",
    "🐲 SUOLALA stands firm through noise 🔕",
    "💎 Conviction builds SUOLALA over time ⏰",
    "🧠 Emotion exits early. Discipline stays longer 🔒",
    "🚀 SUOLALA isn't loud — it's persistent ⏳",
    "🐲 Those who stay early shape what comes later 🔮",
    "📈 Growth rewards those who don't rush it 🧘",
    "💪 Holding SUOLALA is choosing conviction over comfort 🔥",
    "🔥 Real progress looks boring at first 🌱",
    "🛡️ Calm holders build lasting value 💎",
    "⏳ Time tests everyone. SUOLALA holders pass 🏆",
    "🐉 SUOLALA survives because belief survives 🔋",
    "💎 Strong hands are made, not found ⚒️",
    "🧠 Focus beats fear every cycle 🔁",
    "🚀 SUOLALA grows when patience wins 🌱",
    "🔥 Community matters more than charts 📊",
    "🛡️ Stability is a hidden advantage 🎯",
    "💪 SUOLALA is held by those who understand waiting ⏰",
    "🐲 Memes move fast. Conviction moves further 🚀",
    "💎 SUOLALA is built on belief, not noise 🔕",
    "🧠 The strongest move is often doing nothing 🧘",
    "🔥 Patience separates SUOLALA holders from tourists 🧭",
    "💎 Long vision gives SUOLALA real strength 🧠",
    "🐉 Real believers stay when charts are quiet 🌊",
    "🚀 SUOLALA grows through time, not hype ⏳",
    "🛡️ Calm strategy protects SUOLALA value 💎",
    "💪 Staying disciplined builds SUOLALA slowly 🧱",
    "⏰ Time is the ally of SUOLALA holders 💎",
    "🔥 Conviction outlasts volatility in SUOLALA 🌊",
    "🧠 Strong mindset keeps SUOLALA steady 🎯",
    "🐲 Those who wait patiently shape SUOLALA's future 💎",
    "🐉 SUOLALA is built by patience, not pressure 💎",
    "💎 Those who believe early give SUOLALA its strength 🔥",
    "🚀 SUOLALA grows when holders stay focused ⏳",
    "🧠 Calm thinking keeps SUOLALA moving forward 🎯",
    "💪 SUOLALA rewards those who don't rush 🛡️",
    "🔥 Real support is holding, not talking 🐉",
    "⏰ Time and belief shape SUOLALA together 💎",
    "🛡️ Strong holders protect SUOLALA's future 🔒",
    "🐲 SUOLALA stands firm when noise gets loud 🌊",
    "💎 Trust the process — SUOLALA is still building 🧱",
    "🚀 SUOLALA moves best with steady hands ⏳",
    "🧠 Discipline today strengthens SUOLALA tomorrow 💎",
    "🔥 Community belief keeps SUOLALA alive 🐉",
    "💪 Holding SUOLALA means trusting your choice 🛡️",
    "⏰ Long vision gives SUOLALA real value 💎",
    "🐲 SUOLALA grows quietly before big moves 🔥",
    "🛡️ Calm holders build lasting SUOLALA strength 💎",
    "🚀 SUOLALA is a journey, not a quick flip ⏳",
    "💎 Staying consistent builds SUOLALA confidence 🧠",
    "🐉 Those who stay patient shape SUOLALA's path 💎",
]

async def motivate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_chat(update)
    chat_id = update.effective_chat.id
    used = USED_MOTIVATIONS.setdefault(chat_id, set())

    if len(used) >= len(MOTIVATIONS):
        used.clear()

    idx = random.choice([i for i in range(len(MOTIVATIONS)) if i not in used])
    used.add(idx)
    await update.message.reply_text(MOTIVATIONS[idx])

# ===== /count =====
async def count_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur.execute(
        "SELECT count FROM stats WHERE user_id=? AND chat_id=? AND year_week=?",
        (update.effective_user.id, update.effective_chat.id, current_week())
    )
    row = cur.fetchone()
    await update.message.reply_text(f"📊 Your weekly messages: {row[0] if row else 0}")

# ===== /top =====
async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur.execute("""
    SELECT s.count, u.username, u.first_name
    FROM stats s
    JOIN users u ON s.user_id = u.user_id
    WHERE s.chat_id=? AND s.year_week=?
    ORDER BY s.count DESC LIMIT 5
    """, (update.effective_chat.id, current_week()))

    rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("No activity yet.")
        return

    medals = ["🥇","🥈","🥉","🏅","🏅"]
    text = "🏆 Weekly Top Chatters 🏆\n\n"
    for i, (count, username, first_name) in enumerate(rows):
        name = f"@{username}" if username else first_name
        text += f"{medals[i]} {name} — {count}\n"
    await update.message.reply_text(text)

# ===== WELCOME (FIXED) =====
async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.new_chat_members:
        return

    # Remember this chat
    remember_chat(update)
    
    chat_id = update.effective_chat.id
    
    for user in update.message.new_chat_members:
        if user.is_bot:  # Skip if the new member is a bot
            continue
            
        name = user.first_name
        mention = f"[{name}](tg://user?id={user.id})"
        text = (
            f"🎉 Welcome {mention}!\n\n"
            "🐉 **Welcome to 索拉拉 SUOLALA CTO**\n"
            "💎 Stay strong. Stay patient."
        )

        try:
            # First try to send animation if welcome.gif exists
            if os.path.exists("welcome.gif"):
                with open("welcome.gif", "rb") as gif:
                    welcome_msg = await context.bot.send_animation(
                        chat_id=chat_id,
                        animation=gif,
                        caption=text,
                        parse_mode="Markdown"
                    )
                    # Schedule deletion after 5 minutes (300 seconds)
                    asyncio.create_task(delete_after_delay(welcome_msg, 300))
            else:
                # If no GIF, send text message
                welcome_msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="Markdown"
                )
                # Schedule deletion after 5 minutes
                asyncio.create_task(delete_after_delay(welcome_msg, 300))
                
        except Exception as e:
            print(f"Welcome message error: {e}")
            try:
                # Fallback to text only
                welcome_msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🎉 Welcome {name}!\n\n🐉 Welcome to 索拉拉 SUOLALA CTO\n💎 Stay strong. Stay patient."
                )
                asyncio.create_task(delete_after_delay(welcome_msg, 300))
            except Exception as e2:
                print(f"Even fallback welcome failed: {e2}")

# ===== GM / GN TASK (FIXED) =====
async def gm_gn_task(application):
    global LAST_GM_DATE, LAST_GN_DATE
    while True:
        now = datetime.now(CHINA_TZ)
        today = now.date()

        if 11 <= now.hour < 12 and LAST_GM_DATE != today:
            for cid in KNOWN_CHATS:
                try:
                    await application.bot.send_animation(cid, open("gm.gif", "rb"))
                except Exception as e:
                    print(f"GM error in chat {cid}: {e}")
            LAST_GM_DATE = today

        if 23 <= now.hour < 24 and LAST_GN_DATE != today:
            for cid in KNOWN_CHATS:
                try:
                    await application.bot.send_animation(cid, open("gn.gif", "rb"))
                except Exception as e:
                    print(f"GN error in chat {cid}: {e}")
            LAST_GN_DATE = today

        await asyncio.sleep(60)

# Flag to prevent duplicate background task startup
_background_started = False


async def post_init(app):
    # Delete any existing webhook and wait for old polling sessions to timeout
    print("[STARTUP] Clearing webhook and waiting for old sessions to timeout...")
    await app.bot.delete_webhook(drop_pending_updates=True)
    
    # Wait for any existing polling session to timeout (Telegram timeout is ~30s)
    await asyncio.sleep(35)
    print("[STARTUP] Ready for polling")
    
    # Schedule background tasks using pure asyncio (no JobQueue required)
    # This task will wait for polling to stabilize, then start background work
    asyncio.create_task(delayed_background_startup(app))


async def delayed_background_startup(app):
    """Start all background tasks after polling is stable - runs only ONCE"""
    global _background_started
    
    # Prevent duplicate startup
    if _background_started:
        print("[BACKGROUND] Already started, skipping duplicate call")
        return
    _background_started = True
    
    # Wait for polling to fully initialize
    await asyncio.sleep(5)
    
    # Start GM/GN task
    asyncio.create_task(gm_gn_task(app))
    print("[BACKGROUND] GM/GN task started")
    
    # Start buy alert monitor
    await start_buy_alert_monitor_safe(app)


async def start_buy_alert_monitor_safe(app):
    """Start buy alert monitor only if chat IDs exist, prevent duplicate starts"""
    # Reload chat IDs from file
    chat_ids = set()
    if os.path.exists(KNOWN_CHATS_FILE):
        try:
            with open(KNOWN_CHATS_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            chat_ids.add(int(line))
                        except ValueError:
                            pass
        except Exception as e:
            print(f"[BUY ALERT] Error reading chat IDs: {e}")
    
    if chat_ids:
        await start_buy_alert_monitor(app.bot, list(chat_ids))
        print(f"[BUY ALERT] Monitor started for {len(chat_ids)} chat(s)")
    else:
        print("[BUY ALERT] No chat IDs found, monitor not started")


# ===== /generate =====
async def generate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_generating

    remember_chat(update)

    # STEP 0 — Group-only restriction
    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "❌ Image generation only works in group. Please use this bot in a group."
        )
        return

    user = update.effective_user
    user_id = user.id
    username = f"@{user.username}" if user.username else str(user_id)

    # STEP 1 — Global generation lock
    if is_generating:
        await update.message.reply_text(
            "⚠️ Another image is currently generating. Try again in a few minutes."
        )
        return

    # STEP 2 — Per-user 10-minute cooldown
    now = time.time()
    last_time = user_last_generation.get(user_id)
    if last_time is not None:
        diff = now - last_time
        if diff < GENERATE_COOLDOWN_SECONDS:
            remaining = GENERATE_COOLDOWN_SECONDS - diff
            minutes = math.ceil(remaining / 60)
            await update.message.reply_text(
                f"{username} wait {minutes} minute{'s' if minutes != 1 else ''} before next image"
            )
            return

    if not context.args:
        await update.message.reply_text(
            "❗ Usage: /generate <your idea>\n"
            "Example: /generate riding a bull 🐂"
        )
        return

    user_prompt = " ".join(context.args)
    full_prompt = MEME_GIRL_PREFIX + user_prompt

    # STEP 3 — Acquire generation lock
    is_generating = True

    thinking_msg = await update.message.reply_text("🎨 Generating image...")

    try:
        import base64
        from io import BytesIO

        # STEP 4 — Generate image via OpenRouter
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "sourceful/riverflow-v2-fast",
                "modalities": ["image"],
                "messages": [
                    {
                        "role": "user",
                        "content": full_prompt
                    }
                ]
            },
            timeout=60
        )

        data = response.json()

        # Extract base64 image from response
        try:
            image_data = data["choices"][0]["message"]["images"][0]["image_url"]["url"]
            img_b64 = image_data.split(",", 1)[1] if "," in image_data else image_data
            img_bytes = BytesIO(base64.b64decode(img_b64))

        except (KeyError, IndexError, TypeError) as parse_err:
            print(f"[GENERATE] Failed to parse image from response: {parse_err}")
            print(f"[GENERATE] Full API response: {data}")
            is_generating = False  # STEP 4 error — release lock
            await thinking_msg.delete()
            await update.message.reply_text("❌ Image generation failed.")
            return

        # STEP 5 — Record successful generation timestamp
        user_last_generation[user_id] = now

        # STEP 6 — Release generation lock
        is_generating = False

        # STEP 7 — Send image
        await thinking_msg.delete()
        await update.message.reply_photo(
            photo=img_bytes,
            caption=f"🎨 {user_prompt}"
        )

    except Exception as e:
        # ERROR HANDLING — always release lock on failure
        is_generating = False
        print(f"[GENERATE] Error: {e}")
        try:
            print(f"[GENERATE] Full API response: {response.text}")
        except Exception:
            pass
        await thinking_msg.delete()
        await update.message.reply_text("❌ Image generation failed.")


# ===== DEXSCREENER API FOR PRICECHECK =====
DEXSCREENER_API_URL = "https://api.dexscreener.com/latest/dex/pairs/solana/79Qaq5b1JfC8bFuXkAvXTR67fRPmMjMVNkEA3bb8bLzi"
DEXSCREENER_CHART_URL = "https://dexscreener.com/solana/79Qaq5b1JfC8bFuXkAvXTR67fRPmMjMVNkEA3bb8bLzi"


async def pricecheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch and display live SUOLALA price data from DexScreener API"""
    remember_chat(update)
    
    try:
        response = requests.get(DEXSCREENER_API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        pair = data.get("pair")
        if not pair:
            await update.message.reply_text("❌ Could not fetch price data. Try again later.")
            return
        
        price_usd = float(pair.get("priceUsd", 0))
        
        # Market cap (FDV)
        fdv = pair.get("fdv")
        market_cap = float(fdv) if fdv else 0
        
        # Liquidity
        liquidity = pair.get("liquidity", {})
        liquidity_usd = float(liquidity.get("usd", 0)) if liquidity else 0
        
        # 24h changes
        price_change_24h = pair.get("priceChange", {}).get("h24", "N/A")
        
        # Format message (no links)
        message = (
            "📊 SUOLALA Price Check\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💵 Price: ${price_usd:.10f}\n"
            f"🏦 Market Cap: ${market_cap:,.0f}\n"
            f"💧 Liquidity: ${liquidity_usd:,.0f}\n"
            f"📈 24h Change: {price_change_24h}%\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
        
        await update.message.reply_text(message)
        
    except requests.exceptions.RequestException as e:
        print(f"[PRICECHECK] API error: {e}")
        await update.message.reply_text("❌ Failed to fetch price data. API may be temporarily unavailable.")
    except Exception as e:
        print(f"[PRICECHECK] Error: {e}")
        await update.message.reply_text("❌ An error occurred. Try again later.")


def get_floor_price():
    try:
        url = f"https://api-mainnet.magiceden.dev/v2/collections/{MAGICEDEN_COLLECTION}/stats"
        headers = {
            "accept": "application/json",
            "user-agent": "Mozilla/5.0"
        }
        data = requests.get(url, headers=headers, timeout=10).json()
        floor_lamports = data.get("floorPrice", 0)
        if floor_lamports:
            return floor_lamports / 1_000_000_000
        return None
    except Exception as e:
        print("Floor price error:", e)
        return None


async def randomnft(update: Update, context: ContextTypes.DEFAULT_TYPE):
    remember_chat(update)

    try:
        headers = {
            "accept": "application/json",
            "user-agent": "Mozilla/5.0"
        }

        # 1️⃣ Fetch listed NFTs (REAL LISTINGS)
        list_url = f"https://api-mainnet.magiceden.dev/v2/collections/{MAGICEDEN_COLLECTION}/listings?offset=0&limit=100"
        listings = requests.get(list_url, headers=headers, timeout=15).json()

        if not listings or not isinstance(listings, list):
            await update.message.reply_text("❌ No Suolala NFTs listed right now.")
            return

        # 2️⃣ Pick a random LISTED NFT
        nft = random.choice(listings)

        mint = nft.get("tokenMint")
        name = nft.get("title", "Suolala NFT")
        price = nft.get("price")  # ✅ REAL PRICE (SOL)

        if not mint or price is None:
            await update.message.reply_text("⚠️ NFT listing incomplete. Try again.")
            return

        # 3️⃣ Fetch NFT metadata (image)
        token_url = f"https://api-mainnet.magiceden.dev/v2/tokens/{mint}"
        token_data = requests.get(token_url, headers=headers, timeout=15).json()
        image = token_data.get("image")

        if not image:
            await update.message.reply_text("⚠️ NFT image not found.")
            return

        # 4️⃣ Buy link
        buy_link = f"https://magiceden.io/item-details/{mint}"

        caption = (
            f"🎲 **Random Suolala NFT**\n\n"
            f"🖼 **{name}**\n"
            f"💰 **Price: {price:.4f} SOL**\n"
            f"🛒 Buy on Magic Eden\n"
            f"🔗 {buy_link}"
        )

        await update.message.reply_photo(
            photo=image,
            caption=caption,
            parse_mode="Markdown"
        )

    except Exception as e:
        print("RandomNFT ERROR:", e)
        await update.message.reply_text("⚠️ Failed to fetch NFT. Try again later.")

# ===== AUTOMATIC MESSAGES =====
async def automatic_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Automatically send messages based on keywords"""
    if not update.message or update.message.from_user.is_bot:
        return
    
    # Don't respond to commands
    if update.message.text and update.message.text.startswith('/'):
        return
    
    # Don't respond in private chats
    if update.effective_chat.type == "private":
        return
    
    text = update.message.text.lower() if update.message.text else ""
    
    # Define keywords and responses
    keyword_responses = {
        "suolala": [
            "🐉 SUOLALA to the moon! 🚀",
            "💎 Strong SUOLALA community! 🔥",
            "🐲 SUOLALA 加油! 🇨🇳",
            "🚀 SUOLALA is built by believers! 💪"
        ],
        "website": [
            "🌐 Check our website: https://suolala.netlify.app/",
            "🌐 Visit SUOLALA website: https://suolala.netlify.app/"
        ],
        "contract": [
            "📜 Contract: CY1P83KnKwFYostvjQcoR2HJLyEJWRBRaVQmYyyD3cR8",
            "📜 SUOLALA contract: CY1P83KnKwFYostvjQcoR2HJLyEJWRBRaVQmYyyD3cR8"
        ],
        "buy": [
            "🛒 How to buy: /buy",
            "💰 Want to buy SUOLALA? Use /buy command!"
        ],
        "price": [
            "💰 Check price: /price",
            "📈 Current price: /price"
        ],
        "chart": [
            "📈 Check chart: /chart",
            "📊 View chart: /chart"
        ],
        "nft": [
            "🎨 NFTs: /nft",
            "🖼 SUOLALA NFTs: /nft",
            "🎲 Random NFT: /randomnft"
        ],
        "motivation": [
            "💪 Need motivation? /motivate",
            "🔥 Get motivated: /motivate"
        ],
        "community": [
            "👥 Join community: /community",
            "💬 Community link: /community"
        ],
        "memes": [
            "😂 Memes: /memes",
            "😆 Funny memes: /memes"
        ],
        "stickers": [
            "🧧 Stickers: /stickers",
            "🎭 Get stickers: /stickers"
        ],
        "x": [
            "🐦 X/Twitter: /x",
            "📱 Follow us on X: /x"
        ],
        "rules": [
            "📌 Group rules: /rules",
            "⚖️ Read rules: /rules"
        ],
        "solana": [
            "🪐 Solana ecosystem! 🌟",
            "⚡ Powered by Solana! ⚡"
        ],
        "moon": [
            "🚀 To the moon! 🌕",
            "🌙 Moon soon! 🚀"
        ],
        "gm": [
            "🌞 Good morning SUOLALA fam! 💎",
            "☀️ GM! Have a great day! 🐉"
        ],
        "gn": [
            "🌙 Good night SUOLALA fam! 💤",
            "✨ GN! Sweet dreams! 🐲"
        ]
    }
    
    # Check for keywords and respond
    for keyword, responses in keyword_responses.items():
        if keyword in text:
            response_text = random.choice(responses)
            
            try:
                # Send the response
                sent_msg = await update.message.reply_text(response_text)
                # Schedule deletion after 60 seconds
                asyncio.create_task(delete_after_delay(sent_msg, 60))
            except Exception as e:
                print(f"Automatic message error: {e}")
            break  # Only respond to one keyword per message

# ===== START BOT =====
app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

# MESSAGE TRACKER MUST BE FIRST
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_messages))

# AUTOMATIC MESSAGES HANDLER
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, automatic_messages))

# WELCOME - THIS MUST COME AFTER AUTOMATIC MESSAGES TO AVOID CONFLICT
app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))

# TRANSLATER
app.add_handler(CommandHandler("translate", translate_cmd))

# ALL COMMANDS REGISTERED
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("price", price))
app.add_handler(CommandHandler("chart", chart))
app.add_handler(CommandHandler("buy", buy))
app.add_handler(CommandHandler("memes", memes))
app.add_handler(CommandHandler("stickers", stickers))
app.add_handler(CommandHandler("x", x))
app.add_handler(CommandHandler("community", community))
app.add_handler(CommandHandler("nft", nft))
app.add_handler(CommandHandler("contract", contract))
app.add_handler(CommandHandler("website", website))
app.add_handler(CommandHandler("rules", rules))
app.add_handler(CommandHandler("suolala", suolala))
app.add_handler(CommandHandler("motivate", motivate))
app.add_handler(CommandHandler("count", count_cmd))
app.add_handler(CommandHandler("top", top_cmd))
app.add_handler(CommandHandler("randomnft", randomnft))
app.add_handler(CommandHandler("pricecheck", pricecheck))
app.add_handler(CommandHandler("generate", generate_cmd))

print("✅ SUOLALA BOT RUNNING — ALL FEATURES ENABLED")
print(f"📊 Total commands: 19")
print(f"🤖 Automatic messages: Enabled for 15 keywords")
print(f"👋 Welcome messages: Fixed and will send properly")
print(f"🕒 Welcome messages: Auto-delete after 5 minutes")
print(f"💬 Auto-responses: Delete after 1 minute")
app.run_polling(drop_pending_updates=True)
