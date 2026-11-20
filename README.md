# Cubot kiosk

Cubot is the welcome robot on the SPACElogic kiosk PC: animated face, voice, directions with 2D/3D maps, people
finder, parcels (Telegram), Makerspace lights, timers, internet search and a local AI (Ollama).

## How updates reach the kiosk

1. Change the files in this repo (for example with Claude Code) and push to `main`.
2. The kiosk picks it up by itself:
   - every time Cubot opens (`start-kiosk.bat` runs `cubot-update.py` first), and
   - every 2 hours while it is on (`kiosk-server.py`). The page reloads itself when nobody is using it.
3. Only the files listed in `kiosk-manifest.json` → `files` are installed. Old versions go to `backups/` (last 5).

No internet or GitHub down? Cubot starts with the version it already has.

## What stays on the kiosk PC only (never in this repo)

| File | What it holds |
|---|---|
| `office-info.txt` | Company facts, places, staff, Telegram bot token, the kiosk's light key |
| `kiosk-config.json` | This PC's own settings: model, greeting, lights PIN, update settings (see `kiosk-config.example.json`) |
| `kiosk-settings.json` | Saved voice, timers, scheduled lights, Telegram sign-ups |

`.gitignore` keeps them out. **Never commit them**: the repo is public.

## Files

| File | Job |
|---|---|
| `welcome-kiosk.html` | The whole kiosk app (one page). `CONFIG` at the top holds the default settings |
| `building-3d.js` | Floor plans for routes and the 3D walk-through |
| `kiosk-server.py` | Local web server on 127.0.0.1:8000: serves the page, internet search, saved settings, PC hardware, update checks |
| `cubot-update.py` | Downloads and installs a new version from GitHub, and the best AI model for the PC |
| `kiosk-manifest.json` | Version, which files an update installs, and the AI model tiers |
| `start-kiosk.bat` / `stop-kiosk.bat` | Open / close the kiosk on Windows |
| `map-L1.svg` … `map-L6.svg` | 2D floor maps |
| `three.min.js`, `orbit-controls.js` | 3D walk-through |
| `vision/` | Face detection (MediaPipe) for greeting people |
| `ocr/` | Reads parcel labels from the camera (Tesseract) |

## AI model

`model: "auto"` picks the first model in `kiosk-manifest.json` → `models` that fits the PC's graphics card memory
(`minVramGB`) or RAM (`minRamGB`), and the updater downloads it in the background. To fix a model, put
`"model": "qwen3:8b"` in the kiosk's `kiosk-config.json`. Press **F9** on the kiosk to see the PC, version and model.
