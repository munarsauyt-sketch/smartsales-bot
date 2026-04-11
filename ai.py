from groq import Groq
from data import GROQ_API_KEY

client = Groq(api_key=GROQ_API_KEY)

async def ask_ai(user_message: str, system_prompt: str) -> str:
    try:
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            max_tokens=300,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Извините, ИИ временно недоступен. Попробуйте позже."
