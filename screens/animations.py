import re
from urllib.parse import parse_qs, quote, urlsplit

from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from screens.auth import is_logged_in

SCREEN_ID = "animations"

SEARCH_PAGE_URL = "https://www.mixamo.com/#/?page=1&type=Motion%2CMotionPack"
SEARCH_API_PATH = "/api/v1/products"
SEARCH_TIMEOUT_MS = 30_000

# True once the clip cards on the page are exactly the given ids. Mixamo leaves the last
# search's cards up for a while after a new search starts. Packs have their own card type.
CARDS_MATCH_JS = """(ids) => {
    const shown = [...document.querySelectorAll('.product-animation .product-image img')]
        .map(img => (img.src.match(/\\/motions\\/(\\d+)\\//) || [])[1]);
    return shown.length === ids.length && ids.every(id => shown.includes(id));
}"""

_last_search = None  # (query, page URL, Mixamo's response)


def matches(url: str, html: str) -> bool:
    if "mixamo.com" not in url:
        return False
    if "type=Motion" in url:
        return True
    return is_logged_in(url, html) and "type=Character" not in url


def get_character_name(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    h2 = soup.select_one(".product-nav h2")
    if not h2:
        return ""
    # When animation selected: h2 = "<anim name> on <strong>character name</strong>"
    strong = h2.find("strong")
    if strong:
        return strong.get_text(strip=True)
    return h2.get_text(strip=True)


def is_t_pose(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    return bool(soup.find(class_="character-controls")) and not bool(soup.find(class_="animation-settings"))


def get_selected_animation(html: str, page=None) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")

    selected = soup.find(class_=lambda c: c and "product-selected" in c.split())
    if not selected:
        return None

    # Name and description from the product card
    name_el = selected.find("p", class_="text-capitalize")
    name = name_el.get_text(strip=True) if name_el else ""

    anim_id = ""
    img = selected.select_one(".product-image img")
    if img and img.get("src"):
        m = re.search(r"/motions/(\d+)/", img["src"])
        if m:
            anim_id = m.group(1)

    description = ""
    meta = selected.find("ul", class_="product-metadata")
    if meta:
        li = meta.find("li")
        if li:
            description = li.get_text(strip=True).replace("Description:", "").strip()

    # Sidebar parameters
    params = {}
    settings = soup.find(class_="animation-settings")
    if settings:
        for inp in settings.find_all("input", class_="animation-slider-value"):
            params[inp["name"]] = int(inp.get("value", 0))

        trim_inputs = settings.find_all("input", attrs={"name": "trim"})
        if len(trim_inputs) >= 2:
            params["trim_start"] = int(trim_inputs[0].get("value", 0))
            params["trim_end"] = int(trim_inputs[1].get("value", 100))

        trim_group = settings.find(class_="animation-slider-trim")
        if trim_group:
            small = trim_group.find("small", class_="text-muted")
            if small:
                m = re.search(r"(\d+) total frames", small.get_text())
                if m:
                    params["total_frames"] = int(m.group(1))

        for cb_name in ["mirror", "inplace"]:
            if page is not None:
                try:
                    params[cb_name] = page.evaluate(
                        f"() => {{ const el = document.querySelector('input[name=\"{cb_name}\"]'); return el ? el.checked : false; }}"
                    )
                except Exception:
                    params[cb_name] = False
            else:
                cb = settings.find("input", attrs={"name": cb_name, "type": "checkbox"})
                params[cb_name] = cb.has_attr("checked") if cb else False

    return {"id": anim_id, "name": name, "description": description, "params": params}


# --- List & Navigation ---

def search_url(query: str = "") -> str:
    url = SEARCH_PAGE_URL
    if query:
        url += f"&query={quote(query, safe='')}"
    return url


def is_search_response(url: str, query: str = "") -> bool:
    """True if url is the request the page itself makes to search for query."""
    parts = urlsplit(url)
    if parts.path != SEARCH_API_PATH:
        return False
    params = parse_qs(parts.query, keep_blank_values=True)
    return (
        params.get("type") == ["Motion,MotionPack"]
        and params.get("query", [""])[0].strip().lower() == query.strip().lower()
    )


def parse_search_response(data: dict) -> dict:
    items, packs = [], []
    for result in data["results"]:
        if result["type"] == "MotionPack":
            packs.append({"name": result["name"], "clips": len(result["motions"] or [])})
            continue
        m = re.search(r"/motions/(\d+)/", result["thumbnail"])
        items.append({
            "id": m.group(1) if m else "",
            "name": result["name"],
            "description": result["description"],
            "selected": False,
        })

    p = data["pagination"]
    return {
        "items": items,
        "packs": packs,
        "pagination": {"page": p["page"], "total": p["num_results"], "total_pages": p["num_pages"]},
        "cards_ready": True,
    }


def mark_selected(result: dict, html: str):
    selected = get_selected_animation(html)
    for item in result["items"]:
        item["selected"] = bool(selected) and item["id"] == selected["id"]


def format_search_results(result: dict, query: str = "") -> list[str]:
    p = result["pagination"]
    if p["total"] == 0:
        return [f"No animations found for {query!r}."]

    lines = [f"Page {p['page']} of {p['total_pages']} ({p['total']} total)"]
    for a in result["items"]:
        marker = "*" if a["selected"] else " "
        description = f" - {a['description']}" if a["description"] else ""
        lines.append(f"[{marker}] {a['id']}  {a['name']}{description}")
    for pack in result["packs"]:
        lines.append(f"[pack] {pack['name']} ({pack['clips']} clips)")
    if result["packs"]:
        lines.append("Packs can't be selected with select_animation.")
    if not result["cards_ready"]:
        lines.append("Note: the page hasn't finished showing these yet, so select_animation may not find them.")
    return lines


def no_answer_error(query: str) -> RuntimeError:
    return RuntimeError(
        f"Mixamo didn't answer the search for {query!r} within {SEARCH_TIMEOUT_MS // 1000} seconds. "
        "Check the connection and that status shows logged_in: True, then try again."
    )


def refused_error(query: str, status: int) -> RuntimeError:
    return RuntimeError(f"Mixamo refused the search for {query!r}: HTTP {status}.")


def _fetch_search(page, query: str) -> dict:
    global _last_search
    # Repeating a search leaves the URL as it is, so the page won't ask Mixamo again.
    if _last_search and _last_search[:2] == (query, page.url):
        return _last_search[2]

    url = search_url(query)
    try:
        with page.expect_response(
            lambda r: is_search_response(r.url, query), timeout=SEARCH_TIMEOUT_MS
        ) as response_info:
            if page.url == url:  # retrying a search that got no answer
                page.reload(wait_until="domcontentloaded")
            else:
                page.goto(url, wait_until="domcontentloaded")
        response = response_info.value
    except PlaywrightTimeoutError:
        raise no_answer_error(query) from None
    if not response.ok:
        raise refused_error(query, response.status)

    data = response.json()
    _last_search = (query, page.url, data)
    return data


def search(page, query: str = "") -> dict:
    result = parse_search_response(_fetch_search(page, query))
    try:
        page.wait_for_function(
            CARDS_MATCH_JS, arg=[a["id"] for a in result["items"]], timeout=SEARCH_TIMEOUT_MS, polling=100
        )
    except PlaywrightTimeoutError:
        result["cards_ready"] = False
    mark_selected(result, page.content())
    return result


def select_animation(page, anim_id: str):
    clicked = page.evaluate(f"""() => {{
        for (const img of document.querySelectorAll('.product-animation .product-image img')) {{
            if (img.src.includes('/motions/{anim_id}/')) {{
                img.closest('.product-animation').click();
                return true;
            }}
        }}
        return false;
    }}""")
    if not clicked:
        raise RuntimeError(f"Animation id={anim_id} not found on current page")


# --- Controls ---

def set_checkbox(page, name: str, value: bool):
    """Set a checkbox control (mirror, inplace)."""
    current = page.evaluate(
        f"() => {{ const el = document.querySelector('input[name=\"{name}\"]'); return el ? el.checked : null; }}"
    )
    if current is None:
        raise RuntimeError(f"Checkbox '{name}' not found")
    if current != value:
        page.click(f'input[name="{name}"] + span, label:has(input[name="{name}"])')


def set_slider(page, name: str, value: int):
    """Set a slider value (Overdrive, arm-space, trim)."""
    page.evaluate(f"""() => {{
        const el = document.querySelector('input.animation-slider-value[name="{name}"]');
        if (!el) return;
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(el, '{value}');
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }}""")
