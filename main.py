import os
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
load_dotenv()

import gpt  # ожидаем, что в нем есть async def aquery(prompt: str) -> str

app = FastAPI()

# ===== Настройки скорости/краткости =====
TIMEOUT_SECONDS = float(os.getenv("TIMEOUT_SECONDS", "2.2"))   # укладываемся в 3–4.5с лимит Алисы
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Ты — добрый учитель английского для детей 6–10 лет. "
    "Говори очень кратко и понятно (1–2 предложения), без длинных списков и преамбул."
)

@app.post("/post")
async def post(request: Request):
    # Возвращаем ВСЕГДА 200, чтобы Алиса не считала навык «упавшим»
    try:
        req = await request.json()
    except Exception:
        return JSONResponse({"version":"1.0","response":{"end_session":False,"text":"Повтори, пожалуйста."}}, status_code=200)

    res = {
        "version": req.get("version", "1.0"),
        "session": req.get("session", {}),
        "response": {"end_session": False, "text": "Секунду…"}
    }

    # приветствие на первом ходе
    if (req.get("session") or {}).get("new") and not (req.get("request") or {}).get("original_utterance"):
        res["response"]["text"] = "Привет! Я твой учитель английского. Задавай вопрос — отвечу коротко."
        return JSONResponse(res, status_code=200)

    user_text = ((req.get("request") or {}).get("original_utterance") or "").strip()
    if not user_text:
        res["response"]["text"] = "Скажи вопрос про английский — отвечу в двух предложениях."
        return JSONResponse(res, status_code=200)

    # Обрезаем обращения «Алиса ...»
    for w in ("Алиса", "алиса"):
        if user_text.startswith(w):
            user_text = user_text[len(w):].strip()

    # Формируем очень короткий запрос к модели
    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Вопрос ученика: {user_text}\n\n"
        f"Ответь максимально кратко: 1–2 предложения, простыми словами."
    )

    # Прямой вызов модели с жестким таймаутом (НЕТ фоновых задач)
try:
    answer = await asyncio.wait_for(gpt.aquery(prompt), timeout=TIMEOUT_SECONDS)
    res["response"]["text"] = (answer or "Готово.").strip()[:350]
except asyncio.TimeoutError:
    res["response"]["text"] = "Не успеваю за 2 секунды. Скажи вопрос покороче."
except Exception as e:
    # чтобы видеть причину в логах (model not found / invalid_api_key / quota и т.д.)
    print("[OPENAI ERROR]", repr(e))
    res["response"]["text"] = "Техническая заминка. Скажи ещё раз покороче."
