from __future__ import annotations

import asyncio
import os
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "")
PROFILE = Path(os.getenv("BROWSER_DATA_DIR", "/browser-profile")).resolve()
WORKSPACE = Path(os.getenv("WORKSPACE_DIR", "/workspace")).resolve()
playwright_instance = None
browser: Browser | None = None
context: BrowserContext | None = None
page: Page | None = None
app = FastAPI(title="Uranus-AI Browser", docs_url=None, redoc_url=None)


def auth(x_internal_token: str | None = Header(default=None)) -> None:
    if not TOKEN or x_internal_token != TOKEN:
        raise HTTPException(status_code=403, detail="Internal token required")


def safe_screenshot_path(value: str) -> Path:
    rel = PurePosixPath(str(value or "artifacts/browser.png").replace("\\", "/").lstrip("/"))
    if ".." in rel.parts:
        raise HTTPException(status_code=400, detail="Path escapes workspace")
    target = (WORKSPACE / rel).resolve()
    if target != WORKSPACE and WORKSPACE not in target.parents:
        raise HTTPException(status_code=400, detail="Path escapes workspace")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


class Action(BaseModel):
    action: str = Field(min_length=1)
    url: str | None = None
    selector: str | None = None
    text: str | None = None
    key: str | None = None
    pixels: int = Field(default=700, ge=-5000, le=5000)
    path: str = "artifacts/browser.png"


async def get_page() -> Page:
    global page
    if page is None or page.is_closed():
        if context is None:
            raise RuntimeError("Browser is not ready")
        page = await context.new_page()
    return page


@app.on_event("startup")
async def startup() -> None:
    global playwright_instance, browser, context, page
    PROFILE.mkdir(parents=True, exist_ok=True)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    playwright_instance = await async_playwright().start()
    executable = os.getenv("BROWSER_EXECUTABLE_PATH") or None
    launch_options = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"], "viewport": {"width": 1440, "height": 900}, "accept_downloads": False}
    if executable:
        launch_options["executable_path"] = executable
    context = await playwright_instance.chromium.launch_persistent_context(str(PROFILE), **launch_options)
    page = context.pages[0] if context.pages else await context.new_page()


@app.on_event("shutdown")
async def shutdown() -> None:
    if context:
        await context.close()
    if browser:
        await browser.close()
    if playwright_instance:
        await playwright_instance.stop()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok" if page else "starting"}


@app.post("/action")
async def perform(action: Action, _: None = Depends(auth)) -> dict:
    current = await get_page()
    try:
        if action.action == "open":
            parsed = urlparse(action.url or "")
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                return {"ok": False, "error": "Разрешены только абсолютные HTTP(S)-ссылки"}
            await current.goto(action.url, wait_until="domcontentloaded", timeout=30_000)
        elif action.action == "snapshot":
            return {"ok": True, "url": current.url, "title": await current.title(), "text": (await current.locator("body").inner_text(timeout=5000))[:20_000]}
        elif action.action == "click":
            if not action.selector:
                return {"ok": False, "error": "selector is required"}
            await current.locator(action.selector).first.click(timeout=15_000)
            await current.wait_for_load_state("domcontentloaded", timeout=10_000)
        elif action.action == "type":
            if not action.selector:
                return {"ok": False, "error": "selector is required"}
            await current.locator(action.selector).first.fill(action.text or "", timeout=15_000)
        elif action.action == "press":
            await current.keyboard.press(action.key or "Enter")
        elif action.action == "scroll":
            await current.mouse.wheel(0, action.pixels)
        elif action.action == "screenshot":
            path = safe_screenshot_path(action.path)
            await current.screenshot(path=str(path), full_page=True)
            return {"ok": True, "path": str(path.relative_to(WORKSPACE)), "url": current.url, "title": await current.title()}
        else:
            return {"ok": False, "error": f"Unknown browser action: {action.action}"}
        return {"ok": True, "url": current.url, "title": await current.title(), "text": (await current.locator("body").inner_text(timeout=5000))[:12_000]}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "url": current.url}
