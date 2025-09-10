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

# In-memory (на один процесс)
answers: Dict[str, str] = {}          # pending_key -> готовый ответ
users_state: Dict[str, Dict] = {}     # per session_id: {messages: List[str], pending_key: Optional[str]}

# ====== helpers ======
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
            "Привет! Я твой учитель английского языка. "
            "Задавай вопросы или проси объяснить правило — отвечу кратко и понятно."
        )
        # можно добавить подсказки, но по просьбе — без дополнительных режимов
        print('end handle (welcome):', datetime.datetime.now())
        return

    # срезаем обращение «Алиса …»
    for w in CUT_WORD:
        if utterance.startswith(w):
            utterance = utterance[len(w):].strip()

    low = utterance.lower()

    # стоп-слова
    if low in {"стоп", "выход", "хватит", "пока"}:
        res['response']['text'] = "Пока! Приходи ещё заниматься."
        res['response']['end_session'] = True
        print('end handle (bye):', datetime.datetime.now())
        return

    # если есть незавершённый ответ — пробуем его отдать в начале хода
    pending_key = st.get('pending_key')
    if pending_key:
        ready = answers.get(pending_key)
        if ready:
            res['response']['text'] = ready
            answers.pop(pending_key, None)
            st['pending_key'] = None
            if utterance:
                st['messages'] = _trim_history(st['messages'] + [utterance], HISTORY_TURNS)
            print('end handle (deliver pending):', datetime.datetime.now())
            return
        else:
            if "продолж" in low:
                res['response']['text'] = "Ещё чуть-чуть… Скажи «продолжить» через секунду."
                print('end handle (pending not ready):', datetime.datetime.now())
                return
            # иначе продолжаем — это новый вопрос; старый ответ доготовится и будет доступен по «продолжить»

    # ====== GPT с таймаутом и отложенной доставкой ======
    msgs: List[str] = _trim_history(st.get('messages', []), HISTORY_TURNS)

    # уникальный ключ ожидания
    pending_key = f"{session_id}:{int(time.time()*1000)}"
    st['pending_key'] = pending_key

    # запускаем генерацию в фоне
    task = asyncio.create_task(_ask_and_store(pending_key, utterance, msgs))

    try:
        # ждём максимум ~1.9 с — если успеет, отдадим сразу
        await asyncio.wait_for(task, timeout=1.9)
        ready = answers.get(pending_key)
        if ready:
            res['response']['text'] = ready
            answers.pop(pending_key, None)
            st['pending_key'] = None
        else:
            # теоретически не должно случиться, но на всякий случай
            res['response']['text'] = "Готовлю ответ. Скажи «продолжить» через секунду."
    except asyncio.TimeoutError:
        # мягкий фолбэк, без дополнительных кнопок/режимов
        res['response']['text'] = "Хороший вопрос! Дай секундочку… Скажи «продолжить», и я договорю."
    finally:
        if utterance:
            st['messages'] = _trim_history(st['messages'] + [utterance], HISTORY_TURNS)

    print('end handle (gpt branch):', datetime.datetime.now())

async def _ask_and_store(pending_key: str, user_text: str, history: List[str]):
    """Запрос к GPT с учительской установкой. Результат кладём в answers[pending_key]."""
    try:
        teacher_prefix = (
            SYSTEM_PROMPT
            + "\n\nОтвечай очень кратко: максимум 1–2 предложения, простыми словами, без лишних преамбул."
        )
        compound_request = f"{teacher_prefix}\n\nВопрос ученика: {user_text}"
        reply = await gpt.aquery(compound_request, history)
    except Exception:
        traceback.print_exc()
        reply = "Немного сложновато. Давай попробуем ещё раз коротко?"
    answers[pending_key] = reply
    return reply

