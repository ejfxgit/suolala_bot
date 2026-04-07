import asyncio
import base64
import io
import logging
import os
from typing import Any, Dict, Iterable, Optional

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
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_TIMEOUT_SECONDS = 60


def _auth_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }


def _iter_modalities(model: Dict[str, Any]) -> Iterable[str]:
    raw_values = [
        model.get("modality"),
        model.get("input_modality"),
        model.get("output_modality"),
        model.get("input_modalities"),
        model.get("output_modalities"),
    ]
    architecture = model.get("architecture") or {}
    raw_values.extend(
        [
            architecture.get("modality"),
            architecture.get("input_modality"),
            architecture.get("output_modality"),
            architecture.get("input_modalities"),
            architecture.get("output_modalities"),
        ]
    )

    for value in raw_values:
        if not value:
            continue
        if isinstance(value, list):
            for item in value:
                if item:
                    yield str(item).lower()
        else:
            yield str(value).lower()


def _select_image_model() -> Optional[str]:
    response = requests.get(
        OPENROUTER_MODELS_URL,
        headers=_auth_headers(),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    models = response.json().get("data", [])

    for model in models:
        model_id = model.get("id")
        if not model_id:
            continue
        if any("image" in modality for modality in _iter_modalities(model)):
            return model_id
    return None


def _extract_image_payload(data: Dict[str, Any]) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {"url": None, "b64": None}

    choices = data.get("choices") or []
    for choice in choices:
        message = choice.get("message") or {}
        if isinstance(message.get("image_url"), str):
            result["url"] = message["image_url"]
            return result

        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                image_url = part.get("image_url") or part.get("url")
                if isinstance(image_url, dict):
                    image_url = image_url.get("url")
                if isinstance(image_url, str):
                    result["url"] = image_url
                    return result
                b64_json = part.get("b64_json") or part.get("base64")
                if isinstance(b64_json, str):
                    result["b64"] = b64_json
                    return result

        if isinstance(message.get("content"), str) and message["content"].startswith("http"):
            result["url"] = message["content"].strip()
            return result

    for image in data.get("images", []):
        if isinstance(image, dict):
            if isinstance(image.get("url"), str):
                result["url"] = image["url"]
                return result
            if isinstance(image.get("b64_json"), str):
                result["b64"] = image["b64_json"]
                return result

    return result


def _generate_image(prompt: str) -> Dict[str, Optional[str]]:
    image_model = _select_image_model()
    if not image_model:
        return {"error": "No image models available on this account"}

    payload = {
        "model": image_model,
        "messages": [
            {
                "role": "user",
                "content": f"Generate a high-quality image for: {prompt}",
            }
        ],
    }
    response = requests.post(
        OPENROUTER_CHAT_URL,
        headers=_auth_headers(),
        json=payload,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    parsed = _extract_image_payload(response.json())
    if not parsed["url"] and not parsed["b64"]:
        return {"error": "Image generation succeeded but no image payload was returned"}
    return parsed


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Use /generate <prompt> to create an image")


async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prompt = " ".join(context.args).strip()
    if not prompt:
        await update.message.reply_text("Usage: /generate <prompt>")
        return

    try:
        result = await asyncio.to_thread(_generate_image, prompt)
        if result.get("error"):
            await update.message.reply_text(result["error"])
            return

        image_url = result.get("url")
        if image_url:
            await update.message.reply_photo(photo=image_url)
            return

        image_b64 = result.get("b64")
        if image_b64:
            image_bytes = base64.b64decode(image_b64)
            image_file = io.BytesIO(image_bytes)
            image_file.name = "generated.png"
            await update.message.reply_photo(photo=image_file)
            return

        await update.message.reply_text("Image generation failed")
    except Exception as exc:
        logger.exception("Generation failed: %s", exc)
        await update.message.reply_text("Image generation failed")


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
