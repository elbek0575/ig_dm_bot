import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse

load_dotenv()

app = FastAPI()
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "").strip()

@app.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
        return PlainTextResponse(content=challenge, status_code=200)

    raise HTTPException(status_code=403, detail="Verification failed")

@app.post("/webhook")
async def receive_webhook(request: Request):
    data = await request.json()
    print("Webhook event:", data)
    return JSONResponse({"status": "ok"}, status_code=200)

@app.get("/")
async def root():
    return {"ok": True}