SCREEN_ID = "characters"

# Logged-in character browser: URL has type=Character param
def matches(url: str, html: str) -> bool:
    return "mixamo.com" in url and "type=Character" in url

