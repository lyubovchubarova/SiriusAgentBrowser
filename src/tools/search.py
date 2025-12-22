import base64
import os
import xml.etree.ElementTree as ET
from typing import Any

import requests


def yandex_search(
    query: str, folder_id: str | None = None, api_key: str | None = None
) -> list[dict[str, str]] | None:
    """
    Performs a search query using Yandex.Cloud Search API v2.
    Returns a list of dictionaries with 'title', 'url', and 'snippet'.
    Returns None if the API call fails.
    """
    folder_id = folder_id or os.getenv("YANDEX_CLOUD_FOLDER")
    api_key = api_key or os.getenv("YANDEX_CLOUD_API_KEY")

    if not folder_id or not api_key:
        print("Warning: YANDEX_CLOUD_FOLDER or YANDEX_CLOUD_API_KEY not set.")
        return []

    # API v2 Endpoint
    url = "https://searchapi.api.cloud.yandex.net/v2/web/search"

    headers = {
        "Authorization": f"Api-Key {api_key}",
        "Content-Type": "application/json",
    }

    # Request body for v2
    payload = {
        "folderId": folder_id,
        "query": {
            "searchType": "SEARCH_TYPE_RU",
            "queryText": query,
            "familyMode": "FAMILY_MODE_NONE",
            "page": 0,
        },
        # We can specify grouping/sorting here if needed, but defaults are usually fine.
        # To match previous behavior (groupby=attr=d.mode=deep.groups-on-page=10.docs-in-group=1):
        "groupSpec": {
            "groupsOnPage": 10,
            "docsInGroup": 1,
            "groupsMode": "GROUPS_MODE_DEEP",
        },
        "sortSpec": {
            "sortMode": "SORT_MODE_BY_RELEVANCE",
            "sortOrder": "SORT_ORDER_DESC",
        },
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()

        # v2 returns Base64 encoded XML in 'rawData'
        if "rawData" not in data:
            print("Error: 'rawData' not found in API v2 response.")
            return None

        content = base64.b64decode(data["rawData"])

    except Exception as e:
        print(f"Error performing search (v2): {e}")
        if "response" in locals() and hasattr(response, "text"):
            print(f"Response text: {response.text}")
        return None

    try:
        root = ET.fromstring(content)
        # print(content.decode('utf-8')[:1000]) # Debug: print start of XML

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
                passages_elem = doc.find("passages")

                # Helper to extract text from element and its children
                def get_text(elem: Any) -> str:
                    if elem is None:
                        return ""
                    return "".join(elem.itertext())

                snippet = get_text(headline_elem)
                if not snippet and passages_elem is not None:
                    snippet = " ... ".join(
                        [get_text(p) for p in passages_elem.findall("passage")]
                    )

                item = {
                    "url": (url_elem.text or "") if url_elem is not None else "",
                    "title": get_text(title_elem),
                    "snippet": snippet,
                }
                results.append(item)

        return results

    except ET.ParseError as e:
        print(f"Error parsing XML: {e}")
        return []
