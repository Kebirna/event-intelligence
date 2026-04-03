import os
import asyncio
import requests
import json
from datetime import datetime
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError

# ============================================
# LOAD ENVIRONMENT VARIABLES
# ============================================
load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
PHONE = os.getenv("PHONE")
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")

if not all([API_ID, API_HASH, PHONE, N8N_WEBHOOK_URL]):
    raise ValueError("❌ Missing values in .env file!")

API_ID = int(API_ID)

# ============================================
# CHANNELS TO MONITOR
# ============================================
CHANNELS_TO_MONITOR = [
    "LinkUpAddis",
    "eventinaddis",
    "Eventinaddiss",
    "dekenzo1"
]

# ============================================
# SIMPLE LOG TO FILE
# ============================================
LOG_FILE = "event_intelligence.log"

def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(message)  # Show in terminal (pretty)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} - {message}\n")  # Save  to file

# ============================================
# PERMANENT DUPLICATE PREVENTION
# ============================================
SEEN_FILE = "seen_messages.json"

def load_seen():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r") as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_seen(seen):
    seen_list = list(seen)[-1000:]
    with open(SEEN_FILE, "w") as f:
        json.dump(seen_list, f)

seen_messages = load_seen()
log(f"📂 Loaded {len(seen_messages)} seen messages from memory")

# ============================================
# TELEGRAM CLIENT
# ============================================
client = TelegramClient("event_intelligence_session", API_ID, API_HASH)

@client.on(events.NewMessage(chats=CHANNELS_TO_MONITOR))
async def handler(event):
    try:
        message_text = event.message.message
        if not message_text or len(message_text.strip()) == 0:
            return

        message_key = message_text.strip()[:100].lower()

        if message_key in seen_messages:
            log("⏭️ Duplicate skipped!")
            return

        seen_messages.add(message_key)
        save_seen(seen_messages)

        chat = await event.get_chat()
        source_name = getattr(chat, "username", None) or getattr(chat, "title", "Unknown")

        message_id = event.message.id
        post_link = f"https://t.me/{source_name}/{message_id}"

        log(f"\n📩 New message from: {source_name}")
        log(f"🔗 Post link: {post_link}")
        log(f"📝 Text: {message_text[:80]}...")

        payload = {
            "text": message_text,
            "source": source_name,
            "post_link": post_link
        }

        # Retry 3 times if fails
        for attempt in range(3):
            try:
                response = requests.post(
                    N8N_WEBHOOK_URL,
                    json=payload,
                    timeout=10
                )
                if response.status_code == 200:
                    log("✅ Sent to n8n successfully!")
                    break
                else:
                    log(f"⚠️ n8n error: {response.status_code}")
            except requests.exceptions.RequestException as e:
                log(f"❌ Request failed (attempt {attempt+1}): {e}")
                await asyncio.sleep(2)

        await asyncio.sleep(1)

    except FloodWaitError as e:
        log(f"⏳ Flood wait: sleeping {e.seconds} seconds")
        await asyncio.sleep(e.seconds)

    except Exception as e:
        log(f"❌ Error in handler: {e}")

# ============================================
# MAIN WITH AUTO-RECONNECT
# ============================================
async def main():
    log("🚀 Starting Event Intelligence Listener...")
    log(f"👀 Monitoring {len(CHANNELS_TO_MONITOR)} channels:")
    for ch in CHANNELS_TO_MONITOR:
        log(f"   • {ch}")
    log("⏳ Waiting for new messages...\n")

    while True:
        try:
            await client.start(phone=PHONE)
            log("✅ Connected to Telegram!")
            await client.run_until_disconnected()
        except Exception as e:
            log(f"❌ Connection lost: {e}")
            log("🔄 Reconnecting in 30 seconds...")
            await asyncio.sleep(30)

if __name__ == "__main__":
    asyncio.run(main())