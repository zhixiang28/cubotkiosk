"""
Cubot auto-updater
------------------
Checks GitHub for a newer version of Cubot and installs it. start-kiosk.bat runs it every time the kiosk opens,
and kiosk-server.py runs it again every few hours while the kiosk is on.

  * Only the program files listed in kiosk-manifest.json are updated.
  * Your own files are never touched: office-info.txt, kiosk-config.json, kiosk-settings.json, python-path.txt.
  * The old files are kept in the "backups" folder (last 5 updates), so an update can be undone by copying them back.
  * No internet, or GitHub is down? Cubot simply starts with the version it already has.
  * If Python cannot reach GitHub (school/office network, certificates, proxy), it tries again with Windows' own
    curl.exe and PowerShell, and it waits up to "updateWaitSeconds" (default 45) for Wi-Fi when the PC has just started.

Settings (optional) in kiosk-config.json:
  "updateRepo":   "zhixiang28/cubotkiosk"   which GitHub repo to follow
  "updateBranch": "main"
  "autoUpdate":   false                     to switch updates off
  "githubToken":  "..."                     only needed if the repo is private (a read-only token)
  "updateWaitSeconds": 45                   how long to wait for the internet when Cubot opens (0 = don't wait)

Run by hand:  python cubot-update.py           (check and install)
              python cubot-update.py --check   (only say whether there is an update)
              update-cubot.bat                 (double-click: gets the newest updater first, then updates)
Exit codes:   0 nothing to do / updated / offline     10 updated and start-kiosk.bat must restart
"""
import fnmatch
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
UA = "CubotKiosk-Updater/1.1"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0                # run curl/PowerShell without a console window


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


def _urllib(url, headers, timeout):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return r.read()


def _curl(url, headers, timeout):
    """Windows 10/11 has curl.exe built in. It uses the Windows certificate store, so it often works where Python's
    own HTTPS fails (school/office networks that check the traffic)."""
    exe = shutil.which("curl.exe") or shutil.which("curl")
    if not exe:
        raise OSError("curl is not installed")
    out = tempfile.NamedTemporaryFile(delete=False, dir=HERE, prefix=".dl-", suffix=".tmp")
    out.close()
    try:
        base = [exe, "-fsSL", "--max-time", str(int(timeout)), "-o", out.name]
        for k, v in headers.items():
            base += ["-H", f"{k}: {v}"]
        tries = [base + ["--ssl-revoke-best-effort", url], base + [url]] if os.name == "nt" else [base + [url]]
        for cmd in tries:
            r = subprocess.run(cmd, capture_output=True, timeout=timeout + 20, creationflags=NO_WINDOW)
            if r.returncode == 0:
                with open(out.name, "rb") as f:
                    return f.read()
            if r.returncode != 2:                                    # 2 = this curl is too old for that option
                break
        raise OSError(f"curl error {r.returncode}: {r.stderr.decode(errors='replace').strip()[:200]}")
    finally:
        try:
            os.remove(out.name)
        except OSError:
            pass


def _powershell(url, headers, timeout):
    """Last try: PowerShell uses the Windows proxy settings and certificates."""
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        raise OSError("PowerShell is not available")
    out = tempfile.NamedTemporaryFile(delete=False, dir=HERE, prefix=".dl-", suffix=".tmp")
    out.close()
    script = ("$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue';"
              "try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {};"
              "try { [Net.WebRequest]::DefaultWebProxy.Credentials = [Net.CredentialCache]::DefaultNetworkCredentials } catch {};"
              "$h = @{}; if ($env:CUBOT_AUTH) { $h['Authorization'] = $env:CUBOT_AUTH };"
              "Invoke-WebRequest -UseBasicParsing -Uri $env:CUBOT_URL -Headers $h -UserAgent $env:CUBOT_UA"
              " -TimeoutSec ([int]$env:CUBOT_TIMEOUT) -OutFile $env:CUBOT_OUT")
    env = dict(os.environ, CUBOT_URL=url, CUBOT_OUT=out.name, CUBOT_UA=headers.get("User-Agent", UA),
               CUBOT_AUTH=headers.get("Authorization", ""), CUBOT_TIMEOUT=str(int(timeout)))
    try:
        r = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                           capture_output=True, timeout=timeout + 40, env=env, creationflags=NO_WINDOW)
        if r.returncode != 0:
            msg = (r.stderr or r.stdout).decode(errors="replace").strip().splitlines()
            raise OSError("PowerShell: " + (msg[0][:200] if msg else f"error {r.returncode}"))
        with open(out.name, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(out.name)
        except OSError:
            pass


def http(url, token="", accept=None, timeout=15):
    """Download a URL. Tries Python first, then curl.exe, then PowerShell; raises only if all of them fail."""
    h = {"User-Agent": UA}
    if accept:
        h["Accept"] = accept
    if token:
        h["Authorization"] = "Bearer " + token
    if url.startswith("http://127.0.0.1"):                          # local (Ollama, kiosk server): Python only
        return _urllib(url, h, timeout)
    errors = []
    for name, fn in (("Python", _urllib), ("curl", _curl), ("PowerShell", _powershell)):
        try:
            data = fn(url, h, timeout)
            if name != "Python":
                log(f"(Python could not reach GitHub, so {name} was used instead)")
            return data
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e.__class__.__name__}: {e}"[:300])
    raise OSError(" | ".join(errors))


