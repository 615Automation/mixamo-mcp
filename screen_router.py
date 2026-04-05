from playwright.sync_api import Page
from screens import landing, login, characters, animations, download, upload

SCREENS = [upload, download, login, characters, animations, landing]  # specific → general


def current_screen(page: Page):
    try:
        url = page.evaluate("window.location.href")
        html = page.content()
    except Exception:
        return None, None, None  # page is mid-navigation, skip this tick

    for screen in SCREENS:
        if screen.matches(url, html):
            return screen, url, html

    return None, url, html
