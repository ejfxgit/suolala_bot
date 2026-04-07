import logging
import os

import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "meta-llama/llama-3.1-8b-instruct"
SYSTEM_PROMPT = "You create viral image ideas, captions, and include a real Unsplash or Pexels image URL."


def generate_text(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"User prompt: {prompt}\n\n"
                    "Return ONLY this exact format:\n"
                    "Idea: <text>\n"
                    "Caption: <text>\n"
                    "Image URL: <link>\n"
                    "Rules: No image generation. No markdown. Text only. "
                    "Use a real free Unsplash or Pexels image URL."
                ),
            },
        ],
    }

    response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=45)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Use /generate <prompt>")


async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.message.reply_text("Usage: /generate <prompt>")
        return

    try:
        text = generate_text(prompt)
        await update.message.reply_text(text)
    except Exception as exc:
        logger.exception("Generation failed: %s", exc)
        await update.message.reply_text("Generation failed")


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("Missing BOT_TOKEN")
    if not OPENROUTER_API_KEY:
        raise RuntimeError("Missing OPENROUTER_API_KEY")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("generate", generate))
    app.run_polling()


if __name__ == "__main__":
    main()
