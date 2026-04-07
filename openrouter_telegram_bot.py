import asyncio
import base64
import os
from typing import Any, Optional

import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "sourcelfl/riverflow-v2-fast"


def _extract_base64_image(payload: dict[str, Any]) -> Optional[str]:
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return None

    for choice in choices:
        if not isinstance(choice, dict):
            continue

        message = choice.get("message")
        if not isinstance(message, dict):
            continue

        content = message.get("content")

        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue

                b64_json = part.get("b64_json") or part.get("base64")
                if isinstance(b64_json, str) and b64_json.strip():
                    return b64_json.strip()

                image_url = part.get("image_url")
                if isinstance(image_url, dict):
                    url = image_url.get("url")
                    if isinstance(url, str) and url.startswith("data:") and "," in url:
                        return url.split(",", 1)[1]
                elif isinstance(image_url, str) and image_url.startswith("data:") and "," in image_url:
                    return image_url.split(",", 1)[1]

        if isinstance(content, str):
            text = content.strip()
            if text.startswith("data:") and "," in text:
                return text.split(",", 1)[1]
            try:
                base64.b64decode(text, validate=True)
                return text
            except Exception:
                pass

    return None


def _generate_image_to_file(prompt: str) -> tuple[bool, str]:
    response = requests.post(
        OPENROUTER_CHAT_URL,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "modalities": ["image"],
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        },
        timeout=180,
    )

    try:
        data = response.json()
    except Exception:
        data = {"raw_text": response.text}

    if not response.ok:
        print(data)
        return False, "OpenRouter request failed"

    image_b64 = _extract_base64_image(data)
    if not image_b64:
        print(data)
        return False, "Failed to extract base64 image"

    try:
        image_bytes = base64.b64decode(image_b64)
        with open("output.png", "wb") as f:
            f.write(image_bytes)
    except Exception:
        print(data)
        return False, "Failed to decode/save image"

    return True, "ok"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Use /generate <prompt> to create an image")


async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.message.reply_text("Usage: /generate <prompt>")
        return

    thinking = await update.message.reply_text("Generating image...")

    ok, message = await asyncio.to_thread(_generate_image_to_file, prompt)

    try:
        await thinking.delete()
    except Exception:
        pass

    if not ok:
        await update.message.reply_text(f"Image generation failed: {message}")
        return

    await context.bot.send_photo(update.effective_chat.id, open("output.png", "rb"))


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
