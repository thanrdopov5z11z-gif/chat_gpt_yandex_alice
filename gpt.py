import os
import openai

# Ключ и модель
openai.api_key = os.environ["OPENAI_API_KEY"]
MODEL = os.getenv("OPENAI_MODEL", os.getenv("MODEL", "gpt-5-nano"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "160"))  # короткий ответ

async def aquery(prompt: str) -> str:
    # Лёгкий, быстрый запрос к чату
    # Если твоя версия openai не поддерживает acreate, используй create через run_in_executor в main.py
    resp = await openai.ChatCompletion.acreate(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Отвечай кратко и по делу."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.6,
        max_tokens=MAX_TOKENS,
    )
    return resp["choices"][0]["message"]["content"].strip()
