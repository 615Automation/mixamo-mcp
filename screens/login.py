SCREEN_ID = "login"

# Adobe ID auth flow — URL-only match, no HTML fallback to avoid stale-url issues
def matches(url: str, html: str) -> bool:
    return "auth.services.adobe.com" in url or "adobelogin.com" in url
