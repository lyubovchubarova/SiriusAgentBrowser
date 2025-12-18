from .browser_controller import BrowserController, BrowserOptions

if __name__ == "__main__":
    bc = BrowserController(BrowserOptions(headless=False, slow_mo_ms=100)).start()
    bc.open("https://wikipedia.org")
    bc.screenshot("screenshots/wiki.png")
    bc.close()
