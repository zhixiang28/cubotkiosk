# Notes for Claude Code

This repo is installed on a Windows kiosk PC that auto-updates from `main` (see README.md). Anything pushed to
`main` goes live on the kiosk within 2 hours, or the next time it starts.

## Rules
- **Never commit secrets or staff data**: no `office-info.txt`, `kiosk-config.json`, `kiosk-settings.json`, Telegram
  bot tokens, the kiosk light key, Telegram chat IDs, or Supabase secret/service keys. The Supabase *publishable* key in
  `welcome-kiosk.html` is fine (it is public by design).
- When you add a file the kiosk needs, add it to `files` in `kiosk-manifest.json`, or the kiosk will never get it.
- Bump `version` in `kiosk-manifest.json` (YYYY.MM.DD, add .2, .3 for more the same day) and add a short `notes` line.
- Don't rename or remove `cubot-update.py`, `kiosk-manifest.json` or the update block in `start-kiosk.bat`:
  they are how the kiosk updates. A broken updater means someone has to fix the kiosk by hand.
- Per-PC settings belong in the kiosk's `kiosk-config.json` (merged over `CONFIG` by kiosk-server.py), not in
  `CONFIG` defaults.
- `start-kiosk.bat` must keep Windows line endings (CRLF).

## Checks before pushing
- `python -c "import ast; ast.parse(open('kiosk-server.py').read()); ast.parse(open('cubot-update.py').read())"`
- `node -e` or a browser: the main `<script>` in `welcome-kiosk.html` must parse.
- `python -m json.tool kiosk-manifest.json`
