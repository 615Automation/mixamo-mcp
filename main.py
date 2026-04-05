import time
import threading
import queue

import browser
import screen_router
from screens.auth import is_logged_in
from screens.animations import get_selected_animation, get_character_name, is_t_pose, get_animation_list, search, select_animation, set_checkbox, set_slider
from screens.download import get_settings as get_download_settings, open_modal, set_format, set_skin, set_fps, confirm as confirm_download
from screens.upload import upload_file, get_status as get_upload_status, confirm_review, back as upload_back, close as upload_close

MIXAMO_URL = "https://www.mixamo.com"
POLL_INTERVAL = 1.0

_state = {
    "screen": None,
    "logged_in": False,
    "animation": None,
    "download": None,
}
_cmd_queue = queue.Queue()
_running = False


# ---------------------------------------------------------------------------
# Input thread — only reads stdin, never touches Playwright
# ---------------------------------------------------------------------------

def read_line() -> str:
    line = input("> ")
    while line.count('"') % 2 == 1:
        line += " " + input("  ")
    return line


def input_loop():
    print("Ready. Type 'help' for commands.")
    try:
        while _running:
            handle_input(read_line())
    except (EOFError, OSError):
        pass


# ---------------------------------------------------------------------------
# Main thread — all Playwright calls live here
# ---------------------------------------------------------------------------

def main():
    global _running

    page = browser.start()
    page.goto(MIXAMO_URL)
    page.wait_for_load_state("networkidle")

    _running = True
    t = threading.Thread(target=input_loop, daemon=True)
    t.start()

    current = None
    current_animation = None

    try:
        while _running:
            # Execute any pending commands
            try:
                while True:
                    fn = _cmd_queue.get_nowait()
                    try:
                        fn(page)
                    except Exception as e:
                        print(f"  Error: {e}")
            except queue.Empty:
                pass

            screen, url, html = screen_router.current_screen(page)
            if screen is None:
                time.sleep(POLL_INTERVAL)
                continue

            logged_in = is_logged_in(url, html)
            _state["screen"] = screen.SCREEN_ID
            _state["logged_in"] = logged_in

            state_key = (screen.SCREEN_ID, logged_in)
            if state_key != current:
                current = state_key
                print(f"\nScreen: {screen.SCREEN_ID} | logged in: {logged_in}")

            if screen.SCREEN_ID == "animations":
                with open("page_dump.html", "w", encoding="utf-8") as f:
                    f.write(html)
                character = get_character_name(html)
                if character != _state.get("character"):
                    _state["character"] = character
                    print(f"  Character: {character}")
                if is_t_pose(html):
                    if _state.get("animation") is not None:
                        _state["animation"] = None
                        current_animation = None
                        print("  T-pose (no animation selected)")
                else:
                    anim = get_selected_animation(html, page)
                    _state["animation"] = anim
                    if anim and anim != current_animation:
                        current_animation = anim
                        print(f"  Animation: {anim['name']} (id={anim['id']})")
                        print(f"  Desc:      {anim['description']}")
                        print(f"  Params:    {anim['params']}")

            if screen.SCREEN_ID == "download":
                with open("page_dump.html", "w", encoding="utf-8") as f:
                    f.write(html)
                settings = get_download_settings(html, page)
                _state["download"] = settings
                if settings:
                    print(f"  Download settings: {settings}")

            if screen.SCREEN_ID == "upload":
                with open("page_dump.html", "w", encoding="utf-8") as f:
                    f.write(html)
                status = get_upload_status(html)
                if status != _state.get("upload_status"):
                    _state["upload_status"] = status
                    if status.get("state") == "processing":
                        print(f"  Uploading: {status['progress']}% — {status['text']}")
                    elif status.get("state") == "review":
                        print("  Auto-Rigger review — confirming.")
                        confirm_review(page)
                    elif status.get("state") == "change_character":
                        print("  Change character — confirming.")
                        confirm_review(page)
                    elif status.get("state") == "markers":
                        print("  Meshes without skeletons are not supported.")
                        upload_close(page)
                    elif status.get("state") == "error":
                        print(f"  Error: {status['text']} Type 'back' to return.")
                    elif status.get("state") == "idle":
                        print("  Upload modal open — waiting for file.")

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        pass
    finally:
        _running = False
        browser.stop()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

CHECKBOX_PARAMS = {"inplace", "mirror"}
SLIDER_PARAMS = {"overdrive", "arm-space", "trim"}

