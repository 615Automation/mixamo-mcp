SCREEN_ID = "landing"

# Unauthenticated home page shown before login
def matches(url: str, html: str) -> bool:
    return "mixamo.com" in url and 'class="home2' in html
