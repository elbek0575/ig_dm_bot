import hashlib
import hmac
import json
import os

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
REQUIRE_META_SIGNATURE = os.getenv("REQUIRE_META_SIGNATURE", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

AUTO_REPLY_TEXT = (
    "Ассалому алайкум ҳурматли мижоз, сиз ELFER косметология марказига мурожаат қилдингиз. "
    "Сизда доғ ва бошқа муаммолар бўлса, юзингизни эффектсиз, ёруғ жойда расмга тушириб, "
    "https://t.me/dilhabi_medical_Feruza орқали телеграмимизга ўтсангиз, суҳбатимизни шу ерда давом эттирамиз."
)


@app.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
        return PlainTextResponse(content=challenge, status_code=200)

    raise HTTPException(status_code=403, detail="Verification failed")


def send_instagram_reply(recipient_id: str, text: str):
    if not PAGE_ACCESS_TOKEN:
        print("ERROR: PAGE_ACCESS_TOKEN is empty")
        return False

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/me/messages"
    params = {"access_token": PAGE_ACCESS_TOKEN}
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
    }

    try:
        response = requests.post(url, params=params, json=payload, timeout=20)
    except requests.RequestException as exc:
        print("ERROR: Send reply failed:", exc)
        return False

    print("Send reply:", response.status_code, response.text)
    return 200 <= response.status_code < 300


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
                yield sender_id

        # Some Meta messaging webhooks arrive as entry.messaging[].
        for event in entry.get("messaging", []):
            message = event.get("message") or {}
            sender_id = (event.get("sender") or {}).get("id")

            if sender_id and message and not message.get("is_echo"):
                yield sender_id


@app.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    raw_body = await request.body()
    verify_meta_signature(request, raw_body)

    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    reply_count = 0
    for sender_id in iter_sender_ids(body):
        background_tasks.add_task(send_instagram_reply, sender_id, AUTO_REPLY_TEXT)
        reply_count += 1

    print("Webhook processed. Replies queued:", reply_count)
    return {"status": "ok", "replies_queued": reply_count}


@app.get("/")
async def root():
    return {"ok": True}
