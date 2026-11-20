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

If Python can't reach GitHub (school/office network, certificates, proxy), the updater tries again with Windows'
own `curl.exe` and then PowerShell. When Cubot opens right after the PC starts, it waits up to 45 seconds for Wi-Fi
(`updateWaitSeconds` in `kiosk-config.json`).

**Update by hand:** double-click `update-cubot.bat` in the Cubot folder. It downloads the newest updater first, so
it also fixes a kiosk whose updater is too old to work, then installs the update, shows the log and offers to
restart Cubot. If the kiosk doesn't have this file yet, download it once from GitHub (open the file, then
*Download raw file*) into the Cubot folder.

## Face memory

Say or type **"remember me"** (or "my name is ..."). Cubot asks for the name and for permission, then learns the
face and greets that person by name next time. **"Who am I?"** checks, **"forget me"** deletes that person, and
**"forget all faces"** deletes everyone (with a confirm button). It runs only on the kiosk PC (`vision/faces`,
face-api.js, MIT licence). Cubot keeps 128 numbers per face sample in `kiosk-settings.json`, never a photo.
Switch it off with `"faceMemory": false` in `kiosk-config.json`. `"faceMatch"` (default 0.5) sets how strict it is:
lower means fewer mix-ups but more "I don't think we've met".

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
| `update-cubot.bat` | Double-click to update Cubot now (gets the newest updater first, then offers a restart) |
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
