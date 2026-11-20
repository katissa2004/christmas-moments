                    f"Backup model connection error: {error}. "
                    "Retrying in 10 seconds..."
                )
                time.sleep(10)

        if fallback_response is not None:
            response = fallback_response
            response_api = GEMINI_FALLBACK_API

    if response is None:
        raise RuntimeError(
            "Gemini did not return a response."
        )

    if not response.ok:
        print("Gemini request URL:", response_api)
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
