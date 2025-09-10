import os
import asyncio
import inspect
from typing import Dict, List
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

import gpt  # aquery(prompt_or_messages)

app = FastAPI()

# ===== Настройки =====
TIMEOUT_SECONDS = float(os.getenv("TIMEOUT_SECONDS", "2.6"))
HISTORY_TURNS   = int(os.getenv("HISTORY_TURNS", "8"))
SYSTEM_PROMPT   = os.getenv(
    "SYSTEM_PROMPT",
    "Ты — добрый учитель английского для детей 6–10 лет. "
    "Говори просто и дружелюбно. Объясняй кратко, но информативно (2–4 предложения). "
    "Дай 1 простой пример. Хвали за попытки, ошибки исправляй мягко."
)
ANSWER_STYLE = os.getenv(
    "ANSWER_STYLE",
    "Отвечай кратко, но информативно: 2–4 предложения и 1 простой пример. Без преамбул."
)

# Память на сессию в процессе (по session_id)
users_state: Dict[str, Dict[str, List[Dict[str, str]]]] = {}


async def call_gpt(payload):
    """Аккуратно вызывает gpt.aquery независимо от того, async он или sync, и
       принимает либо строку, либо список сообщений."""
    fn = getattr(gpt, "aquery", None)
    if fn is None:
        raise RuntimeError("В модуле gpt нет функции aquery")
    if inspect.iscoroutinefunction(fn):
        return await fn(payload)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn, payload)


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
            status_code=200,
        )

    # 2) базовый каркас ответа Алисы
    res = {
        "version": req.get("version", "1.0"),
        "session": req.get("session", {}),
        "response": {"end_session": False, "text": "Секунду…"},
    }

    # 3) сессия/текст
    sess = req.get("session") or {}
    is_new = bool(sess.get("new"))
    session_id = sess.get("session_id") or "anon"
    user_text = ((req.get("request") or {}).get("original_utterance") or "").strip()

    # 4) инициализация памяти для этой сессии
    st = users_state.setdefault(session_id, {"history": []})

    # 5) приветствие при первом заходе + кладём system-промпт в историю
    if is_new and not user_text:
        st["history"] = [
            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\nСтиль: {ANSWER_STYLE}"}
        ]
        res["response"]["text"] = "Привет! Я твой учитель английского. Спрашивай — отвечу кратко, с примером."
        return JSONResponse(res, status_code=200)

    # 6) если текста нет — просим задать вопрос
    if not user_text:
        res["response"]["text"] = "Скажи вопрос про английский — отвечу кратко."
        return JSONResponse(res, status_code=200)

    # 7) срезаем «Алиса …» в начале
    for w in ("Алиса", "алиса"):
        if user_text.startswith(w):
            user_text = user_text[len(w):].strip()

    # 8) собираем сообщения: system + последние HISTORY_TURNS пар + текущий вопрос
    history = st.get("history") or []
    sys = history[:1] if history and history[0].get("role") == "system" else []
    tail = history[-(HISTORY_TURNS * 2):] if len(history) > 1 else []
    messages = sys + tail + [{"role": "user", "content": user_text}]

    # 9) вызов модели с таймаутом и обновление истории
    try:
        answer = await asyncio.wait_for(call_gpt(messages), timeout=TIMEOUT_SECONDS)
        answer = (answer or "").strip()
        st["history"] = sys + tail + [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": answer},
        ]
        res["response"]["text"] = answer[:600]
    except asyncio.TimeoutError:
        res["response"]["text"] = "Не успеваю за 2–3 секунды. Скажи вопрос покороче."
    except Exception as e:
        print("[OPENAI ERROR]", repr(e))
        res["response"]["text"] = "Техническая заминка. Скажи ещё раз покороче."

    return JSONResponse(res, status_code=200)