HELP = """
Commands:
  status                       show current screen and animation
  set inplace <true|false>     toggle In Place
  set mirror  <true|false>     toggle Mirror
  set overdrive <0-100>        set Overdrive
  set arm-space <0-100>        set Character Arm-Space
  list [query]                 list animations (optionally search by query)
  select <id>                  select animation by id
  upload <path>                upload a character file (fbx/obj/zip)
  next                         confirm auto-rigger review (click Next)
  download <path> [format=fbx_unity] [skin=false] [fps=30]
  help                         show this message
  quit                         exit
"""


def cmd_status():
    s = _state
    print(f"Screen: {s['screen']} | logged in: {s['logged_in']}")
    if s["animation"]:
        a = s["animation"]
        print(f"Animation: {a['name']} (id={a['id']})")
        print(f"Params:    {a['params']}")
    if s["download"]:
        print(f"Download:  {s['download']}")


def parse_bool(val: str) -> bool:
    if val.lower() in ("true", "1", "yes", "on"):
        return True
    if val.lower() in ("false", "0", "no", "off"):
        return False
    raise ValueError(f"Expected true/false, got '{val}'")


def handle_input(line: str):
    global _running
    import shlex
    try:
        parts = shlex.split(line.strip(), posix=False)
        parts = [p.strip('"\'') for p in parts]
    except ValueError:
        parts = line.strip().split()
    if not parts:
        return

    cmd = parts[0].lower()

    if cmd in ("quit", "exit"):
        _running = False
        return

    if cmd == "help":
        print(HELP)
        return

    if cmd == "status":
        cmd_status()
        return

    if cmd == "set" and len(parts) >= 3:
        param = parts[1].lower()
        raw = parts[2]

        if param in CHECKBOX_PARAMS:
            try:
                value = parse_bool(raw)
            except ValueError as e:
                print(f"  {e}")
                return
            def fn(page, p=param, v=value):
                set_checkbox(page, p, v)
                print(f"  {p} set to {v}")
            _cmd_queue.put(fn)

        elif param in SLIDER_PARAMS:
            try:
                value = int(raw)
            except ValueError:
                print(f"  Expected integer, got '{raw}'")
                return
            def fn(page, p=param, v=value):
                set_slider(page, p, v)
                print(f"  {p} set to {v}")
            _cmd_queue.put(fn)

        else:
            print(f"  Unknown param '{param}'. Try: {CHECKBOX_PARAMS | SLIDER_PARAMS}")
        return

    if cmd == "download":
        if len(parts) < 2:
            print("  Usage: download <output_path> [format=fbx_unity] [skin=false] [fps=30]")
            return
        output = parts[1]
        opts = {}
        for kv in parts[2:]:
            if "=" in kv:
                k, v = kv.split("=", 1)
                opts[k.lower()] = v
        def fn(page, o=output, opts=opts):
            open_modal(page)
            if "format" in opts:
                set_format(page, opts["format"])
            if "skin" in opts:
                set_skin(page, parse_bool(opts["skin"]))
            if "fps" in opts:
                set_fps(page, int(opts["fps"]))
            saved = confirm_download(page, o)
            print(f"  Saved: {saved}")
        _cmd_queue.put(fn)
        return

    if cmd == "list":
        query = " ".join(parts[1:]) if len(parts) >= 2 else ""
        def fn(page, q=query):
            search(page, q)
            result = get_animation_list(page.content())
            p = result["pagination"]
            print(f"\n  Page {p['page']} of {p['total_pages']} ({p['total']} total)")
            for a in result["items"]:
                marker = "*" if a["selected"] else " "
                print(f"  [{marker}] {a['id']}  {a['name']}")
        _cmd_queue.put(fn)
        return

    if cmd == "select":
        if len(parts) < 2:
            print("  Usage: select <id>")
            return
        anim_id = parts[1]
        def fn(page, i=anim_id):
            select_animation(page, i)
            print(f"  Selected animation id={i}")
        _cmd_queue.put(fn)
        return

    if cmd == "next":
        _cmd_queue.put(lambda page: confirm_review(page))
        return

    if cmd == "back":
        _cmd_queue.put(lambda page: upload_back(page))
        return

    if cmd == "close":
        _cmd_queue.put(lambda page: upload_close(page))
        return

    if cmd == "upload" and len(parts) >= 2:
        path = " ".join(parts[1:])
        def fn(page, p=path):
            upload_file(page, p)
            print(f"  Uploading: {p}")
        _cmd_queue.put(fn)
        return

    print(f"  Unknown command '{cmd}'. Type 'help'.")


if __name__ == "__main__":
    main()
