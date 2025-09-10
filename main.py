import os
import asyncio
import inspect
from typing import Dict, List   # <-- ДОБАВЬ
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

import gpt  # ожидается aquery(prompt_or_messages)

app = FastAPI()

# ===== Настройки =====
TIMEOUT_SECONDS = float(os.getenv("TIMEOUT_SECONDS", "2.6"))  # <-- БЫЛО 2.2
HISTORY_TURNS   = int(os.getenv("HISTORY_TURNS", "8"))        # <-- ДОБАВЬ
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

# Память на сессию в процессе:
users_state: Dict[str, Dict[str, List[Dict[str, str]]]] = {}  # <-- ДОБАВЬ
