import os
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

# ====== Настройки через ENV ======
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "6"))
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Ты — добрый учитель английского для детей 6–10 лет. Говори просто и дружелюбно. "
    "Объясняй кратко (1–2 предложения), давай маленькие задания (повтори слово, переведи, выбери вариант). "
    "Хвали за попытки, ошибки исправляй мягко, сначала дай подсказку, затем правильный ответ. "
    "Если вопрос не про английский — мягко верни к теме."
)

# Режущие «обращения к Алисе» в начале реплики
CUT_WORD = ['Алиса', 'алиса']

# Память на процесс
answers: Dict[str, str] = {}
users_state: Dict[str, Dict[str, List[str]]] = {}

# ====== Служебные роуты для быстрых проверок ======
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

# ====== Вспомогательные ======
def _suggest_buttons(titles: List[str]):
    return [{"title": t, "hide": True} for t in titles[:5]]

def _trim_history(msgs: List[str], keep: int) -> List[str]:
    if not msgs:
        return []
    return msgs[-keep:]

def _as_json(resp: dict) -> JSONResponse:
    # Всегда возвращаем 200, чтобы Алиса не видела 4xx/5xx
    return JSONResponse(resp, status_code=200)

# ====== Основной вебхук Алисы ======
@app.post("/post")
async def post(request: Request):
    try:
        req = await request.json()
    except Exception:
        # Неверный JSON — мягкий ответ
        return _as_json({
            "version": "1.0",
            "response": {"end_session": False, "text": "Я тебя не расслышала. Повтори, пожалуйста."}
        })

    response = {
        "session": req.get("session", {}),
        "version": req.get("version", "1.0"),
        "response": {"end_session": False}
    }

    await handle_dialog(response, req)
    # Возвращаем корректный JSON
    return _as_json(response)

async def handle_dialog(res, req):
    print('start handle:', datetime.datetime.now(tz=None))
    session = req.get('session') or {}
    session_id = session.get('session_id') or "anon"
    print('session:', session_id)

    # Инициализация состояния
    if session_id not in users_state:
        users_state[session_id] = {'messages': []}
    session_state = users_state[session_id]

    # Приветствие при первом запуске (или если нет текста)
    is_new = bool(session.get("new"))
    utterance = (req.get('request') or {}).get('original_utterance') or ""
    utterance = utterance.strip()

    if is_new and not utterance:
        greeting = (
            "Привет! Я твой учитель английского языка. "
            "Давай начнём: скажи «викторина» или «слова»."
        )
        res['response']['text'] = greeting
        res['response']['tts'] = "Привет! Я твой учитель английского языка. Скажи: викторина — или — слова."
        res['response']['buttons'] = _suggest_buttons(["Викторина", "Слова", "Переведи"])
        print('end handle:', datetime.datetime.now(tz=None))
        return

    # Если пользователь что-то сказал
    if utterance:
        # Срезаем «Алиса …» в начале
        for w in CUT_WORD:
            if utterance.startswith(w):
                utterance = utterance[len(w):].strip()

        # Достаём/подрезаем историю
        messages: List[str] = session_state.get('messages', [])
        messages = _trim_history(messages, HISTORY_TURNS)

        # ====== Быстрые режимы без GPT (отклик < 100 мс) ======
        low = utterance.lower()
        if low in {"стоп", "выход", "хватит", "пока"}:
            res['response']['text'] = "Пока! Приходи ещё заниматься."
            res['response']['end_session'] = True
            print('end handle:', datetime.datetime.now(tz=None))
            return

        # «Викторина» — мгновенный вопрос без GPT
        if "викторин" in low:
            res['response']['text'] = "Переведи на русский: cat."
            res['response']['buttons'] = _suggest_buttons(["кот", "собака", "яблоко", "Слова"])
            print('end handle:', datetime.datetime.now(tz=None))
            return

        # «Слова» / перевод простых слов без GPT
        mapping = {"кот": "cat", "собака": "dog", "яблоко": "apple"}
        if low in {"слова", "переведи", "слово"} or low in mapping:
            if low in mapping:
                res['response']['text'] = f"{low} — по-английски {mapping[low]}. Молодец! Ещё?"
                res['response']['buttons'] = _suggest_buttons(["кот", "собака", "яблоко", "Викторина"])
            else:
                res['response']['text'] = "Скажи слово на русском — я дам перевод. Например: «яблоко»."
                res['response']['buttons'] = _suggest_buttons(["яблоко", "кот", "собака", "Викторина"])
            print('end handle:', datetime.datetime.now(tz=None))
            return

        # ====== Медленная ветка — спрашиваем GPT, но быстро отвечаем фолбэком ======
        # Запускаем генерацию в фоне
        task = asyncio.create_task(ask(utterance, messages))

        # Короткая пауза (даём шанс готовому ответу) — держим < ~2 сек суммарно
        await asyncio.sleep(1.0)

        # Обновим историю
        messages.append(utterance)
        session_state['messages'] = messages

        # Ключ для словаря ответов (чтобы не конфликтовало с одинаковыми текстами)
        ans_key = f"{session_id}::{utterance}"

        if task.done():
            reply = task.result()
            answers.pop(ans_key, None)
        else:
            # Не успели — мягкий «учительский» фолбэк + кнопки
            reply = "Хороший вопрос! Дай  секундочку… Скажи «продолжить», и я договорю."
            res['response']['tts'] = "Хороший вопрос! sil <[800]> Скажи: продолжить — и я договорю."
            res['response']['buttons'] = _suggest_buttons(["Продолжить", "Викторина", "Слова"])
            # помечаем незавершённый запрос — при следующей реплике отдадим готовый ответ
            session_state['message'] = ans_key

        res['response']['text'] = reply

    else:
        # Пустая реплика (на всякий случай)
        res['response']['text'] = "Я твой учитель английского. Скажи: «викторина» или «слова»."
        res['response']['buttons'] = _suggest_buttons(["Викторина", "Слова", "Переведи"])

    print('end handle:', datetime.datetime.now(tz=None))

async def ask(user_text: str, messages: List[str]) -> str:
    """
    Вызываем GPT с «учительской» установкой. Если в твоём gpt.aquery уже
    учитывается системный промпт из ENV — всё ок. Если нет, мы добавим
    короткую установку прямо в текущий запрос (не ломает совместимость).
    """
    try:
        # Локальный префикс-установка (на случай, если gpt.aquery не подхватывает SYSTEM_PROMPT сам)
        teacher_prefix = (
            SYSTEM_PROMPT
            + "\n\nОтвечай очень кратко: максимум 1–2 предложения, простыми словами, без лишних преамбул."
        )
        # Передаём в aquery «подсказку учителя» + исходный вопрос
        compound_request = f"{teacher_prefix}\n\nВопрос ученика: {user_text}"
        reply = await gpt.aquery(compound_request, messages)
    except Exception:
        traceback.print_exc()
        reply = "Немного сложновато. Давай попробуем ещё раз коротко?"
    return reply
