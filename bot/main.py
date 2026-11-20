
import os
import re
import json
import html
import random
import base64
import time

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

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
    "User-Agent": (
        "ChristmasMomentsBot/1.0 "
        "(https://katissa2004.github.io/christmas-moments/)"
    )
}

SEARCH_QUERIES = [
    "Christmas beautiful winter landscape",
    "Christmas tree lights festive decorations",
    "Christmas village snow night",
    "Christmas cozy interior fireplace",
    "Christmas ornaments photography",
    "Christmas market winter lights"
]

MAX_CANDIDATES = 2


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
    with open("history.json", "w", encoding="utf-8") as file:
        json.dump(
            history[-200:],
            file,
            ensure_ascii=False,
            indent=2
        )


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

        pages = response.json().get(
            "query", {}
        ).get("pages", {})

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
                    metadata.get(
                        "ImageDescription", {}
                    ).get("value", "")
                ),
                "author": clean_metadata(
                    metadata.get("Artist", {}).get("value", "")
                ),
                "credit": clean_metadata(
                    metadata.get("Credit", {}).get("value", "")
                ),
                "license": clean_metadata(
                    metadata.get(
                        "LicenseShortName", {}
                    ).get("value", "")
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

    selected_candidates = candidates[:MAX_CANDIDATES]

    print(
        f"Selected {len(selected_candidates)} candidates "
        f"for Gemini."
    )

    return selected_candidates


# -----------------------------
# DOWNLOAD IMAGE
# -----------------------------

def download_image(candidate):
    url = candidate["image_url"]

    for attempt in range(2):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=30
            )

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")

                if retry_after:
                    try:
                        wait = int(retry_after)
                    except ValueError:
                        try:
                            retry_date = parsedate_to_datetime(
                                retry_after
                            )

                            wait = max(
                                0,
                                int(
                                    (
                                        retry_date - datetime.now(
                                            retry_date.tzinfo
                                        )
                                    ).total_seconds()
                                )
                            )
                        except (ValueError, TypeError):
                            wait = 60
                else:
                    wait = 60

                print(
                    f"Wikimedia rate limit. Retry after {wait}s."
                )

                if attempt == 0 and wait <= 30:
                    time.sleep(wait)
                    continue

                raise RuntimeError(
                    f"Wikimedia rate limited us. "
                    f"Please retry after {wait} seconds."
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

        except requests.RequestException as error:
            if attempt == 1:
                raise RuntimeError(
                    f"Could not download image: {error}"
                ) from error

            time.sleep(5)


# -----------------------------
# GEMINI SELECTION
# -----------------------------

def select_with_ai(candidates, api_key):

    parts = [
        {
            "text": (
                "You are an art director selecting beautiful Christmas "
                "photographs for a public Christmas-themed website.\n"
                "Choose exactly ONE image.\n\n"
                "Prioritize:\n"
                "- beautiful and atmospheric composition;\n"
                "- genuine Christmas or winter holiday mood;\n"
                "- warm lights, snow and festive decorations;\n"
                "- cozy scenes and magical winter landscapes;\n"
                "- high visual quality.\n\n"
                "Reject unrelated images, screenshots, logos, "
                "watermarks and images with prominent text.\n\n"
                "Return ONLY the number of your chosen image."
            )
        }
    ]

    downloaded_candidates = []

    for candidate in candidates:
        try:
            if downloaded_candidates:
                time.sleep(3)

            image_bytes, mime_type = download_image(candidate)

            downloaded_candidates.append(candidate)

            number = len(downloaded_candidates)

            parts.append({
                "text": (
                    f"\nImage {number}: {candidate['title']}\n"
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

        except Exception as error:
            print(
                f"Skipping unavailable image "
                f"{candidate['title']}: {error}"
            )

    if not downloaded_candidates:
        raise RuntimeError(
            "Could not download any candidate images."
        )

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

    response = None

    retryable_statuses = (429, 500, 502, 503, 504)

    for attempt in range(4):

        try:
            print(
                f"Sending request to Gemini "
                f"(attempt {attempt + 1}/4)..."
            )

            response = requests.post(
                GEMINI_API,
                headers={
                    "x-goog-api-key": api_key,
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=(20, 120)
            )

            if response.status_code in retryable_statuses:

                if attempt == 3:
                    break

                wait = 10 * (2 ** attempt)

                print(
                    f"Gemini returned HTTP {response.status_code}. "
                    f"Retrying in {wait} seconds..."
                )

                time.sleep(wait)
                continue

            break

        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError
        ) as error:

            if attempt == 3:
                raise RuntimeError(
                    f"Gemini request failed after 4 attempts: {error}"
                ) from error

            wait = 10 * (2 ** attempt)

            print(
                f"Gemini connection error: {error}. "
                f"Retrying in {wait} seconds..."
            )

            time.sleep(wait)

    if response is None:
        raise RuntimeError(
            "Gemini did not return a response."
        )

    if not response.ok:
        print("Gemini request URL:", GEMINI_API)
        print("Gemini error details:", response.text[:4000])

        raise RuntimeError(
            f"Gemini API error: HTTP {response.status_code}"
        )

    result = response.json()

    try:
        answer = (
            result["candidates"][0]
            ["content"]["parts"][0]["text"]
        )
    except (KeyError, IndexError, TypeError):
        print("Unexpected Gemini response:", result)

        raise RuntimeError(
            "Gemini returned an unexpected response."
        )

    print("Gemini answer:", answer)

    match = re.search(r"\b([1-9]\d*)\b", answer)

    if not match:
        raise ValueError(
            "Gemini returned an invalid selection."
        )

    selected_index = int(match.group(1)) - 1

    if selected_index >= len(downloaded_candidates):
        raise ValueError(
            "Gemini selected an image that does not exist."
        )

    return downloaded_candidates[selected_index]


# -----------------------------
# MAIN
# -----------------------------

def main():

    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is missing."
        )

    history = load_history()

    candidates = search_images(history)

    if not candidates:
        raise RuntimeError(
            "No suitable images found."
        )

    selected = select_with_ai(
        candidates,
        api_key
    )

    result = {
        "image_url": selected["image_url"],
        "description": (
            selected["description"] or selected["title"]
        ),
        "author": (
            selected["author"] or selected["credit"] or "Unknown"
        ),
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
        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2
        )

    history.append(selected["title"])
    save_history(history)

    print("Successfully selected:", selected["title"])
    print("Image updated!")


if __name__ == "__main__":
    main()
