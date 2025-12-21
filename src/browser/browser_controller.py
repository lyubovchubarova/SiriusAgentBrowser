from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    ViewportSize,
    sync_playwright,
)


@dataclass
class BrowserOptions:
    headless: bool = True  # False = окно видно
    browser_name: str = "chromium"  # chromium | firefox | webkit
    slow_mo_ms: int = 0  # для дебага, например 200
    viewport: ViewportSize | None = None  # {"width": 1280, "height": 720}
    cdp_url: str | None = (
        None  # URL для подключения к существующему браузеру (например, http://localhost:9222)
    )


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

    def is_extension_installed(self, name: str) -> bool:
        """
        Проверяет, установлено ли расширение с заданным именем.
        Использует CDP Target.getTargets.
        """
        if not self._browser:
            return False

        try:
            # Подключаемся к CDP на уровне браузера
            # Note: connect_over_cdp returns a Browser, which supports new_browser_cdp_session
            # But standard launch() might not expose it easily in all versions without args.
            # However, since we are mostly interested in the 'connect_over_cdp' case for the extension check:

            # For connect_over_cdp (which we use for the agent), this should work.
            # If it fails, we might need to try context-level session.
            try:
                client = self._browser.new_browser_cdp_session()
            except Exception:
                # Fallback: try to get session from a page if available
                if self._context and self._context.pages:
                    client = self._context.new_cdp_session(self._context.pages[0])
                elif self._page and self._context:
                    client = self._context.new_cdp_session(self._page)
                else:
                    # Create a temp page to get CDP access if needed?
                    # Better to just return False or log warning if we can't get CDP.
                    print("Could not create CDP session to check extensions.")
                    return False

            targets = client.send("Target.getTargets")

            # Debug output to understand what targets are visible
            print(f"DEBUG: Checking targets for extension '{name}'")
            found_titles = []
            for target in targets.get("targetInfos", []):
                t_title = target.get("title", "")
                t_type = target.get("type", "")
                t_url = target.get("url", "")
                found_titles.append(f"[{t_type}] {t_title} ({t_url})")

                # Check by title
                if name in t_title:
                    try:
                        client.detach()
                    except Exception:
                        pass
                    return True

                # Check by URL (fallback if title is missing or different)
                # Our extension has sidepanel.html and offscreen.html
                if "chrome-extension://" in t_url and (
                    "sidepanel.html" in t_url or "offscreen.html" in t_url
                ):
                    # Double check if it might be another extension?
                    # But usually we only have one sidepanel.html active for this agent.
                    # Let's assume it's ours if we can't match by name.
                    print(f"DEBUG: Found extension by URL: {t_url}")
                    try:
                        client.detach()
                    except Exception:
                        pass
                    return True

            # Only print if not found to avoid spam when working
            print(f"DEBUG: Extension not found. Visible targets: {found_titles}")

            try:
                client.detach()
            except Exception:
                pass

        except Exception as e:
            print(f"Error checking extension: {e}")
            return False

        return False

    def start(self) -> BrowserController:
        if self._browser:
            return self

        self._pw = sync_playwright().start()

        if self.options.cdp_url:
            print(f"Connecting to existing browser at {self.options.cdp_url}")
            # Подключаемся к существующему браузеру через CDP
            self._browser = self._pw.chromium.connect_over_cdp(self.options.cdp_url)

            # Пытаемся использовать существующий контекст или создаем новый
            if self._browser.contexts:
                self._context = self._browser.contexts[0]
            else:
                self._context = self._browser.new_context(
                    viewport=self.options.viewport
                )
        else:
            browser_type = getattr(self._pw, self.options.browser_name, None)
            if browser_type is None:
                raise ValueError(f"Unknown browser_name: {self.options.browser_name}")

            self._browser = browser_type.launch(
                headless=self.options.headless,
                slow_mo=self.options.slow_mo_ms,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                    "--disable-browser-side-navigation",
                    "--disable-gpu",
                ],
            )

            self._context = self._browser.new_context(
                viewport=self.options.viewport,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )

        # Inject cursor visualization
        js_cursor = """
            window.addEventListener('DOMContentLoaded', () => {
                if (document.getElementById('playwright-cursor')) return;
                const cursor = document.createElement('div');
                cursor.id = 'playwright-cursor';
                cursor.style.position = 'fixed';
                cursor.style.top = '0';
                cursor.style.left = '0';
                cursor.style.width = '20px';
                cursor.style.height = '20px';
                cursor.style.backgroundColor = 'rgba(255, 0, 0, 0.5)';
                cursor.style.borderRadius = '50%';
                cursor.style.pointerEvents = 'none';
                cursor.style.zIndex = '2147483647';
                cursor.style.transition = 'transform 0.1s ease';
                document.body.appendChild(cursor);

                document.addEventListener('mousemove', (e) => {
                    cursor.style.transform = `translate(${e.clientX - 10}px, ${e.clientY - 10}px)`;
                });

                document.addEventListener('click', () => {
                    cursor.style.backgroundColor = 'rgba(0, 255, 0, 0.5)';
                    cursor.style.transform += ' scale(0.8)';
                    setTimeout(() => {
                        cursor.style.backgroundColor = 'rgba(255, 0, 0, 0.5)';
                        cursor.style.transform = cursor.style.transform.replace(' scale(0.8)', '');
                    }, 150);
                });
            });
        """
        self._context.add_init_script(js_cursor)

        # Anti-detection script (Stealth Mode)
        js_stealth = """
            // 1. Pass the Webdriver Test.
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // 2. Pass the Chrome Test.
            if (!window.chrome) {
                window.chrome = {
                    runtime: {}
                };
            }

            // 3. Pass the Permissions Test.
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                Promise.resolve({ state: 'denied' }) :
                originalQuery(parameters)
            );

            // 4. Pass the Plugins Test.
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });

            // 5. Pass the Languages Test.
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en'],
            });
        """
        self._context.add_init_script(js_stealth)

        # Try to use an existing page instead of opening a new blank one
        if self._context.pages:
            # Filter out extension pages (background pages, side panels, etc.)
            # They usually have 'chrome-extension://' scheme
            valid_pages = [
                p
                for p in self._context.pages
                if not p.url.startswith("chrome-extension://")
                and not p.url.startswith("devtools://")
            ]

            if valid_pages:
                # Use the most recently active VALID page
                self._page = valid_pages[-1]
                print(f"Attached to existing page: {self._page.url}")
            else:
                # If only extension pages exist, create a new normal page
                print("Only extension pages found. Creating new page.")
                self._page = self._context.new_page()
        else:
            self._page = self._context.new_page()

        return self

    def get_element_details(self, selector: str) -> str:
        """
        Returns details about an element (text, outerHTML) for inspection.
        """
        try:
            # Try ID first if it looks like E123
            if re.match(r"^E\d+$", selector):
                loc = self.page.locator(f"[data-pw-bbox-id='{selector}']").first
            else:
                loc = self.page.locator(selector).first

            if not loc.is_visible():
                return f"Element '{selector}' not visible or not found."

            text = loc.text_content() or ""
            html = loc.evaluate("el => el.outerHTML")
            # Truncate HTML if too long
            if len(html) > 1000:
                html = html[:1000] + "... (truncated)"

            return f"Element Details:\nText: {text.strip()}\nHTML Snippet: {html}"
        except Exception as e:
            return f"Error inspecting '{selector}': {e}"

    def open(
        self,
        url: str,
        wait_until: Literal[
            "commit", "domcontentloaded", "load", "networkidle"
        ] = "domcontentloaded",
    ) -> BrowserController:
        self.page.goto(url, wait_until=wait_until)
        return self

    def screenshot(self, path: str, viewport_only: bool = True) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(p), full_page=not viewport_only)
        return str(p)

    def get_accessibility_tree(self) -> str:
        """
        Returns a simplified text representation of the accessibility tree.
        Useful for LLM planning.
        """
        try:
            snapshot = self.page.accessibility.snapshot()  # type: ignore

            def process_node(node: dict[str, Any], depth: int = 0) -> str:
                indent = "  " * depth
                role = node.get("role", "unknown")
                name = node.get("name", "")
                text = f"{indent}- [{role}] {name}"

                children = node.get("children", [])
                # Limit depth and children to avoid huge prompts
                if depth > 5:
                    return text

                child_texts = []
                for child in children[:20]:  # Limit siblings
                    child_texts.append(process_node(child, depth + 1))

                if child_texts:
                    return text + "\n" + "\n".join(child_texts)
                return text

            if snapshot:
                return process_node(snapshot)
            return "Accessibility tree empty"
        except Exception as e:
            return f"Error getting accessibility tree: {e}"

    def screenshot_with_bboxes(
        self,
        image_path: str,
        meta_path: str | None = None,
        max_elements: int = 400,
        padding: int = 2,
    ) -> dict[str, Any]:
        """
        Скриншот ТОЛЬКО видимой части (viewport) + bbox кликабельных элементов + id.
        Сохраняет картинку и json с метаданными.
        """

        js = r"""
        () => {
          const selectors = [
            'a[href]',
            'button',
            'input',
            'textarea',
            'select',
            '[role="button"]',
            '[role="link"]',            '[role="checkbox"]',
            '[role="radio"]',
            '[role="tab"]',            '[onclick]',
            '[tabindex]:not([tabindex="-1"])'
          ];

          const uniq = (arr) => Array.from(new Set(arr));
          const nodes = uniq(selectors.flatMap(s => Array.from(document.querySelectorAll(s))));

          const isVisible = (el) => {
            const style = window.getComputedStyle(el);
            if (!style) return false;
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;

            const r = el.getBoundingClientRect();
            // Smart Filtering: Increase min size to avoid noise (was 2x2)
            if (r.width < 8 || r.height < 8) return false;

            // строго в пределах viewport (мы рисуем только по видимой части)
            if (r.bottom <= 0 || r.right <= 0) return false;
            if (r.top >= window.innerHeight || r.left >= window.innerWidth) return false;

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
              return (el.getAttribute('placeholder') || el.getAttribute('aria-label') || el.value || '')
                .trim().slice(0, 80);
            }
            return (el.innerText || el.textContent || el.getAttribute('aria-label') || '')
              .trim().replace(/\s+/g, ' ').slice(0, 80);
          };

          const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

          const out = [];
          let idx = 1;
          for (const el of nodes) {
            if (!isVisible(el)) continue;
            if (el.getAttribute('aria-hidden') === 'true') continue;

            const r = el.getBoundingClientRect();

            // обрезаем bbox границами viewport, чтобы не рисовать за пределами
            const x = clamp(r.x, 0, window.innerWidth);
            const y = clamp(r.y, 0, window.innerHeight);
            const x2 = clamp(r.x + r.width, 0, window.innerWidth);
            const y2 = clamp(r.y + r.height, 0, window.innerHeight);

            const w = x2 - x;
            const h = y2 - y;
            
            // Smart Filtering: Double check size after clamping
            if (w < 8 || h < 8) continue;

            const id = `E${idx++}`;
            el.dataset.pwBboxId = id;

            const attrs = {};
            if (el.tagName.toLowerCase() === 'a') {
                attrs.href = el.getAttribute('href') || '';
            }
            if (el.tagName.toLowerCase() === 'input') {
                attrs.placeholder = el.getAttribute('placeholder') || '';
                attrs.value = el.value || '';
            }

            out.push({
              id,
              type: getType(el),
              text: getText(el),
              bbox: { x, y, w, h },
              attributes: attrs
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
        elements = data["elements"][:max_elements]

        # Optimization: If we don't strictly need the screenshot file on disk for the Planner (text-only),
        # we could skip the drawing part. But the Orchestrator currently expects the file to exist.
        # Let's keep it but optimize:
        # 1. Don't convert to RGBA if not needed (RGB is faster)
        # 2. Use a faster drawing method or skip if headless?
        # For now, let's just return the data if image_path is None (refactoring needed)

        # If image_path is "SKIP_SCREENSHOT", we just return the elements
        if image_path == "SKIP_SCREENSHOT":
            return {
                "devicePixelRatio": float(data.get("devicePixelRatio", 1.0)),
                "viewport_only": True,
                "image": "",
                "viewport": data.get("viewport"),
                "elements": elements,
            }

        img_path = Path(image_path)
        img_path.parent.mkdir(parents=True, exist_ok=True)

        # ВАЖНО: только viewport
        self.page.screenshot(path=str(img_path), full_page=False)

        dpr = float(data.get("devicePixelRatio", 1.0))
        im = Image.open(str(img_path)).convert("RGB")  # RGB is faster than RGBA
        draw = ImageDraw.Draw(im)

        try:
            font: Any = ImageFont.truetype("DejaVuSans.ttf", 14)
        except Exception:
            font = ImageFont.load_default()

        meta = {
            "devicePixelRatio": dpr,
            "viewport_only": True,
            "image": str(img_path),
            "viewport": data.get("viewport"),
            "elements": [],
        }

        def clamp_px(v: int, lo: int, hi: int) -> int:
            return max(lo, min(hi, v))

        W, H = im.size

        for el in elements:
            b = el["bbox"]

            x1 = int((b["x"] - padding) * dpr)
            y1 = int((b["y"] - padding) * dpr)
            x2 = int((b["x"] + b["w"] + padding) * dpr)
            y2 = int((b["y"] + b["h"] + padding) * dpr)

            # на всякий случай ограничим рамки размерами изображения
            x1 = clamp_px(x1, 0, W - 1)
            y1 = clamp_px(y1, 0, H - 1)
            x2 = clamp_px(x2, 0, W - 1)
            y2 = clamp_px(y2, 0, H - 1)
            if x2 <= x1 or y2 <= y1:
                continue

            draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0, 255), width=3)

            label = el["id"]
            # textbbox returns (l,t,r,b)
            tb = draw.textbbox((0, 0), label, font=font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
            pad = 4

            lx1 = x1
            ly1 = max(0, y1 - th - pad * 2)
            lx2 = clamp_px(int(x1 + tw + pad * 2), 0, W - 1)
            ly2 = clamp_px(int(ly1 + th + pad * 2), 0, H - 1)

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

        im.convert("RGB").save(str(img_path))

        if meta_path is None:
            meta_path = str(img_path.with_suffix(".json"))
        mp = Path(meta_path)
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return meta

    def handle_popups(self) -> bool:
        """
        Пытается закрыть всплывающие окна (cookie banners, promo popups) через JS.
        Возвращает True, если что-то было закрыто.
        """
        js = r"""
        () => {
            const closeSelectors = [
                'button[aria-label="Close"]',
                'button[aria-label="close"]',
                'button[aria-label="Закрыть"]',
                'svg[aria-label="Close"]',
                'div[role="button"][aria-label="Close"]',
                '.close-modal',
                '.modal-close',
                '.popup-close',
                '.b-popup-close',
                '[class*="popup"] [class*="close"]',
                '[class*="modal"] [class*="close"]'
            ];
            
            const cookieSelectors = [
                '#onetrust-accept-btn-handler',
                '#accept-cookie-notification',
                'button[id*="cookie"][id*="accept"]',
                'button[class*="cookie"][class*="accept"]',
                'button[data-testid="cookie-policy-dialog-accept-button"]',
                '.js-cookie-consent-accept',
                '.cookie-banner__accept',
                '#cookie-accept'
            ];

            let actionTaken = false;
            
            const clickAll = (selectors) => {
                for (const sel of selectors) {
                    try {
                        const els = document.querySelectorAll(sel);
                        for (const el of els) {
                            const style = window.getComputedStyle(el);
                            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
                            const r = el.getBoundingClientRect();
                            if (r.width === 0 || r.height === 0) continue;
                            
                            // Ensure it's clickable
                            el.click();
                            actionTaken = true;
                        }
                    } catch(e) {}
                }
            };

            clickAll(closeSelectors);
            clickAll(cookieSelectors);
            
            return actionTaken;
        }
        """
        try:
            return bool(self.page.evaluate(js))
        except Exception:
            return False

    def close(self) -> None:
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

    def click_by_id(self, element_id: str, timeout_ms: int = 5000) -> None:
        """
        Клик по элементу, которому ранее присвоен data-pw-bbox-id = element_id
        (эти id ты создаёшь в screenshot_with_bboxes()).
        """
        locator = self.page.locator(f'[data-pw-bbox-id="{element_id}"]').first
        locator.wait_for(state="visible", timeout=timeout_ms)
        locator.click(timeout=timeout_ms)

    def type_by_id(
        self,
        element_id: str,
        text: str,
        timeout_ms: int = 5000,
        clear: bool = True,
        press_enter: bool = False,
    ) -> None:
        """
        Ввод текста в input/textarea/contenteditable по id.
        """
        locator = self.page.locator(f'[data-pw-bbox-id="{element_id}"]').first
        locator.wait_for(state="visible", timeout=timeout_ms)

        # фокус
        locator.click(timeout=timeout_ms)

        if clear:
            # универсальная очистка
            try:
                locator.fill("", timeout=timeout_ms)
            except Exception:
                # если fill не поддерживается (редко), чистим через Ctrl/Command+A + Backspace
                mod = (
                    "Meta"
                    if self.page.evaluate("() => navigator.platform.includes('Mac')")
                    else "Control"
                )
                self.page.keyboard.press(f"{mod}+A")
                self.page.keyboard.press("Backspace")

        # ввод
        try:
            locator.fill(text, timeout=timeout_ms)
        except Exception:
            locator.type(text, delay=0)

        if press_enter:
            self.page.keyboard.press("Enter")

    def scroll(self, delta_y: int) -> None:
        """
        Скролл страницы на delta_y пикселей.
        delta_y > 0 — вниз, delta_y < 0 — вверх.
        """
        self.page.mouse.wheel(0, delta_y)

    def refresh_bbox_ids(self, max_elements: int = 400) -> dict[str, Any]:
        """
        Важно: после скролла/перехода id могут исчезнуть.
        Этот метод заново находит кликабельные элементы и проставляет им data-pw-bbox-id.
        Возвращает метаданные (id/type/text/bbox) как раньше.
        """
        js = r"""
        (maxElements) => {
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

            if (r.bottom <= 0 || r.right <= 0) return false;
            if (r.top >= window.innerHeight || r.left >= window.innerWidth) return false;

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
              return (el.getAttribute('placeholder') || el.getAttribute('aria-label') || el.value || '')
                .trim().slice(0, 80);
            }
            return (el.innerText || el.textContent || el.getAttribute('aria-label') || '')
              .trim().replace(/\s+/g, ' ').slice(0, 80);
          };

          const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

          const out = [];
          let idx = 1;

          for (const el of nodes) {
            if (!isVisible(el)) continue;

            const r = el.getBoundingClientRect();
            const x = clamp(r.x, 0, window.innerWidth);
            const y = clamp(r.y, 0, window.innerHeight);
            const x2 = clamp(r.x + r.width, 0, window.innerWidth);
            const y2 = clamp(r.y + r.height, 0, window.innerHeight);

            const w = x2 - x;
            const h = y2 - y;
            if (w < 2 || h < 2) continue;

            const id = `E${idx++}`;
            el.dataset.pwBboxId = id;

            out.push({ id, type: getType(el), text: getText(el), bbox: { x, y, w, h } });

            if (out.length >= maxElements) break;
          }

          return {
            devicePixelRatio: window.devicePixelRatio || 1,
            viewport: { w: window.innerWidth, h: window.innerHeight },
            elements: out
          };
        }
        """
        return cast("dict[str, Any]", self.page.evaluate(js, max_elements))
