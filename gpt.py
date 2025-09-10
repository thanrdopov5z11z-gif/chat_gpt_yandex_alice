# gpt.py — работает и с новым, и со старым SDK openai
import os, asyncio
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
MODEL = os.getenv("OPENAI_MODEL", os.getenv("MODEL", "gpt-4o-mini"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "160"))

try:
    # новый SDK
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    async def aquery(prompt: str) -> str:
        r = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Отвечай максимально кратко и по делу."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.6,
            max_tokens=MAX_TOKENS,
        )
        return (r.choices[0].message.content or "").strip()

except Exception:
    # старый SDK
    import openai
    openai.api_key = OPENAI_API_KEY

    def _sync_query(prompt: str) -> str:
        r = openai.ChatCompletion.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Отвечай максимально кратко и по делу."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.6,
            max_tokens=MAX_TOKENS,
        )
        return r["choices"][0]["message"]["content"].strip()

    async def aquery(prompt: str) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_query, prompt)

