from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)


@dataclass
class BrowserOptions:
    headless: bool = True  # False = окно видно
    browser_name: str = "chromium"  # chromium | firefox | webkit
    slow_mo_ms: int = 0  # для дебага, например 200
    viewport: dict | None = None  # например {"width": 1280, "height": 720}


class BrowserController:
    def __init__(self, options: BrowserOptions | None = None):
        self.options = options or BrowserOptions()
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Browser is not started. Call start() first.")
        return self._page

    def start(self) -> BrowserController:
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

    def open(self, url: str, wait_until: str = "domcontentloaded") -> BrowserController:
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

    def screenshot_with_bboxes(
        self,
        image_path: str,
        meta_path: str | None = None,
        full_page: bool = True,
        max_elements: int = 400,
        padding: int = 2,
    ) -> dict:
        """
        Делает скриншот и рисует bbox + id всех кликабельных элементов.
        Возвращает dict с метаданными.
        """

        # 1) Собираем элементы в браузере
        js = r"""
        () => {
          const selectors = [
            'a[href]',
            'button',
            'input',
            'textarea',
            'select',
            '[role="button"]',
            '[role="link"]',
            '[onclick]',
            '[tabindex]:not([tabindex="-1"])'
          ];

          const uniq = (arr) => Array.from(new Set(arr));
          const nodes = uniq(selectors.flatMap(s => Array.from(document.querySelectorAll(s))));

          const isVisible = (el) => {
            const style = window.getComputedStyle(el);
            if (!style) return false;
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;

            const r = el.getBoundingClientRect();
            if (r.width < 2 || r.height < 2) return false;
            if (r.bottom < 0 || r.right < 0) return false;
            if (r.top > (window.innerHeight || document.documentElement.clientHeight)) return false;
            if (r.left > (window.innerWidth || document.documentElement.clientWidth)) return false;
            return true;
          };

          const getType = (el) => {
            const tag = el.tagName.toLowerCase();
            if (tag === 'a') return 'link';
            if (tag === 'button') return 'button';
            if (tag === 'input') return `input:${(el.getAttribute('type') || 'text').toLowerCase()}`;
            if (tag === 'textarea') return 'textarea';
            if (tag === 'select') return 'select';
            const role = (el.getAttribute('role') || '').toLowerCase();
            if (role) return `role:${role}`;
            if (el.hasAttribute('onclick')) return 'onclick';
            return tag;
          };

          const getText = (el) => {
            const tag = el.tagName.toLowerCase();
            if (tag === 'input' || tag === 'textarea') {
              return (el.getAttribute('placeholder') || el.getAttribute('aria-label') || el.value || '').trim().slice(0, 80);
            }
            return (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ').slice(0, 80);
          };

          const out = [];
          let idx = 1;
          for (const el of nodes) {
            if (!isVisible(el)) continue;

            const r = el.getBoundingClientRect();
            const id = `E${idx++}`;
            el.dataset.pwBboxId = id;

            out.push({
              id,
              type: getType(el),
              text: getText(el),
              bbox: { x: r.x, y: r.y, w: r.width, h: r.height }
            });

            if (out.length >= 2000) break;
          }

          return {
            devicePixelRatio: window.devicePixelRatio || 1,
            viewport: { w: window.innerWidth, h: window.innerHeight },
            elements: out
          };
        }
        """

        data = self.page.evaluate(js)

        # Ограничение на случай “страницы-ад”
        elements = data["elements"][:max_elements]

        # 2) Скриншот (оригинал)
        img_path = Path(image_path)
        img_path.parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(img_path), full_page=full_page)

        # 3) Рисуем bbox на скрине
        dpr = float(data.get("devicePixelRatio", 1.0))  # важный множитель
        im = Image.open(str(img_path)).convert("RGBA")
        draw = ImageDraw.Draw(im)

        # Шрифт: пробуем нормальный, иначе дефолт
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 14)
        except Exception:
            font = ImageFont.load_default()

        meta = {
            "devicePixelRatio": dpr,
            "full_page": full_page,
            "image": str(img_path),
            "elements": [],
        }

        for el in elements:
            b = el["bbox"]
            # bbox в CSS-пикселях -> в пиксели картинки
            x1 = int((b["x"] - padding) * dpr)
            y1 = int((b["y"] - padding) * dpr)
            x2 = int((b["x"] + b["w"] + padding) * dpr)
            y2 = int((b["y"] + b["h"] + padding) * dpr)

            # рамка
            draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0, 255), width=3)

            # подпись id (плашка)
            label = el["id"]
            tw, th = draw.textbbox((0, 0), label, font=font)[2:]
            pad = 4
            lx1, ly1 = x1, max(0, y1 - th - pad * 2)
            lx2, ly2 = x1 + tw + pad * 2, ly1 + th + pad * 2
            draw.rectangle([lx1, ly1, lx2, ly2], fill=(255, 0, 0, 200))
            draw.text(
                (lx1 + pad, ly1 + pad), label, font=font, fill=(255, 255, 255, 255)
            )

            meta["elements"].append(
                {
                    "id": el["id"],
                    "type": el["type"],
                    "text": el["text"],
                    "bbox_css": el["bbox"],
                    "bbox_px": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                }
            )

        # сохраняем отрисованный скриншот (перезаписываем)
        im = im.convert("RGB")
        im.save(str(img_path))

        # 4) json мета (опционально)
        if meta_path is None:
            meta_path = str(img_path.with_suffix(".json"))
        mp = Path(meta_path)
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return meta
