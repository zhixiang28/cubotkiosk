"""
Cubot auto-updater
------------------
Checks GitHub for a newer version of Cubot and installs it. start-kiosk.bat runs it every time the kiosk opens,
and kiosk-server.py runs it again every few hours while the kiosk is on.

  * Only the program files listed in kiosk-manifest.json are updated.
  * Your own files are never touched: office-info.txt, kiosk-config.json, kiosk-settings.json, python-path.txt.
  * The old files are kept in the "backups" folder (last 5 updates), so an update can be undone by copying them back.
  * No internet, or GitHub is down? Cubot simply starts with the version it already has.

Settings (optional) in kiosk-config.json:
  "updateRepo":   "zhixiang28/cubotkiosk"   which GitHub repo to follow
  "updateBranch": "main"
  "autoUpdate":   false                     to switch updates off
  "githubToken":  "..."                     only needed if the repo is private (a read-only token)

Run by hand:  python cubot-update.py           (check and install)
              python cubot-update.py --check   (only say whether there is an update)
Exit codes:   0 nothing to do / updated / offline     10 updated and start-kiosk.bat must restart
"""
import fnmatch
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REPO = "zhixiang28/cubotkiosk"
VERSION_FILE = os.path.join(HERE, ".cubot-version")
LOG_FILE = os.path.join(HERE, "update-log.txt")
# never written by an update, even if someone lists them in the manifest
PROTECTED = {"office-info.txt", "kiosk-config.json", "kiosk-settings.json", "python-path.txt", ".cubot-version",
             "update-log.txt"}
UA = "CubotKiosk-Updater/1.0"


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if os.path.getsize(LOG_FILE) > 200_000:                      # keep the log small
            with open(LOG_FILE, encoding="utf-8") as f:
                tail = f.readlines()[-500:]
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.writelines(tail)
    except OSError:
        pass


def local_config():
    try:
        with open(os.path.join(HERE, "kiosk-config.json"), encoding="utf-8-sig") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def http(url, token="", accept=None, timeout=15):
    h = {"User-Agent": UA}
    if accept:
        h["Accept"] = accept
    if token:
        h["Authorization"] = "Bearer " + token
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        return r.read()


def current_version():
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def latest_sha(repo, branch, token):
    return http(f"https://api.github.com/repos/{repo}/commits/{branch}", token,
                accept="application/vnd.github.sha", timeout=8).decode().strip()


def download(repo, sha, token):
    if token:   # private repo: the API zip link works with a token
        data = http(f"https://api.github.com/repos/{repo}/zipball/{sha}", token, timeout=120)
    else:
        data = http(f"https://codeload.github.com/{repo}/zip/{sha}", timeout=120)
    z = zipfile.ZipFile(io.BytesIO(data))
    root = z.namelist()[0].split("/")[0] + "/"                       # GitHub puts everything in one folder
    return z, root


def safe_rel(path):
    p = path.replace("\\", "/").lstrip("/")
    if not p or p.startswith("../") or "/../" in p or ":" in p:
        return None
    if os.path.basename(p) in PROTECTED or p.split("/")[0] in ("backups", "browser-profile", "browser-profile-chrome"):
        return None
    return p


def plan(z, root, manifest):
    """Which files from the download to install: everything matching the manifest's "files" patterns."""
    pats = manifest.get("files") or []
    out = {}
    for name in z.namelist():
        if not name.startswith(root) or name.endswith("/"):
            continue
        rel = safe_rel(name[len(root):])
        if rel and any(fnmatch.fnmatch(rel, p) for p in pats):
            out[rel] = z.read(name)
    return out


