from pathlib import Path
from bs4 import BeautifulSoup

SCREEN_ID = "download"

_OPEN_BUTTON = ".sidebar-header button.btn-primary"
_CONFIRM_BUTTON = ".modal-footer button.btn-primary"
_CANCEL_BUTTON = ".modal-footer button.btn-default"

# Select indices inside the modal (all share same id, so positional)
_SELECT_FORMAT = 0
_SELECT_SKIN = 1
_SELECT_FPS = 2
_SELECT_KEYFRAME = 3

FORMAT_OPTIONS = {
    "fbx":        "fbx7_2019",
    "fbx_ascii":  "fbx7_2019_ascii",
    "fbx_unity":  "fbx7_unity",
    "fbx_7.4":    "fbx7_2014",
    "fbx_6.1":    "fbx6",
    "collada":    "dae_mixamo",
}


def matches(url: str, html: str) -> bool:
    return "mixamo.com" in url and "asset-download-modal" in html


def open_modal(page):
    if "asset-download-modal" not in page.content():
        page.click(_OPEN_BUTTON)
        page.wait_for_selector(_CANCEL_BUTTON, timeout=10_000)


def set_option(page, index: int, value: str):
    page.evaluate(f"""() => {{
        const sel = document.querySelectorAll('.asset-download-modal select')[{index}];
        if (!sel) return;
        const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
        setter.call(sel, '{value}');
        sel.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }}""")


def set_format(page, value: str):
    set_option(page, _SELECT_FORMAT, FORMAT_OPTIONS.get(value, value))


def set_skin(page, value: bool):
    set_option(page, _SELECT_SKIN, "true" if value else "false")


def set_fps(page, value: int):
    set_option(page, _SELECT_FPS, str(value))


def confirm(page, output_path: str):
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with page.expect_download(timeout=60_000) as dl_info:
        page.click(_CONFIRM_BUTTON)
    dl_info.value.save_as(str(p))
    return str(p)


def get_settings(html: str, page=None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    modal = soup.find(class_=lambda c: c and "asset-download-modal" in c.split())
    if not modal:
        return {}

    labels = [label.get_text(strip=True) for label in modal.find_all("label")]
    selects = modal.find_all("select")

    settings = {}
    for i, (label, select) in enumerate(zip(labels, selects)):
        key = label.lower().replace(" ", "_")
        if page is not None:
            try:
                value = page.evaluate(
                    f"() => {{ const els = document.querySelectorAll('.asset-download-modal select'); "
                    f"return els[{i}] ? els[{i}].value : ''; }}"
                )
            except Exception:
                value = _selected_value(select)
        else:
            value = _selected_value(select)

        opt = select.find("option", value=value)
        settings[key] = {"value": value, "label": opt.get_text(strip=True) if opt else value}

    return settings


def _selected_value(select) -> str:
    selected = select.find("option", selected=True)
    if selected:
        return selected.get("value", "")
    first = select.find("option")
    return first.get("value", "") if first else ""
