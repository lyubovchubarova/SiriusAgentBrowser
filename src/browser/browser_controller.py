from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Playwright, Browser, BrowserContext, Page


@dataclass
class BrowserOptions:
    headless: bool = True              # False = окно видно
    browser_name: str = "chromium"     # chromium | firefox | webkit
    slow_mo_ms: int = 0                # для дебага, например 200
    viewport: Optional[dict] = None    # например {"width": 1280, "height": 720}


class BrowserController:
    def __init__(self, options: BrowserOptions | None = None):
        self.options = options or BrowserOptions()
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Browser is not started. Call start() first.")
        return self._page

    def start(self) -> "BrowserController":
        if self._browser:
            return self

        self._pw = sync_playwright().start()

        browser_type = getattr(self._pw, self.options.browser_name, None)
        if browser_type is None:
            raise ValueError(f"Unknown browser_name: {self.options.browser_name}")

        self._browser = browser_type.launch(
            headless=self.options.headless,
            slow_mo=self.options.slow_mo_ms,
        )

        self._context = self._browser.new_context(viewport=self.options.viewport)
        self._page = self._context.new_page()
        return self

    def open(self, url: str, wait_until: str = "domcontentloaded") -> "BrowserController":
        self.page.goto(url, wait_until=wait_until)
        return self

    def screenshot(self, path: str, full_page: bool = True) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(p), full_page=full_page)
        return str(p)

    def close(self) -> None:
        # закрываем в правильном порядке
        if self._context:
            self._context.close()
            self._context = None
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._pw:
            self._pw.stop()
            self._pw = None
        self._page = None
