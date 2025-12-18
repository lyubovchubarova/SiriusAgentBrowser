from .browser_controller import BrowserController, BrowserOptions

if __name__ == "__main__":
    bc = BrowserController(BrowserOptions(headless=False, slow_mo_ms=100)).start()
    bc.open("https://wikipedia.org")
    bc.screenshot_with_bboxes("screenshots/wiki.png", "screenshots/wiki_meta.json")
    input("Press Enter to close the browser...")
    bc.close()
