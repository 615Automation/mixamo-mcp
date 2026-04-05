from pathlib import Path
from playwright.sync_api import sync_playwright, BrowserContext, Page
from screens.auth import is_logged_in

PROFILE_DIR = Path(__file__).parent / "browser_profile"
MIXAMO_URL = "https://www.mixamo.com"

_pw = None
_context: BrowserContext = None
_page: Page = None


def _launch(headless: bool) -> Page:
    global _pw, _context, _page
    PROFILE_DIR.mkdir(exist_ok=True)
    _pw = sync_playwright().start()
    _context = _pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        viewport={"width": 1280, "height": 900},
    )
    _page = _context.new_page()
    return _page


def _close():
    global _pw, _context, _page
    try:
        if _context:
            _context.close()
    except Exception:
        pass
    try:
        if _pw:
            _pw.stop()
    except Exception:
        pass
    _pw = _context = _page = None


def _check_logged_in(page: Page) -> bool:
    page.goto(MIXAMO_URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    try:
        url = page.evaluate("window.location.href")
        html = page.content()
        return is_logged_in(url, html)
    except Exception:
        return False


DEBUG = True  # set to False to run headless after login


def start() -> Page:
    """Start browser. If not logged in, open visible browser for login, then resume in configured mode."""
    page = _launch(headless=False if DEBUG else True)

    if _check_logged_in(page):
        print("Session active.")
        return page

    if not DEBUG:
        # Relaunch visible just for login
        _close()
        print("\nNot logged in. Opening browser for login...")
        page = _launch(headless=False)
        page.goto(MIXAMO_URL, wait_until="domcontentloaded")

    print("Waiting for login", end="", flush=True)
    while True:
        try:
            url = page.evaluate("window.location.href")
            html = page.content()
        except Exception:
            import time; time.sleep(1)
            continue

        if is_logged_in(url, html):
            print(" done.")
            break

        import time
        time.sleep(1)
        print(".", end="", flush=True)

    if not DEBUG:
        _close()
        print("Resuming in headless mode.")
        page = _launch(headless=True)
        page.goto(MIXAMO_URL, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")

    return page


def stop():
    _close()


def get_page() -> Page:
    return _page
