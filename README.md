# mixamo-mcp

A Playwright-based automation tool for [Mixamo](https://www.mixamo.com), with both a CLI operator and an MCP server for Claude Code integration.

## Features

- Browse and search animations
- Upload custom characters (FBX / OBJ / ZIP) via Auto-Rigger
- Set animation parameters (inplace, mirror, overdrive, arm-space, trim)
- Download animations with your character (FBX for Unity/Unreal, Collada)
- Persistent browser session — log in once, stays logged in
- MCP server so Claude Code can drive everything as tools

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

## CLI usage

```bash
python main.py
```

Available commands:

| Command | Description |
|---|---|
| `list [query]` | List animations, optionally filtered by query |
| `select <id>` | Select animation by ID |
| `set inplace true/false` | Toggle in-place mode |
| `set mirror true/false` | Toggle mirror |
| `set overdrive <0-100>` | Set overdrive slider |
| `upload <path>` | Upload a character file |
| `download <path>` | Download current animation |
| `status` | Show current screen and animation info |
| `quit` | Exit |

## MCP server (Claude Code)

The MCP server lets Claude Code control Mixamo directly as tools.

### Configure

Add to your `.mcp.json` (already included in this repo):

```json
{
  "mcpServers": {
    "mixamo": {
      "command": "python",
      "args": ["C:\\Users\\vital\\Projects\\mixamo-mcp\\mcp_server.py"]
    }
  }
}
```

### Available tools

| Tool | Description |
|---|---|
| `status()` | Current screen, character, animation, params |
| `list_animations(query)` | Search animations: IDs, names, descriptions, packs and the real total |
| `select_animation(id)` | Select animation by ID |
| `set_param(name, value)` | Set inplace / mirror / overdrive / arm-space / trim |
| `upload_character(path)` | Upload character to Auto-Rigger |
| `download_animation(path, format, skin, fps)` | Download animation |
| `confirm_review()` | Confirm Auto-Rigger review step |
| `close_upload_modal()` | Dismiss upload modal |

### Download formats

| Key | Format |
|---|---|
| `fbx_unity` | FBX for Unity (default) |
| `fbx` | FBX 2019 |
| `fbx_ascii` | FBX 2019 ASCII |
| `fbx_7.4` | FBX 2014 |
| `fbx_6.1` | FBX 6.1 |
| `collada` | Collada (.dae) |

## Tests

```bash
python -m unittest discover -s tests -t .
```

The tests need no login or network: `tests/fixtures/` holds real search responses from Mixamo.

## Notes

- Do not run `main.py` and `mcp_server.py` at the same time — both use the same browser profile
- Log in once via the visible browser; session is saved in `browser_profile/`
