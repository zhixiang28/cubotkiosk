"""
Cubot kiosk web server
----------------------
Serves the kiosk files to the browser on this PC only (127.0.0.1:8000) and lets Cubot look things up
on the internet:

  /api/search?q=...   web search. Uses Ollama web search when an API key is set in office-info.txt
                      ([INTERNET] section, "ollama api key | ..."), otherwise Wikipedia.
                      Weather questions also get a live forecast from Open-Meteo (free, no key).
  /api/status         which search the kiosk is using (shown on the F9 screen)
  /api/settings       the kiosk's saved settings (voice, timers, scheduled lights, Telegram sign-ups) in kiosk-settings.json
  /api/hardware       this PC's memory and graphics card, so Cubot can pick the best AI model for it
  /api/version        which Cubot version is installed (the page reloads itself when an update arrives)

It also serves welcome-kiosk.html with your own settings from kiosk-config.json mixed in, and checks GitHub for
updates every few hours (see cubot-update.py).

Start it with:  python kiosk-server.py      (start-kiosk.bat does this for you)
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8000
UA = "CubotKiosk/1.0 (office welcome kiosk)"
SETTINGS = os.path.join(HERE, "kiosk-settings.json")
CONFIG_FILE = os.path.join(HERE, "kiosk-config.json")
PRIVATE_CONFIG = {"githubToken"}          # never sent to the page
_hw_cache = {}


def local_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8-sig") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError) as e:
        if os.path.exists(CONFIG_FILE):
            sys.stderr.write(f"kiosk-config.json has a mistake and was ignored: {e}\n")
        return {}


def hardware():
    """Memory and graphics card(s), measured once."""
    if _hw_cache:
        return _hw_cache
    ram = 0.0
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS(); m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            ram = m.ullTotalPhys / 1024 ** 3
        else:
            with open("/proc/meminfo") as f:
                ram = int(f.readline().split()[1]) / 1024 ** 2
    except Exception:  # noqa: BLE001
        pass
    gpus = []
    smi = shutil.which("nvidia-smi") or (r"C:\Windows\System32\nvidia-smi.exe" if os.name == "nt" else None)
    if smi and os.path.exists(smi):
        try:
            out = subprocess.run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], capture_output=True,
                                 text=True, timeout=8, creationflags=0x08000000 if os.name == "nt" else 0).stdout
            for line in out.strip().splitlines():
                name, mem = [x.strip() for x in line.rsplit(",", 1)]
                gpus.append({"name": name, "vramGB": round(int(mem) / 1024, 1)})
        except Exception:  # noqa: BLE001
            pass
    cpu = ""
    try:
        if os.name == "nt":
            import winreg
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            cpu = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        else:
            with open("/proc/cpuinfo") as f:
                cpu = next((l.split(":", 1)[1].strip() for l in f if l.startswith("model name")), "")
    except Exception:  # noqa: BLE001
        pass
    _hw_cache.update({"ramGB": round(ram, 1), "gpus": gpus, "vramGB": max([g["vramGB"] for g in gpus], default=0),
                      "cpu": cpu, "threads": os.cpu_count() or 0})
    return _hw_cache


def version_info():
    try:
        with open(os.path.join(HERE, ".cubot-version"), encoding="utf-8") as f:
            v = json.load(f)
    except (OSError, ValueError):
        v = {}
    try:
        v["page"] = int(os.path.getmtime(os.path.join(HERE, "welcome-kiosk.html")))
    except OSError:
        v["page"] = 0
    return v


def updater_loop():
    """Check GitHub for updates a few minutes after start, then every few hours."""
    path = os.path.join(HERE, "cubot-update.py")
    time.sleep(180)
    while True:
        cfg = local_config()
        if os.path.exists(path) and cfg.get("autoUpdate") is not False:
            try:
                spec = importlib.util.spec_from_file_location("cubot_update", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                before = os.path.getmtime(__file__)
                mod.run()
                if os.path.getmtime(__file__) != before:      # this server was updated: restart it
                    sys.stderr.write("kiosk-server.py was updated, restarting it\n")
                    time.sleep(2)
                    os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)] + sys.argv[1:])
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"update check failed: {e}\n")
        time.sleep(max(0.5, float(cfg.get("updateEveryHours", 2))) * 3600)
WEATHER_WORDS = re.compile(r"\b(weather|rain|raining|rainy|forecast|temperature|hot|cold|sunny|umbrella|humid|humidity|storm|thunder)\b", re.I)
WMO = {0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "cloudy", 45: "foggy", 48: "foggy",
       51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
       80: "light showers", 81: "showers", 82: "heavy showers", 95: "thunderstorms", 96: "thunderstorms with hail",
       99: "thunderstorms with hail"}


def settings():
    """Read the [INTERNET] section of office-info.txt every time, so edits work without a restart."""
    out = {"key": os.environ.get("OLLAMA_API_KEY", "").strip(), "place": "Singapore", "lat": 1.3521, "lon": 103.8198}
    try:
        with open(os.path.join(HERE, "office-info.txt"), encoding="utf-8-sig") as f:
            text = f.read()
    except OSError:
        return out
    sec = re.search(r"^\[INTERNET\][^\n]*\n(.*?)(?=^\[|\Z)", text, re.M | re.S)
    if not sec:
        return out
    for line in sec.group(1).splitlines():
        if "|" not in line or line.strip().startswith("#"):
            continue
        k, v = [p.strip() for p in line.split("|", 1)]
        k = k.lower()
        if k in ("ollama api key", "api key", "ollama key") and v:
            out["key"] = v
        elif k in ("weather place", "city", "place") and v:
            out["place"] = v
        elif k in ("weather lat lon", "lat lon", "location") and v:
            try:
                out["lat"], out["lon"] = [float(x) for x in re.split(r"[ ,]+", v)[:2]]
            except ValueError:
                pass
    return out


def get_json(url, data=None, headers=None, timeout=10):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h, method="POST" if body else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def ollama_search(q, key):
    d = get_json("https://ollama.com/api/web_search", {"query": q, "max_results": 4},
                 {"Authorization": "Bearer " + key})
    return [{"title": r.get("title", ""), "url": r.get("url", ""), "content": (r.get("content") or "")[:1500]}
            for r in d.get("results", [])]


def wikipedia_search(q):
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "generator": "search", "gsrsearch": q, "gsrlimit": 3, "prop": "extracts|info",
        "exintro": 1, "explaintext": 1, "exsentences": 6, "inprop": "url", "format": "json", "formatversion": 2})
    pages = (get_json(url).get("query") or {}).get("pages") or []
    pages.sort(key=lambda p: p.get("index", 99))
    return [{"title": p.get("title", ""), "url": p.get("fullurl", ""), "content": p.get("extract", "")}
            for p in pages if p.get("extract")]


def weather(q, cfg):
    place, lat, lon = cfg["place"], cfg["lat"], cfg["lon"]
    m = re.search(r"\b(?:in|at|for)\s+([A-Za-z][A-Za-z .'-]{1,40}?)(?:\s+(?:today|tomorrow|now|this|next|tonight)\b|[?.!]|$)", q)
    if m and m.group(1).strip().lower() not in ("the office", "here", "office", "the morning", "the afternoon", "the evening"):
        g = get_json("https://geocoding-api.open-meteo.com/v1/search?" +
                     urllib.parse.urlencode({"name": m.group(1).strip(), "count": 1}))
        if g.get("results"):
            r = g["results"][0]
            place, lat, lon = ", ".join(x for x in (r.get("name"), r.get("country")) if x), r["latitude"], r["longitude"]
    d = get_json("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 2,
        "current": "temperature_2m,relative_humidity_2m,weather_code,precipitation",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"}))
    c, dl = d.get("current", {}), d.get("daily", {})

    def day(i, name):
        try:
            return (f"{name}: {WMO.get(dl['weather_code'][i], 'mixed weather')}, {round(dl['temperature_2m_min'][i])} to "
                    f"{round(dl['temperature_2m_max'][i])} degrees Celsius, {dl['precipitation_probability_max'][i]}% chance of rain.")
        except (KeyError, IndexError, TypeError):
            return ""
    now = (f"Weather in {place} right now ({c.get('time', '')} local time): {WMO.get(c.get('weather_code'), 'mixed weather')}, "
           f"{round(c.get('temperature_2m', 0))} degrees Celsius, humidity {c.get('relative_humidity_2m', '?')}%.")
    return {"title": f"Weather forecast for {place} (Open-Meteo)", "url": "https://open-meteo.com",
            "content": " ".join(x for x in (now, day(0, "Today"), day(1, "Tomorrow")) if x)}


def search(q):
    cfg = settings()
    results, used, errors = [], "", []
    if WEATHER_WORDS.search(q):
        try:
            results.append(weather(q, cfg))
            used = "open-meteo"
        except Exception as e:  # noqa: BLE001
            errors.append(f"weather: {e}")
    if cfg["key"]:
        try:
            results += ollama_search(q, cfg["key"])
            used = used + "+ollama" if used else "ollama"
        except Exception as e:  # noqa: BLE001
            errors.append(f"ollama: {e}")
    if len(results) < 2 and not (used and "ollama" in used):
        try:
            results += wikipedia_search(q)
            used = used + "+wikipedia" if used else "wikipedia"
        except Exception as e:  # noqa: BLE001
            errors.append(f"wikipedia: {e}")
    return {"query": q, "results": results[:5], "source": used, "errors": errors}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=HERE, **kw)

    def end_headers(self):
        if self.path.split("?")[0].endswith((".html", ".js", ".txt", ".json")) or self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/search":
            q = (urllib.parse.parse_qs(u.query).get("q") or [""])[0].strip()[:200]
            if not q:
                return self.send_json({"error": "missing q"}, 400)
            t = time.time()
            out = search(q)
            out["ms"] = int((time.time() - t) * 1000)
            sys.stderr.write(f"search {q!r}: {len(out['results'])} results via {out['source'] or 'nothing'} "
                             f"in {out['ms']} ms {'; '.join(out['errors'])}\n")
            return self.send_json(out)
        if u.path == "/api/status":
            return self.send_json({"server": "kiosk-server", "search": "ollama" if settings()["key"] else "wikipedia"})
        if u.path == "/api/settings":
            try:
                with open(SETTINGS, encoding="utf-8") as f:
                    return self.send_json(json.load(f))
            except (OSError, ValueError):
                return self.send_json({})
        if u.path == "/api/hardware":
            return self.send_json(hardware())
        if u.path == "/api/version":
            return self.send_json(version_info())
        if u.path in ("/kiosk-settings.json", "/kiosk-config.json", "/.cubot-version", "/update-log.txt"):
            return self.send_json({"error": "private"}, 404)
        if u.path in ("/", "", "/welcome-kiosk.html"):
            return self.send_page()
        return super().do_GET()

    def send_page(self):
        """welcome-kiosk.html with this PC's own settings (kiosk-config.json) mixed in, so updates never lose them."""
        try:
            with open(os.path.join(HERE, "welcome-kiosk.html"), encoding="utf-8") as f:
                html = f.read()
        except OSError:
            return self.send_json({"error": "welcome-kiosk.html is missing"}, 404)
        cfg = {k: v for k, v in local_config().items() if k not in PRIVATE_CONFIG}
        inject = ("<script>window.KIOSK_OVERRIDES = " + json.dumps(cfg).replace("</", "<\\/") +
                  "; window.KIOSK_VERSION = " + json.dumps(version_info()) + ";</script>")
        html = html.replace("<head>", "<head>\n" + inject, 1)
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/api/settings":
            return self.send_json({"error": "not found"}, 404)
        n = int(self.headers.get("Content-Length") or 0)
        if not 0 < n <= 2_000_000:
            return self.send_json({"error": "too big"}, 413)
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("settings must be an object")
            tmp = SETTINGS + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, SETTINGS)          # never leaves a half-written file
            return self.send_json({"ok": True})
        except Exception as e:  # noqa: BLE001
            return self.send_json({"error": str(e)}, 400)

    def log_message(self, fmt, *args):  # keep the console quiet: only errors
        if args and str(args[1] if len(args) > 1 else "").startswith(("4", "5")) and "favicon" not in str(args[0]):
            sys.stderr.write("%s\n" % (fmt % args))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    print(f"Cubot kiosk server on http://localhost:{port}  (search: {'Ollama web search' if settings()['key'] else 'Wikipedia'})")
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=hardware, daemon=True).start()          # measure the PC once, early
    threading.Thread(target=updater_loop, daemon=True).start()
    srv.serve_forever()
