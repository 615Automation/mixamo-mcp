import re
from pathlib import Path
from bs4 import BeautifulSoup

SCREEN_ID = "upload"

ACCEPTED_FORMATS = ["fbx", "obj", "zip"]

_OPEN_BUTTON = 'button:has-text("Upload Character")'
_SELECT_LINK = 'a:has-text("Select character file")'


def matches(url: str, html: str) -> bool:
    return "mixamo.com" in url and "autorig-modal" in html


def get_status(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    if soup.find(class_="autorig-uploading"):
        bar = soup.find(class_="progress-bar")
        progress = int(bar.get("aria-valuenow", 0)) if bar else 0
        status_el = soup.find(class_="progress-status")
        status_text = status_el.get_text(strip=True) if status_el else ""
        return {"state": "processing", "progress": progress, "text": status_text}

    if soup.find(class_="autorig-overlay"):
        return {"state": "markers", "text": "Marker placement required — not supported. Type 'close' to dismiss."}

    if soup.find(class_="autorig-holder"):
        info_el = soup.find(class_="autorig-info")
        text = info_el.get_text(" ", strip=True) if info_el else ""
        return {"state": "review", "text": text}

    if soup.find(string=re.compile("unable to map your existing skeleton")):
        return {"state": "error", "text": "Unable to map skeleton. Upload a compatible model or use Auto-Rigger."}

    title_el = soup.find(class_="modal-title")
    if title_el and title_el.get_text(strip=True) == "Change Character":
        return {"state": "change_character", "text": "Proceed with this new character? Previous character will not be saved."}

    if soup.find(class_="autorig-upload"):
        return {"state": "idle"}

    return {}


def confirm_review(page):
    """Click Next on the auto-rigger review screen."""
    page.click(".modal-footer button.btn-primary")


def back(page):
    """Click Back to View page on the skeleton error screen."""
    page.click(".modal-footer button.btn-primary")


def close(page):
    """Click the X button to dismiss the auto-rigger modal."""
    page.click(".autorig-modal .modal-header button.close")


def upload_file(page, path: str):
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if p.suffix.lower() not in (".fbx", ".obj", ".zip"):
        raise ValueError(f"Unsupported format '{p.suffix}'. Use fbx, obj, or zip.")

    if "autorig-modal" not in page.content():
        page.click(_OPEN_BUTTON)
        page.wait_for_selector(_SELECT_LINK, timeout=10_000)

    with page.expect_file_chooser() as fc_info:
        page.click(_SELECT_LINK)
    fc_info.value.set_files(str(p))
