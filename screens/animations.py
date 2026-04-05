import re
from bs4 import BeautifulSoup
from screens.auth import is_logged_in

SCREEN_ID = "animations"


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

def get_animation_list(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for item in soup.find_all(class_="product-animation"):
        img = item.select_one(".product-image img")
        name_el = item.find("p", class_="text-capitalize")
        if not img or not name_el:
            continue
        m = re.search(r"/motions/(\d+)/", img["src"])
        selected = "product-selected" in item.get("class", [])
        results.append({
            "id": m.group(1) if m else "",
            "name": name_el.get_text(strip=True),
            "selected": selected,
        })

    # Pagination: "Showing 1-48 of 391 results"
    page_info = {"page": 1, "per_page": 0, "total": 0, "total_pages": 1}
    info_el = soup.find(class_="search-description")
    if info_el:
        m = re.search(r"Showing (\d+)-(\d+) of (\d+)", info_el.get_text())
        if m:
            start, end, total = int(m.group(1)), int(m.group(2)), int(m.group(3))
            per_page = end - start + 1
            page_info = {
                "page": (start - 1) // per_page + 1,
                "per_page": per_page,
                "total": total,
                "total_pages": -(-total // per_page),  # ceil division
            }

    return {"items": results, "pagination": page_info}


def search(page, query: str = ""):
    url = "https://www.mixamo.com/#/?page=1&type=Motion%2CMotionPack"
    if query:
        url += f"&query={query}"
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector(".product-animation", timeout=15_000)


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
