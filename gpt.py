# gpt.py
import os
import asyncio
from typing import List, Dict, Union

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

MODEL = os.getenv("OPENAI_MODEL", os.getenv("MODEL", "gpt-4o-mini"))  # можно поменять на gpt-5-nano
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "260"))

Message = Dict[str, str]  # {"role": "system"|"user"|"assistant", "content": "..."}

# Попытка №1: новый SDK (openai>=1.x)
try:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    async def aquery(prompt_or_messages: Union[str, List[Message]]) -> str:
        # Принимаем либо строку, либо список сообщений (для контекста)
        if isinstance(prompt_or_messages, list):
            messages = prompt_or_messages
        else:
            messages = [
                {"role": "system", "content": "Отвечай достаточно развернуто, но кратко и по делу."},
                {"role": "user", "content": str(prompt_or_messages)},
            ]

        r = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.6,
            max_tokens=MAX_TOKENS,
        )
        return (r.choices[0].message.content or "").strip()

except Exception:
    # Попытка №2: старый SDK (openai<1.0)
    import openai
    openai.api_key = OPENAI_API_KEY

    def _sync_query(prompt_or_messages: Union[str, List[Message]]) -> str:
        if isinstance(prompt_or_messages, list):
            messages = prompt_or_messages
        else:
            messages = [
                {"role": "system", "content": "Отвечай достаточно развернуто, но кратко и по делу."},
                {"role": "user", "content": str(prompt_or_messages)},
            ]
        r = openai.ChatCompletion.create(
            model=MODEL,
            messages=messages,
            temperature=0.6,
            max_tokens=MAX_TOKENS,
        )
        return r["choices"][0]["message"]["content"].strip()

    async def aquery(prompt_or_messages: Union[str, List[Message]]) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_query, prompt_or_messages)
