import os
import time
import asyncio
import traceback
import datetime
from typing import Dict, List
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from dotenv import load_dotenv
load_dotenv()

import gpt

app = FastAPI()

# ====== ENV ======
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "6"))
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Ты — добрый учитель английского для детей 6–10 лет. Говори просто и дружелюбно. "
    "Объясняй кратко (1–2 предложения), давай маленькие задания (повтори слово, переведи, выбери вариант). "
    "Хвали за попытки, ошибки исправляй мягко, сначала дай подсказку, затем правильный ответ. "
    "Если вопрос не про английский — мягко верни к теме."
)

CUT_WORD = ['Алиса', 'алиса']

# Глобальные in-memory структуры (на один процесс)
answers: Dict[str, str] = {}          # pending_key -> готовый ответ
users_state: Dict[str, Dict] = {}     # per session_id

# ====== helpers ======
def _suggest_buttons(titles: List[str]):
    return [{"title": t, "hide": True} for t in titles[:5]]

def _trim_history(msgs: List[str], keep: int) -> List[str]:
    if not msgs:
        return []
    return msgs[-keep:]

def _json_ok(resp: dict) -> JSONResponse:
    # Всегда 200, чтобы Алиса не видела 4xx/5xx
    return JSONResponse(resp, status_code=200)

# ====== debug & health ======
@app.get("/health")
async def health():
    return {"ok": True, "ts": int(datetime.datetime.now().timestamp())}

@app.get("/debug-model")
async def debug_model():
    return {
        "OPENAI_MODEL": os.getenv("OPENAI_MODEL"),
        "MODEL": os.getenv("MODEL"),
        "HISTORY_TURNS": HISTORY_TURNS
    }

# ====== основной вебхук ======
@app.post("/post")
async def post(request: Request):
    try:
        req = await request.json()
    except Exception:
        return _json_ok({
            "version": "1.0",
            "response": {"end_session": False, "text": "Я тебя не расслышала. Повтори, пожалуйста."}
        })

    response = {
        "session": req.get("session", {}),
        "version": req.get("version", "1.0"),
        "response": {"end_session": False}
    }

    await handle_dialog(response, req)
    return _json_ok(response)

async def handle_dialog(res, req):
    print('start handle:', datetime.datetime.now())
    session = req.get('session') or {}
    rq = req.get('request') or {}
    session_id = session.get('session_id') or "anon"

    # init state
    st = users_state.setdefault(session_id, {'messages': [], 'pending_key': None})

    # приветствие на первом ходе
    is_new = bool(session.get("new"))
    utterance = (rq.get('original_utterance') or "").strip()

    if is_new and not utterance:
        res['response']['text'] = (
            "Привет! Я твой учитель английского. "
            "Можем переводить слова и фразы, объяснять правила и тренировать произношение. "
            "Скажи: «переведи …» или «как сказать …»."
        )
        res['response']['tts'] = (
            "Привет! Я твой учитель английского. "
            "Скажи: переведи — или — как сказать."
        )
        res['response']['buttons'] = _suggest_buttons(["Переведи", "Повтори"])
        print('end handle (welcome):', datetime.datetime.now())
        return

    # срезаем обращение «Алиса …»
    for w in CUT_WORD:
        if utterance.startswith(w):
            utterance = utterance[len(w):].strip()

    low = utterance.lower()

    # стоп
