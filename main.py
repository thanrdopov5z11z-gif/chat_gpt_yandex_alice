import os
import asyncio
import inspect
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

import gpt  # ожидается aquery(prompt)

app = FastAPI()

# ===== Настройки =====
TIMEOUT_SECONDS = float(os.getenv("TIMEOUT_SECONDS", "2.2"))
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Ты — добрый учитель английского для детей 6–10 лет. "
    "Говори очень кратко и понятно (1–2 предложения), без длинных списков и преамбул."
)

# --- вспомогательное: аккуратно вызвать gpt.aquery независимо от того, async он или нет
async def call_gpt(prompt: str) -> str:
    fn = getattr(gpt, "aquery", None)
    if fn is None:
        raise RuntimeError("В модуле gpt нет функции aquery(prompt)")
    if inspect.iscoroutinefunction(fn):
        return await fn(prompt)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn, prompt)

@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/post")
async def post(request: Request):
    # 1) безопасно читаем вход
    try:
        req = await request.json()
    except Exception:
        return JSONResponse(
            {"version": "1.0", "response": {"end_session": False, "text": "Повтори, пожалуйста."}},
            status_code=200
        )

    # 2) базовый каркас ответа Алисы
    res = {
        "version": req.get("version", "1.0"),
        "session": req.get("session", {}),
        "response": {"end_session": False, "text": "Секунду…"}
    }

    # 3) приветствие при первом запуске без текста
    sess = req.get("session") or {}
    is_new = bool(sess.get("new"))
    user_text = ((req.get("request") or {}).get("original_utterance") or "").strip()

    if is_new and not user_text:
        res["response"]["text"] = "Привет! Я твой учитель английского. Задавай вопрос — отвечу коротко."
        return JSONResponse(res, status_code=200)

    # 4) если текст пуст — просим уточнить
    if not user_text:
        res["response"]["text"] = "Скажи вопрос про английский — отвечу в двух предложениях."
        return JSONResponse(res, status_code=200)

    # 5) обрезаем «Алиса …» в начале
    for w in ("Алиса", "алиса"):
        if user_text.startswith(w):
            user_text = user_text[len(w):].strip()

    # 6) собираем промпт (кратко!)
    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Вопрос ученика: {user_text}\n\n"
        f"Ответь максимально кратко: 1–2 предложения, простыми словами."
    )

    # 7) один прямой вызов модели с жёстким таймаутом
    try:
        answer = await asyncio.wait_for(call_gpt(prompt), timeout=TIMEOUT_SECONDS)
        res["response"]["text"] = (answer or "Готово.").strip()[:350]
    except asyncio.TimeoutError:
        res["response"]["text"] = "Не успеваю за 2 секунды. Скажи вопрос покороче."
    except Exception as e:
        # логируем, чтобы сразу