def current_version():
    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def latest_sha(repo, branch, token):
    """The newest commit on the branch. Asks the GitHub API first; if that fails (blocked, or its limit of 60
    checks an hour is used up), reads it straight from GitHub's git server, which has no such limit."""
    try:
        data = http(f"https://api.github.com/repos/{repo}/commits/{branch}", token, timeout=10).decode().strip()
        sha = json.loads(data)["sha"] if data.startswith("{") else data
        if re.fullmatch(r"[0-9a-f]{40}", sha):
            return sha
        raise ValueError(f"unexpected answer from GitHub: {data[:80]!r}")
    except Exception as e:  # noqa: BLE001
        if token:
            raise
        first = e
    try:
        refs = http(f"https://github.com/{repo}.git/info/refs?service=git-upload-pack", timeout=15).decode(errors="replace")
    except Exception as e:  # noqa: BLE001
        raise OSError(f"{first} || {e}") from None
    m = re.search(r"([0-9a-f]{40}) refs/heads/" + re.escape(branch) + r"\b", refs)
    if not m:
        raise OSError(f"{first} || branch {branch!r} was not found on GitHub")
    return m.group(1)


def download(repo, sha, token):
    if token:   # private repo: the API zip link works with a token
        data = http(f"https://api.github.com/repos/{repo}/zipball/{sha}", token, timeout=120)
    else:
        try:
            data = http(f"https://codeload.github.com/{repo}/zip/{sha}", timeout=180)
        except Exception:  # noqa: BLE001
            data = http(f"https://github.com/{repo}/archive/{sha}.zip", timeout=180)
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
            subprocess.Popen([exe, "pull", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=NO_WINDOW)
        return


def looks_offline(err):
    """True when the PC is not on the internet yet (Wi-Fi still connecting after start-up)."""
    t = str(err).lower()
    return any(w in t for w in ("getaddrinfo", "name or service", "nodename", "resolve host", "could not resolve",
                                "network is unreachable", "no such host", "remote name could not be resolved",
                                "unable to connect", "connection refused", "actively refused", "10051", "10065"))


def run(check_only=False, wait=0):
    cfg = local_config()
    if cfg.get("autoUpdate") is False:
        return 0
    repo = cfg.get("updateRepo") or DEFAULT_REPO
    branch = cfg.get("updateBranch") or "main"
    token = cfg.get("githubToken") or ""
    cur = current_version()
    give_up = time.time() + max(0, wait)
    while True:
        try:
            sha = latest_sha(repo, branch, token)
            break
        except Exception as e:  # noqa: BLE001
            if looks_offline(e) and time.time() + 10 < give_up:
                print("No internet yet, trying again in 10 seconds...", flush=True)
                time.sleep(10)
                continue
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
    try:
        _wait = float(local_config().get("updateWaitSeconds", 45))
    except (TypeError, ValueError):
        _wait = 45
    if "--now" in sys.argv or "--check" in sys.argv:
        _wait = 0
    sys.exit(run("--check" in sys.argv, wait=_wait))
