# gpt.py
import os
import asyncio

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

# модель и длина ответа
MODEL = os.getenv("OPENAI_MODEL", os.getenv("MODEL", "gpt-4o-mini"))  # начни с 4o-mini, потом попробуешь gpt-5-nano
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "160"))

# ---- Путь 1: новый SDK (openai>=1.x) ----
# pip install --upgrade openai
try:
    from openai import AsyncOpenAI  # новый клиент
    _client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    async def aquery(prompt: str) -> str:
        # минимальный, быстрый вызов
        resp = await _client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Отвечай максимально кратко и по делу."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.6,
            max_tokens=MAX_TOKENS,
        )
        return (resp.choices[0].message.content or "").strip()

except Exception:
    # ---- Путь 2: старый SDK (openai<1.0) ----
    # работает даже если у тебя старая библиотека
    import openai
    openai.api_key = OPENAI_API_KEY

    async def aquery(prompt: str) -> str:
        loop = asyncio.get_event_loop()

        def _call():
            resp = openai.ChatCompletion.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": "Отвечай максимально кратко и по делу."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.6,
                max_tokens=MAX_TOKENS,
            )
            return resp["choices"][0]["message"]["content"].strip()

        return await loop.run_in_executor(None, _call)
