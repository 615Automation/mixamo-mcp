#!/usr/bin/env python3
"""
MCP server for mixamo-operator.
Exposes Mixamo automation as tools for Claude Code.

Usage — add to Claude Code MCP settings:
  {
    "mcpServers": {
      "mixamo": {
        "command": "python",
        "args": ["C:\\\\Users\\\\vital\\\\Projects\\\\mixamo-operator\\\\mcp_server.py"]
      }
    }
  }

NOTE: Do not run main.py at the same time — both use the same browser profile.
"""
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from playwright.async_api import async_playwright, BrowserContext, Page

from screens.auth import is_logged_in
from screens.animations import (
    get_character_name,
    is_t_pose,
    get_selected_animation,
    get_animation_list,
)
from screens.download import get_settings as get_download_settings
from screens.upload import get_status as get_upload_status

MIXAMO_URL = "https://www.mixamo.com"
PROFILE_DIR = Path(__file__).parent / "browser_profile"

mcp = FastMCP("mixamo-mcp")

_pw = None
_context: BrowserContext | None = None
_page: Page | None = None


async def _get_page() -> Page:
    global _pw, _context, _page
    if _page is not None:
        try:
            await _page.evaluate("1")
            return _page
        except Exception:
            _page = None

    PROFILE_DIR.mkdir(exist_ok=True)
    _pw = await async_playwright().start()
    _context = await _pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=True,
        viewport={"width": 1280, "height": 900},
    )
    pages = _context.pages
    _page = pages[0] if pages else await _context.new_page()
    await _page.goto(MIXAMO_URL)
    await _page.wait_for_load_state("networkidle")
    return _page


async def _html_url(page: Page) -> tuple[str, str]:
    url = await page.evaluate("window.location.href")
    html = await page.content()
    return html, url


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def status() -> str:
    """Get current Mixamo screen state: character, selected animation, and all params."""
    page = await _get_page()
    html, url = await _html_url(page)
    logged = is_logged_in(url, html)
    lines = [f"url: {url}", f"logged_in: {logged}"]

    if "autorig-modal" in html:
        st = get_upload_status(html)
        lines.append(f"screen: upload")
        lines.append(f"state: {st.get('state')}")
        if st.get("text"):
            lines.append(f"message: {st['text']}")
        if st.get("progress") is not None:
            lines.append(f"progress: {st['progress']}%")

    elif "asset-download-modal" in html:
        settings = get_download_settings(html)
        lines.append("screen: download")
        for k, v in settings.items():
            lines.append(f"  {k}: {v['label']} ({v['value']})")

    elif logged:
        char = get_character_name(html)
        lines.append("screen: animations")
        lines.append(f"character: {char}")
        if is_t_pose(html):
            lines.append("animation: none (T-pose)")
        else:
            anim = get_selected_animation(html)  # HTML-only, no sync page
            if anim:
                for cb in ("mirror", "inplace"):
                    try:
                        val = await page.evaluate(
                            f"() => {{ const el = document.querySelector('input[name=\"{cb}\"]');"
                            f" return el ? el.checked : false; }}"
                        )
                        anim["params"][cb] = val
                    except Exception:
                        pass
                lines.append(f"animation: {anim['name']} (id={anim['id']})")
                lines.append(f"description: {anim['description']}")
                lines.append(f"params: {anim['params']}")
    else:
        lines.append("screen: login/landing (not authenticated)")

    return "\n".join(lines)


@mcp.tool()
async def list_animations(query: str = "") -> str:
    """
    List animations. Optionally filter by query string.
    Returns current page of results with IDs and names.
    """
    page = await _get_page()
    url = "https://www.mixamo.com/#/?page=1&type=Motion%2CMotionPack"
    if query:
        url += f"&query={query}"
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_selector(".product-animation", timeout=15_000)
    html = await page.content()
    result = get_animation_list(html)
    p = result["pagination"]
    lines = [f"Page {p['page']} of {p['total_pages']} ({p['total']} total)"]
    for a in result["items"]:
        marker = "*" if a["selected"] else " "
        lines.append(f"[{marker}] {a['id']}  {a['name']}")
    return "\n".join(lines)


@mcp.tool()
async def select_animation(animation_id: str) -> str:
    """Select an animation by its numeric ID (must be visible on the current page)."""
    page = await _get_page()
    clicked = await page.evaluate(f"""() => {{
        for (const img of document.querySelectorAll('.product-animation .product-image img')) {{
            if (img.src.includes('/motions/{animation_id}/')) {{
                img.closest('.product-animation').click();
                return true;
            }}
        }}
        return false;
    }}""")
    if not clicked:
        return f"Animation id={animation_id} not found on current page. Use list_animations first."
    await page.wait_for_load_state("networkidle")
    return f"Selected animation id={animation_id}"


