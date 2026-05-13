import hashlib
import hmac
import json
import os
import threading
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

load_dotenv()

app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "").strip()
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "").strip()
META_APP_SECRET = os.getenv("META_APP_SECRET", "").strip()
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v20.0").strip()
LOGO_IMAGE_URL = os.getenv("LOGO_IMAGE_URL", "").strip()
REQUIRE_META_SIGNATURE = os.getenv("REQUIRE_META_SIGNATURE", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
STATE_FILE = Path(os.getenv("ASSISTANT_STATE_FILE", "assistant_state.json"))
DEFAULT_TELEGRAM_LINK = "https://t.me/dilhabi_medical_Feruza"
TELEGRAM_ASSISTANT_LINKS = [
    link.strip()
    for link in os.getenv("TELEGRAM_ASSISTANT_LINKS", DEFAULT_TELEGRAM_LINK).split(",")
    if link.strip()
]
_assistant_state_lock = threading.Lock()

AUTO_REPLY_TEMPLATE = (
    "Ассалому алайкум ҳурматли мижоз, сиз DILHABI COSMETICS косметология марказига мурожаат қилдингиз. "
    "Сизда доғ ва бошқа муаммолар бўлса, {telegram_link} орқали телеграмимизга ўтсангиз, "
    "суҳбатимизни шу ерда давом эттирамиз.\n\n"
    "Assalomu alaykum, hurmatli mijoz. Siz DILHABI COSMETICS kosmetologiya markaziga murojaat qildingiz. "
    "Sizda dog' va boshqa muammolar bo'lsa, {telegram_link} orqali Telegramimizga o'tsangiz, "
    "suhbatimizni shu yerda davom ettiramiz.\n\n"
    "Здравствуйте, уважаемый клиент. Вы обратились в косметологический центр DILHABI COSMETICS. "
    "Если у вас есть пигментные пятна или другие проблемы, перейдите в наш Telegram по ссылке "
    "{telegram_link}, и мы продолжим общение там."
)


def _read_assistant_index():
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return 0

    try:
        return int(state.get("next_index", 0))
    except (TypeError, ValueError):
        return 0


def _write_assistant_index(next_index: int):
    tmp_file = STATE_FILE.with_suffix(f"{STATE_FILE.suffix}.tmp")
    tmp_file.write_text(
        json.dumps({"next_index": next_index}, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp_file.replace(STATE_FILE)


def get_next_telegram_link():
    if not TELEGRAM_ASSISTANT_LINKS:
        return DEFAULT_TELEGRAM_LINK

    with _assistant_state_lock:
        current_index = _read_assistant_index()
        link = TELEGRAM_ASSISTANT_LINKS[current_index % len(TELEGRAM_ASSISTANT_LINKS)]
        _write_assistant_index((current_index + 1) % len(TELEGRAM_ASSISTANT_LINKS))

    return link


def build_auto_reply_text():
    return AUTO_REPLY_TEMPLATE.format(telegram_link=get_next_telegram_link())


@app.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
        return PlainTextResponse(content=challenge, status_code=200)

    raise HTTPException(status_code=403, detail="Verification failed")


def send_instagram_message(recipient_id: str, message: dict):
    if not PAGE_ACCESS_TOKEN:
        print("ERROR: PAGE_ACCESS_TOKEN is empty")
        return False

    url = f"https://graph.instagram.com/{GRAPH_API_VERSION}/me/messages"
    headers = {"Authorization": f"Bearer {PAGE_ACCESS_TOKEN}"}
    payload = {
        "recipient": {"id": recipient_id},
        "message": message,
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
    except requests.RequestException as exc:
        print("ERROR: Send reply failed:", exc)
        return False

    print("Send reply to:", recipient_id)
    print("Send reply status:", response.status_code)
    print("Send reply response:", response.text)
    return 200 <= response.status_code < 300


def send_instagram_reply(recipient_id: str, text: str):
    text_sent = send_instagram_message(recipient_id, {"text": text})

    if LOGO_IMAGE_URL:
        image_sent = send_instagram_message(
            recipient_id,
            {
                "attachment": {
                    "type": "image",
                    "payload": {"url": LOGO_IMAGE_URL},
                }
            },
        )
        return text_sent and image_sent

    return text_sent


def verify_meta_signature(request: Request, body: bytes):
    if not META_APP_SECRET:
        return

    signature = request.headers.get("x-hub-signature-256", "")
    if not signature.startswith("sha256="):
        message = "Missing Meta signature"
        print("WARNING:", message)
        if REQUIRE_META_SIGNATURE:
            raise HTTPException(status_code=403, detail=message)
        return

    expected = hmac.new(
        META_APP_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, f"sha256={expected}"):
        message = "Invalid Meta signature"
        print("WARNING:", message)
        if REQUIRE_META_SIGNATURE:
            raise HTTPException(status_code=403, detail=message)


def iter_sender_ids(body: dict):
    for entry in body.get("entry", []):
        # Instagram webhook can arrive as entry.changes[].value.
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue

            value = change.get("value") or {}
            message = value.get("message") or {}
            sender_id = (value.get("sender") or {}).get("id")

            if sender_id and message and not message.get("is_echo"):
                print("Incoming change message from:", sender_id)
                yield sender_id

        # Some Meta messaging webhooks arrive as entry.messaging[].
        for event in entry.get("messaging", []):
            message = event.get("message") or {}
            sender_id = (event.get("sender") or {}).get("id")

            if sender_id and message and not message.get("is_echo"):
                print("Incoming messaging event from:", sender_id)
                yield sender_id


@app.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    raw_body = await request.body()
    verify_meta_signature(request, raw_body)

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    print("Webhook body:", json.dumps(body, ensure_ascii=False))

    reply_count = 0
    for sender_id in iter_sender_ids(body):
        background_tasks.add_task(send_instagram_reply, sender_id, build_auto_reply_text())
        reply_count += 1

    print("Webhook processed. Replies queued:", reply_count)
    return {"status": "ok", "replies_queued": reply_count}


@app.get("/")
async def root():
    return {"ok": True}
