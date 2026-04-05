def is_logged_in(url: str, html: str) -> bool:
    # Must be on the mixamo.com host, not just contain it in query params
    if not (url.startswith("https://www.mixamo.com") or url.startswith("https://mixamo.com")):
        return False
    # When logged out, mixamo navbar has "Log in" and "Sign up" links
    return '>Log in<' not in html and '>Sign up<' not in html
