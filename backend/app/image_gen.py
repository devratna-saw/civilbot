"""
Free, keyless AI image generation via Pollinations.ai - a public
text-to-image endpoint that needs no API key or billing.

Kept separate from gemini_client.py: Gemini's own image models
(gemini-*-image, nano-banana) have a free-tier quota of zero on this
project and require billing to be enabled, which the user explicitly
wants to avoid for now. Swapping providers later is a one-file change.
"""
from __future__ import annotations

import urllib.parse

import requests

_BASE_URL = "https://image.pollinations.ai/prompt/"
_TIMEOUT_SECONDS = 20
_MAX_ATTEMPTS = 2


class ImageGenError(Exception):
    pass


def generate_image(prompt: str, width: int = 768, height: int = 512, seed: int | None = None) -> bytes:
    prompt = prompt.strip()
    if not prompt:
        raise ImageGenError("prompt must not be empty")
    if len(prompt) > 500:
        raise ImageGenError("prompt too long (500 char limit)")

    params = {"width": width, "height": height, "nologo": "true"}
    if seed is not None:
        params["seed"] = seed
    url = _BASE_URL + urllib.parse.quote(prompt)

    last_error: str | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = requests.get(url, params=params, headers={"User-Agent": "CivilBot/1.0"}, timeout=_TIMEOUT_SECONDS)
        except requests.RequestException as e:
            last_error = str(e)
            continue  # this free shared service is sometimes just slow - one retry often succeeds

        if resp.status_code in (429, 500, 502, 503, 504):
            last_error = f"upstream returned {resp.status_code}"
            continue

        try:
            resp.raise_for_status()
        except requests.RequestException as e:
            raise ImageGenError(f"Image generation service error: {e}") from e

        content_type = resp.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            raise ImageGenError("Image generation service returned an unexpected response")
        return resp.content

    raise ImageGenError(
        "The free image service is overloaded or slow right now (it's a shared public quota, not "
        f"yours, and this ran on Render's servers so it can be less reliable than from a browser) - "
        f"wait a bit and try again. (last error: {last_error})"
    )
