
import os
import re
import json
import html
import random
import base64
from datetime import datetime, timezone

import requests


# -----------------------------
# SETTINGS
# -----------------------------

GEMINI_MODEL = "gemini-3.8-flash"

COMMONS_API = "https://commons.wikimedia.org/w/api.php"

GEMINI_API = (
    f"https://generativelanguage.googleapis.com/v1beta/"
    f"models/{GEMINI_MODEL}:generateContent"
)

HISTORY_FILE = "history.json"
CURRENT_IMAGE_FILE = "current_image.json"

HEADERS = {
    "User-Agent": "ChristmasMomentsBot/1.0 (personal project)"
}

SEARCH_QUERIES = [
    "Christmas beautiful winter landscape",
    "Christmas tree lights festive decorations",
    "Christmas village snow night",
    "Christmas cozy interior fireplace",
    "Christmas ornaments photography",
    "Christmas market winter lights"
]

MAX_CANDIDATES = 6


# -----------------------------
# HISTORY
# -----------------------------

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        return []


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as file:
        json.dump(history[-200:], file, ensure_ascii=False, indent=2)


# -----------------------------
# WIKIMEDIA SEARCH
# -----------------------------

def clean_metadata(value):
    if not value:
        return ""

    value = re.sub(r"<[^>]+>", " ", str(value))
    return html.unescape(value).strip()


def search_images(history):
    candidates = []
    seen = set()

    queries = SEARCH_QUERIES.copy()
    random.shuffle(queries)

    for query in queries:
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": 6,
            "gsrlimit": 20,
            "prop": "imageinfo",
            "iiprop": "url|mime|size|extmetadata",
            "iiurlwidth": 1200,
            "iiextmetadatafilter": (
                "Artist|Credit|LicenseShortName|LicenseUrl|ImageDescription"
            ),
            "format": "json"
        }

        response = requests.get(
            COMMONS_API,
            params=params,
            headers=HEADERS,
            timeout=30
        )
        response.raise_for_status()

        pages = response.json().get("query", {}).get("pages", {})

        if isinstance(pages, dict):
            pages = list(pages.values())

        for page in pages:
            title = page.get("title", "")

            if not title or title in history or title in seen:
                continue

            image_info = page.get("imageinfo", [{}])[0]
            metadata = image_info.get("extmetadata", {})

            image_url = image_info.get("thumburl")
            file_page = image_info.get("descriptionurl")

            if not image_url or not file_page:
                continue

            if image_info.get("mime") not in (
                "image/jpeg",
                "image/png",
                "image/webp"
            ):
                continue

            width = image_info.get("width", 0)
            height = image_info.get("height", 0)

            if width < 900 or height < 500:
                continue

            if width / height < 1.2:
                continue

            candidate = {
                "title": title,
                "image_url": image_url,
                "source_url": file_page,
                "description": clean_metadata(
                    metadata.get("ImageDescription", {}).get("value", "")
                ),
                "author": clean_metadata(
                    metadata.get("Artist", {}).get("value", "")
                ),
                "credit": clean_metadata(
                    metadata.get("Credit", {}).get("value", "")
                ),
                "license": clean_metadata(
                    metadata.get("LicenseShortName", {}).get("value", "")
                ),
                "license_url": clean_metadata(
                    metadata.get("LicenseUrl", {}).get("value", "")
                )
            }

            candidates.append(candidate)
            seen.add(title)

        if len(candidates) >= 25:
            break

    random.shuffle(candidates)

    print(f"Found {len(candidates)} unique candidates.")

    return candidates[:MAX_CANDIDATES]


# -----------------------------
# DOWNLOAD IMAGE
# -----------------------------

def download_image(candidate):
    response = requests.get(
        candidate["image_url"],
        headers=HEADERS,
        timeout=30
    )
    response.raise_for_status()

    content_type = response.headers.get(
        "Content-Type", ""
    ).split(";")[0].lower()

    if content_type not in (
        "image/jpeg",
        "image/png",
        "image/webp"
    ):
        raise ValueError("Unsupported image format")

    if len(response.content) > 5_000_000:
        raise ValueError("Image is too large")

    return response.content, content_type


# -----------------------------
# GEMINI SELECTION
# -----------------------------

def select_with_ai(candidates, api_key):
    parts = [
        {
            "text": (
                "You are an art director selecting beautiful Christmas "
                "photographs for a public Christmas-themed website.\n"
                "Look at all the images and choose exactly ONE.\n\n"
                "Prioritize:\n"
                "- beautiful and atmospheric composition;\n"
                "- genuine Christmas or winter holiday mood;\n"
                "- warm lights, snow, decorations, cozy scenes or "
                "magical winter landscapes;\n"
                "- high visual quality;\n"
                "- variety compared with ordinary Christmas stock photos.\n\n"
                "Reject unrelated images, screenshots, logos, "
                "watermarks and images with prominent text.\n\n"
                "Return ONLY the number of your chosen image. "
                "No explanation."
            )
        }
    ]

    for index, candidate in enumerate(candidates, start=1):
        image_bytes, mime_type = download_image(candidate)

        parts.append({
            "text": (
                f"\nImage {index}: {candidate['title']}\n"
                f"Description: {candidate['description'][:400]}"
            )
        })

        parts.append({
            "inline_data": {
                "mime_type": mime_type,
                "data": base64.b64encode(
                    image_bytes
                ).decode("utf-8")
            }
        })

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": parts
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 30
        }
    }

    response = requests.post(
    GEMINI_API,
    headers={"x-goog-api-key": api_key},
    json=payload,
    timeout=90
)

if not response.ok:
    print("Gemini error details:", response.text[:2000])
    raise RuntimeError(
        f"Gemini API error: HTTP {response.status_code}"
    )

    result = response.json()

    answer = result["candidates"][0]["content"]["parts"][0]["text"]

    print("Gemini answer:", answer)

    match = re.search(r"\b([1-6])\b", answer)

    if not match:
        raise ValueError("Gemini returned an invalid selection")

    selected_index = int(match.group(1)) - 1

    if selected_index >= len(candidates):
        raise ValueError("Selected image does not exist")

    return candidates[selected_index]


# -----------------------------
# MAIN
# -----------------------------

def main():
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing")

    history = load_history()

    candidates = search_images(history)

    if not candidates:
        raise RuntimeError("No suitable images found")

    selected = select_with_ai(candidates, api_key)

    result = {
        "image_url": selected["image_url"],
        "description": selected["description"] or selected["title"],
        "author": selected["author"] or selected["credit"] or "Unknown",
        "license": selected["license"],
        "license_url": selected["license_url"],
        "source_url": selected["source_url"],
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    with open(
        CURRENT_IMAGE_FILE,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(result, file, ensure_ascii=False, indent=2)

    history.append(selected["title"])
    save_history(history)

    print("Successfully selected:", selected["title"])
    print("Image updated!")


if __name__ == "__main__":
    main()
