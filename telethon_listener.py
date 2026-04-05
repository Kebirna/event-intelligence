import os
import asyncio
import requests
import json
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.tl.types import (
    MessageEntityBold,
    MessageEntityBlockquote,
    MessageEntityTextUrl,
)

# ============================================
# LOAD ENVIRONMENT VARIABLES
# ============================================
load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
PHONE = os.getenv("PHONE")
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")
OUTPUT_CHANNEL = os.getenv("OUTPUT_CHANNEL", "EventCollectorChannel")

if not all([API_ID, API_HASH, PHONE, N8N_WEBHOOK_URL]):
    raise ValueError("❌ Missing values in .env file!")

API_ID = int(API_ID)

CHANNELS_TO_MONITOR = [
    "LinkUpAddis",
    "eventinaddis",
    "Eventinaddiss",
    "dekenzo1"
]

LOG_FILE = "event_intelligence.log"

def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(message)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} - {message}\n")

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

client = TelegramClient("event_intelligence_session", API_ID, API_HASH)
main_loop = None

def utf16_len(text):
    return len(text.encode('utf-16-le')) // 2

def utf16_offset(full_text, char_offset):
    return utf16_len(full_text[:char_offset])

def clean(val):
    s = str(val) if val is not None else ""
    return s.lstrip("=").strip()

async def send_collapsible_message(data):
    score_raw = clean(data.get("relevanceScore", "0"))
    try:
        score = int(score_raw)
    except:
        score = 0

    action = clean(data.get("suggestedAction", "REVIEW")).upper()
    leads  = clean(data.get("leadPotential", "MEDIUM")).upper()

    action_emoji = "✅" if action == "ATTEND" else "👀" if action == "MONITOR" else "⏭️"
    leads_emoji = "🔥" if leads == "HIGH" else "⚡" if leads == "MEDIUM" else "❄️"
    score_circle = "🟢" if score >= 8 else "🟡" if score >= 5 else "🔴"

    event_name  = clean(data.get("eventName", "Unknown"))
    location    = clean(data.get("location", "TBD"))
    date        = clean(data.get("date", "TBD"))
    time_       = clean(data.get("time", ""))
    event_type  = clean(data.get("eventType", "General"))
    entrance    = clean(data.get("entranceFee", "TBD"))
    source      = clean(data.get("source", "Unknown"))
    reason      = clean(data.get("relevanceReason", ""))
    opportunity = clean(data.get("keyOpportunity", ""))
    audience    = clean(data.get("targetAudience", ""))
    team        = clean(data.get("recommendedTeam", ""))
    post_link   = clean(data.get("post_link", ""))

    header = (
        f"📅 New Event Detected\n\n"
        f"🎪 Event: {event_name}\n"
        f"📍 Location: {location}\n"
        f"🕐 Date: {date} {time_}\n"
        f"🎯 Type: {event_type}\n"
        f"🎟 Entrance: {entrance}\n"
        f"🌐 Source: @{source}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{score_circle} GF Score: {score}/10 {action_emoji} {action}\n"
        f"🎯 Leads: {leads_emoji} {leads}\n\n"
    )

    collapsed_body = (
        f"💡 Why attend:\n{reason}\n\n"
        f"🔑 Key Opportunity:\n{opportunity}\n\n"
        f"👥 Who attends: {audience}\n"
        f"👔 Send: {team}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )

    # Build full text
    link_label = "View Original Post"
    # No emoji before link — eliminates any UTF-16 offset ambiguity
    footer = f"\n\n{link_label}"

    full_text = header + collapsed_body + footer

    # UTF-16 offsets
    bold_text = "New Event Detected"
    bold_utf16_offset = utf16_offset(full_text, full_text.index(bold_text))
    bold_utf16_len    = utf16_len(bold_text)

    collapsed_utf16_offset = utf16_len(header)
    collapsed_utf16_length = utf16_len(collapsed_body)

    link_char_offset  = full_text.rfind(link_label)
    link_utf16_offset = utf16_offset(full_text, link_char_offset)
    link_utf16_len    = utf16_len(link_label)

    log(f"📐 UTF-16 — bold:{bold_utf16_offset}+{bold_utf16_len}, collapsed:{collapsed_utf16_offset}+{collapsed_utf16_length}, link:{link_utf16_offset}+{link_utf16_len}")

    entities = [
        MessageEntityBold(offset=bold_utf16_offset, length=bold_utf16_len),
        MessageEntityBlockquote(offset=collapsed_utf16_offset, length=collapsed_utf16_length, collapsed=True),
    ]

    if post_link and link_char_offset != -1:
        entities.append(MessageEntityTextUrl(
            offset=link_utf16_offset,
            length=link_utf16_len,
            url=post_link
        ))

    await client.send_message(OUTPUT_CHANNEL, full_text, formatting_entities=entities)
    log(f"✅ Collapsible message sent for: {event_name}")


class WebhookHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        if self.path == "/send_formatted":
            try:
                data = json.loads(body)
                log(f"📨 /send_formatted received: {data.get('eventName', 'unknown')}")
                future = asyncio.run_coroutine_threadsafe(send_collapsible_message(data), main_loop)
                future.result(timeout=30)
                self._respond(200, {"status": "sent"})
            except Exception as e:
                log(f"❌ /send_formatted error: {e}")
                self._respond(500, {"status": "error", "message": str(e)})

        elif self.path == "/send":
            try:
                data = json.loads(body)
                text = data.get("text", "")
                if text:
                    future = asyncio.run_coroutine_threadsafe(client.send_message(OUTPUT_CHANNEL, text), main_loop)
                    future.result(timeout=30)
                self._respond(200, {"status": "sent"})
            except Exception as e:
                log(f"❌ /send error: {e}")
                self._respond(500, {"status": "error", "message": str(e)})

        else:
            self._respond(404, {"status": "not found"})

    def _respond(self, code, body_dict):
        response = json.dumps(body_dict).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


def start_http_server():
    server = HTTPServer(("0.0.0.0", 5055), WebhookHandler)
    log("🌐 HTTP server listening on port 5055")
    log("   • /send_formatted  ← collapsible messages from n8n")
    log("   • /send            ← legacy plain text")
    server.serve_forever()


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

        payload = {"text": message_text, "source": source_name, "post_link": post_link}

        for attempt in range(3):
            try:
                response = requests.post(N8N_WEBHOOK_URL, json=payload, timeout=10)
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


async def main():
    global main_loop
    main_loop = asyncio.get_event_loop()

    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

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