def install(files, old_sha):
    changed = []
    for rel, data in files.items():
        dest = os.path.join(HERE, *rel.split("/"))
        try:
            with open(dest, "rb") as f:
                if f.read() == data:
                    continue
        except OSError:
            pass
        changed.append(rel)
    if not changed:
        return []
    stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + (old_sha[:7] or "first")
    bdir = os.path.join(HERE, "backups", stamp)
    for rel in changed:
        dest = os.path.join(HERE, *rel.split("/"))
        if os.path.exists(dest):
            os.makedirs(os.path.dirname(os.path.join(bdir, rel)), exist_ok=True)
            shutil.copy2(dest, os.path.join(bdir, rel))
    for rel in changed:
        dest = os.path.join(HERE, *rel.split("/"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if rel.lower() == "start-kiosk.bat":
            dest += ".new"          # the running start-kiosk.bat swaps itself in safely (see start-kiosk.bat)
        tmp = dest + ".tmp"
        with open(tmp, "wb") as f:
            f.write(files[rel])
        os.replace(tmp, dest)
    # keep only the 5 newest backups
    try:
        olds = sorted(os.listdir(os.path.join(HERE, "backups")))
        for d in olds[:-5]:
            shutil.rmtree(os.path.join(HERE, "backups", d), ignore_errors=True)
    except OSError:
        pass
    return changed


def find_ollama():
    for p in (os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe"), os.path.join(HERE, "Ollama", "ollama.exe")):
        if os.path.exists(p):
            return p
    return shutil.which("ollama")


def pull_models(manifest):
    """Download the smartest AI model this PC can run fast (from the manifest's "models" list), in the background
    so Cubot can start straight away. Skipped when kiosk-config.json fixes a model, or Ollama is not running."""
    cfg = local_config()
    tiers = manifest.get("models") or []
    if not tiers or (cfg.get("model") and cfg.get("model") != "auto") or cfg.get("autoModel") is False:
        return
    try:
        tags = json.loads(http("http://127.0.0.1:11434/api/tags", timeout=3))
        have = {m.get("name", "") for m in tags.get("models", [])}
        hw = json.loads(http("http://127.0.0.1:8000/api/hardware", timeout=10))
    except Exception:  # noqa: BLE001
        return                                                       # try again at the next check
    vram, ram = hw.get("vramGB", 0), hw.get("ramGB", 0)
    for t in tiers:
        ok = (t.get("minVramGB") and vram >= t["minVramGB"]) or (t.get("minRamGB") and ram >= t["minRamGB"]) \
            or (not t.get("minVramGB") and not t.get("minRamGB"))
        if not ok:
            continue
        name = t["model"]
        if name in have or name + ":latest" in have:
            return                                                   # already has the best one
        exe = find_ollama()
        if exe:
            log(f"Downloading the AI model {name} for this PC in the background (Cubot uses it once it is ready)")
            flags = 0x08000000 if os.name == "nt" else 0               # no console window
            subprocess.Popen([exe, "pull", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        return


def run(check_only=False):
    cfg = local_config()
    if cfg.get("autoUpdate") is False:
        return 0
    repo = cfg.get("updateRepo") or DEFAULT_REPO
    branch = cfg.get("updateBranch") or "main"
    token = cfg.get("githubToken") or ""
    cur = current_version()
    try:
        sha = latest_sha(repo, branch, token)
    except Exception as e:  # noqa: BLE001
        log(f"Could not check for updates ({e.__class__.__name__}: {e}). Starting the current version.")
        return 0
    if sha == cur.get("sha"):
        print("Cubot is up to date.", flush=True)
        try:
            with open(os.path.join(HERE, "kiosk-manifest.json"), encoding="utf-8-sig") as f:
                pull_models(json.load(f))
        except (OSError, ValueError):
            pass
        return 0
    if check_only:
        print(f"Update available: {sha[:7]} (now {cur.get('sha', 'unknown')[:7]})", flush=True)
        return 0
    log(f"New version {sha[:7]} found (was {cur.get('sha', 'none')[:7]}). Downloading...")
    try:
        z, root = download(repo, sha, token)
        manifest = json.loads(z.read(root + "kiosk-manifest.json").decode("utf-8-sig"))
        files = plan(z, root, manifest)
        if "welcome-kiosk.html" not in files:
            raise ValueError("the download has no welcome-kiosk.html, so it was not installed")
        changed = install(files, cur.get("sha", ""))
    except Exception as e:  # noqa: BLE001
        log(f"Update failed, keeping the current version: {e.__class__.__name__}: {e}")
        return 0
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        json.dump({"sha": sha, "version": manifest.get("version", ""), "installed": time.strftime("%Y-%m-%d %H:%M"),
                   "repo": repo, "changed": changed}, f, indent=1)
    log(f"Updated to {manifest.get('version', sha[:7])}: {', '.join(changed) or 'no file changes'}")
    for note in manifest.get("notes", [])[:5]:
        log("  - " + note)
    pull_models(manifest)
    return 10 if "start-kiosk.bat" in changed else 0


if __name__ == "__main__":
    sys.exit(run("--check" in sys.argv))