@mcp.tool()
async def set_param(name: str, value: str) -> str:
    """
    Set an animation parameter.
    Checkbox params (value: true/false): inplace, mirror
    Slider params (value: 0-100): overdrive, arm-space, trim
    """
    CHECKBOX_PARAMS = {"inplace", "mirror"}
    SLIDER_PARAMS = {"overdrive", "arm-space", "trim"}
    page = await _get_page()

    if name in CHECKBOX_PARAMS:
        bool_val = value.lower() in ("true", "1", "yes", "on")
        current = await page.evaluate(
            f"() => {{ const el = document.querySelector('input[name=\"{name}\"]');"
            f" return el ? el.checked : null; }}"
        )
        if current is None:
            return f"Checkbox '{name}' not found — is an animation selected?"
        if current != bool_val:
            await page.click(f'input[name="{name}"] + span, label:has(input[name="{name}"])')
        return f"{name} = {bool_val}"

    if name in SLIDER_PARAMS:
        try:
            int_val = int(value)
        except ValueError:
            return f"Expected integer for '{name}', got '{value}'"
        await page.evaluate(f"""() => {{
            const el = document.querySelector('input.animation-slider-value[name="{name}"]');
            if (!el) return;
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            setter.call(el, '{int_val}');
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}""")
        return f"{name} = {int_val}"

    return f"Unknown param '{name}'. Checkboxes: inplace, mirror. Sliders: overdrive, arm-space, trim"


@mcp.tool()
async def upload_character(file_path: str) -> str:
    """Upload a character file (.fbx, .obj, or .zip) to the Mixamo Auto-Rigger."""
    page = await _get_page()
    p = Path(file_path)
    if not p.exists():
        return f"File not found: {file_path}"
    if p.suffix.lower() not in (".fbx", ".obj", ".zip"):
        return f"Unsupported format '{p.suffix}'. Use .fbx, .obj, or .zip."

    html = await page.content()
    if "autorig-modal" not in html:
        await page.click('button:has-text("Upload Character")')
        await page.wait_for_selector('a:has-text("Select character file")', timeout=10_000)

    async with page.expect_file_chooser() as fc_info:
        await page.click('a:has-text("Select character file")')
    fc = await fc_info.value
    await fc.set_files(str(p))
    return f"Upload started: {p.name} — call status() to track progress"


@mcp.tool()
async def download_animation(
    output_path: str,
    format: str = "fbx_unity",
    skin: bool = False,
    fps: int = 30,
) -> str:
    """
    Download the currently selected animation.
    format: fbx | fbx_ascii | fbx_unity | fbx_7.4 | fbx_6.1 | collada
    skin: include skin mesh
    fps: frames per second
    """
    FORMAT_MAP = {
        "fbx":       "fbx7_2019",
        "fbx_ascii": "fbx7_2019_ascii",
        "fbx_unity": "fbx7_unity",
        "fbx_7.4":   "fbx7_2014",
        "fbx_6.1":   "fbx6",
        "collada":   "dae_mixamo",
    }

    page = await _get_page()
    html = await page.content()
    if "asset-download-modal" not in html:
        await page.click(".sidebar-header button.btn-primary")
        await page.wait_for_selector(".modal-footer button.btn-default", timeout=10_000)

    async def _set_select(index: int, value: str):
        await page.evaluate(f"""() => {{
            const sel = document.querySelectorAll('.asset-download-modal select')[{index}];
            if (!sel) return;
            const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
            setter.call(sel, '{value}');
            sel.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}""")

    await _set_select(0, FORMAT_MAP.get(format, format))
    await _set_select(1, "true" if skin else "false")
    await _set_select(2, str(fps))

    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    async with page.expect_download(timeout=60_000) as dl_info:
        await page.click(".modal-footer button.btn-primary")
    dl = await dl_info.value
    await dl.save_as(str(p))
    return f"Saved: {p}"


@mcp.tool()
async def confirm_review() -> str:
    """Click Next on the Auto-Rigger review screen to confirm the character rig."""
    page = await _get_page()
    await page.click(".modal-footer button.btn-primary")
    return "Confirmed."


@mcp.tool()
async def close_upload_modal() -> str:
    """Close/dismiss the upload modal without completing."""
    page = await _get_page()
    await page.click(".autorig-modal .modal-header button.close")
    return "Upload modal closed."


if __name__ == "__main__":
    mcp.run()
