import os
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse

load_dotenv()

app = FastAPI()

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "").strip()
PAGE_ACCESS_TOKEN = os.getenv("PAGE_ACCESS_TOKEN", "").strip()

AUTO_REPLY_TEXT = (
    "Ассалому алейкум ҳурматли мижоз, сиз ELFER косметология марказига мурожаат қилдиз. "
    "Сизда доғ ва бошқа муаммолар бўлса юзизни эффектсиз ёруғ жойда расмга тушуриб "
    "\"https://t.me/dilhabi_medical_Feruza\" устига босиб телеграмимга ўтсангиз шу ерда суҳбатимизни давом эттирардик."
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
        return

    url = "https://graph.facebook.com/v20.0/me/messages"
    params = {"access_token": PAGE_ACCESS_TOKEN}
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }

    r = requests.post(url, params=params, json=payload, timeout=20)
    print("Send reply:", r.status_code, r.text)


@app.post("/webhook")
async def receive_webhook(request: Request):
    body = await request.json()
    print("Webhook event:", body)
    
    for entry in body.get("entry", []):
        # Instagram webhook odatda "changes" bilan keladi
        for change in entry.get("changes", []):
            print("FIELD:", change.get("field"), "VALUE:", change.get("value"))        
            field = change.get("field")
            value = change.get("value", {})

            if field == "messages":
                sender_id = value.get("sender", {}).get("id")
                message = value.get("message", {})
                text = message.get("text")

                if sender_id and text:
                    send_instagram_reply(sender_id, AUTO_REPLY_TEXT)

    return {"status": "ok"}



@app.get("/")
async def root():
    return {"ok": True}
