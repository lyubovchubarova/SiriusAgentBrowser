import os
import xml.etree.ElementTree as ET
from typing import Any

import requests


def yandex_search(
    query: str, folder_id: str | None = None, api_key: str | None = None
) -> list[dict[str, str]]:
    """
    Performs a search query using Yandex.Cloud Search API (Yandex.XML).
    Returns a list of dictionaries with 'title', 'url', and 'snippet'.
    """
    folder_id = folder_id or os.getenv("YANDEX_CLOUD_FOLDER")
    api_key = api_key or os.getenv("YANDEX_CLOUD_API_KEY")

    if not folder_id or not api_key:
        print("Warning: YANDEX_CLOUD_FOLDER or YANDEX_CLOUD_API_KEY not set.")
        return []

    url = "https://yandex.ru/search/xml"

    params = {
        "folderid": folder_id,
        "apikey": api_key,
        "query": query,
        "l10n": "ru",  # Prefer Russian as per context, or make it configurable
        "sortby": "rlv",
        "filter": "none",
        "groupby": "attr=d.mode=deep.groups-on-page=10.docs-in-group=1",
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        content = response.content
    except Exception as e:
        print(f"Error performing search: {e}")
        return []

    try:
        root = ET.fromstring(content)

        # Check for error
        error = root.find("response/error")
        if error is None:
            error = root.find("error")

        if error is not None:
            print(f"API Error: {error.text}")
            return []

        results = []

        for group in root.findall(".//group"):
            doc = group.find("doc")
            if doc is not None:
                url_elem = doc.find("url")
                title_elem = doc.find("title")
                headline_elem = doc.find("headline")

                # Helper to extract text from element and its children
                def get_text(elem: Any) -> str:
                    if elem is None:
                        return ""
                    return "".join(elem.itertext())

                item = {
                    "url": (url_elem.text or "") if url_elem is not None else "",
                    "title": get_text(title_elem),
                    "snippet": get_text(headline_elem),
                }
                results.append(item)

        return results

    except ET.ParseError as e:
        print(f"Error parsing XML: {e}")
        return []
