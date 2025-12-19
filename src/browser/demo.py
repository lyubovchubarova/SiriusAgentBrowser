from .browser_controller import BrowserController, BrowserOptions

if __name__ == "__main__":
    bc = BrowserController(BrowserOptions(headless=False, slow_mo_ms=100)).start()
    bc.open("https://wikipedia.org")
    meta = bc.screenshot_with_bboxes("wiki_screenshot.png")

    # Выводим элементы
    for el in meta["elements"][:5]:  # первые 5
        print(f"{el['id']}: {el['type']} - {el['text']}")

    # Кликаем по первой ссылке (обычно E1)
    bc.click_by_id("E1", timeout_ms=30000)

    input("Press Enter to close the browser...")
    bc.close()
