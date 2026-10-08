#!/usr/bin/env python3
"""LanPC server (Python, standard library only).  Run:  python server.py"""
import hashlib, hmac, json, mimetypes, os, platform, queue, secrets, shutil, socket, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT", 8080))
BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(BASE, "shared")              # the shared "drive"
PUB = os.path.join(BASE, "public")
CFG = os.path.join(BASE, "system", "config.json")  # account + theme (never exposed through the files API)
THEMES = {"teal", "midnight", "graphite", "paper", "forest", "rose"}
os.makedirs(ROOT, exist_ok=True)
os.makedirs(os.path.dirname(CFG), exist_ok=True)
START = time.time()
SRV = None

try:
    import psutil                                # optional, only improves stats
except ImportError:
    psutil = None


def inside(base, p):
    """Resolve p under base; return None if it escapes."""
    f = os.path.realpath(os.path.join(base, str(p or "").lstrip("/\\")))
    b = os.path.realpath(base)
    return f if f == b or f.startswith(b + os.sep) else None


# ---------------- account / config ----------------
cfg_lock = threading.Lock()
tokens = set()


def load_cfg():
    try:
        with open(CFG) as fh:
            return json.load(fh)
    except Exception:
        return None


def save_cfg(c):
    tmp = CFG + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(c, fh)
    os.replace(tmp, CFG)


def hash_pw(pw, salt=None):
    salt = salt or os.urandom(16)
    return salt.hex(), hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 200_000).hex()


def check_pw(c, pw):
    _, h = hash_pw(pw, bytes.fromhex(c["salt"]))
    return hmac.compare_digest(h, c["hash"])


def new_token():
    t = secrets.token_urlsafe(24)
    tokens.add(t)
    return t


def wipe_everything():
    for n in os.listdir(ROOT):
        p = os.path.join(ROOT, n)
        shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)
    with cfg_lock:
        if os.path.exists(CFG):
            os.remove(CFG)
    with lock:
        history.clear()
    tokens.clear()


# ---------------- system stats ----------------
def _win_mem():
    import ctypes
    class MS(ctypes.Structure):
        _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                    ("tpf", ctypes.c_ulonglong), ("apf", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong),
                    ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]
    m = MS(); m.l = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.tp, m.ap


def mem():
    try:
        if psutil:
            v = psutil.virtual_memory(); return v.total, v.available
        if os.path.exists("/proc/meminfo"):
            d = {l.split(":")[0]: int(l.split()[1]) * 1024 for l in open("/proc/meminfo")}
            return d["MemTotal"], d.get("MemAvailable", d.get("MemFree", 0))
        if os.name == "nt":
            return _win_mem()
        pg = os.sysconf("SC_PAGE_SIZE"); return pg * os.sysconf("SC_PHYS_PAGES"), pg * os.sysconf("SC_AVPHYS_PAGES")
    except Exception:
        return 0, 0


def _cpu_sample():
    if os.path.exists("/proc/stat"):
        v = [int(x) for x in open("/proc/stat").readline().split()[1:]]
        return v[3] + (v[4] if len(v) > 4 else 0), sum(v[:8])
    if os.name == "nt":
        import ctypes
        i, k, u = (ctypes.c_ulonglong() for _ in range(3))
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u))
        return i.value, k.value + u.value
    return None


cpu_pct = 0
def cpu_loop():
    global cpu_pct
    last = None
    while True:
        try:
            if psutil:
                cpu_pct = int(psutil.cpu_percent())
            else:
                s = _cpu_sample()
                if s and last and s[1] > last[1]:
                    cpu_pct = int(100 * (1 - (s[0] - last[0]) / (s[1] - last[1])))
                last = s
        except Exception:
            pass
        time.sleep(2)


def uptime():
    try:
        if os.path.exists("/proc/uptime"):
            return float(open("/proc/uptime").read().split()[0])
        if os.name == "nt":
            import ctypes
            return ctypes.windll.kernel32.GetTickCount64() / 1000
    except Exception:
        pass
    return time.time() - START


def lan_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1)); ips.add(s.getsockname()[0]); s.close()
    except Exception:
        pass
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except Exception:
        pass
    return sorted(i for i in ips if not i.startswith("127."))


# ---------------- chat ----------------
history, streams, lock = [], set(), threading.Lock()


def broadcast(m):
    with lock:
        for q in list(streams):
            q.put(m)


# ---------------- HTTP ----------------
class Handler(BaseHTTPRequestHandler):
    server_version = "LanPC"

    def log_message(self, *a):
        pass

    def reply(self, code, data, ctype="application/json"):
        if not isinstance(data, (bytes, str)):
            data = json.dumps(data)
        b = data.encode() if isinstance(data, str) else data
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def body(self, limit=200_000_000):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("Too large")
        return self.rfile.read(n)

    def jbody(self):
        try:
            d = json.loads(self.body(100_000) or b"{}")
            return d if isinstance(d, dict) else {}
        except ValueError:
            return {}

    def handle_any(self):
        try:
            u = urlparse(self.path)
            if u.path.startswith("/api/"):
                self.api(u.path, parse_qs(u.query))
            else:
                self.static(u.path)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except FileNotFoundError:
            self.reply(404, "Not found")
        except (NotADirectoryError, IsADirectoryError):
            self.reply(400, "Bad path")
        except Exception as e:
            try:
                self.reply(500, str(e))
            except Exception:
                pass

    do_GET = do_PUT = do_POST = do_DELETE = handle_any

    def static(self, p):
        f = inside(PUB, "index.html" if p == "/" else p)
        if not f or not os.path.isfile(f):
            return self.reply(404, "Not found", "text/plain")
        self.send_file(f)

    def send_file(self, f, download=False):
        ctype = mimetypes.guess_type(f)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(os.path.getsize(f)))
        if download:
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % os.path.basename(f))
        self.end_headers()
        with open(f, "rb") as fh:
            shutil.copyfileobj(fh, self.wfile)

    def api(self, p, qs):
        m = self.command
        path = (qs.get("path") or [""])[0]
        tok = (qs.get("token") or [self.headers.get("x-token", "")])[0]
        cfg = load_cfg()

        # ---- public endpoints (setup + sign-in) ----
        if p == "/api/status":
            return self.reply(200, {"installed": bool(cfg), "theme": cfg["theme"] if cfg else "teal",
                                    "user": cfg["user"] if cfg else "", "authed": tok in tokens})
        if p == "/api/install" and m == "POST":
            d = self.jbody()
            user, pw = str(d.get("user", "")).strip()[:24], str(d.get("password", ""))
            theme = d.get("theme") if d.get("theme") in THEMES else "teal"
            if not user or len(pw) < 4:
                return self.reply(400, "Choose a user name and a password of at least 4 characters.")
            with cfg_lock:
                if load_cfg():
                    return self.reply(403, "LanPC is already installed.")
                salt, h = hash_pw(pw)
                save_cfg({"user": user, "salt": salt, "hash": h, "theme": theme, "installed": int(time.time())})
            os.makedirs(ROOT, exist_ok=True)
            return self.reply(200, {"token": new_token()})
        if p == "/api/login" and m == "POST":
            if not cfg:
                return self.reply(403, "LanPC is not installed yet.")
            if not check_pw(cfg, str(self.jbody().get("password", ""))):
                time.sleep(1)                      # slow down guessing
                return self.reply(403, "Wrong password.")
            return self.reply(200, {"token": new_token()})

        # ---- everything below needs a signed-in session ----
        if tok not in tokens:
            return self.reply(401, "Sign in required")

        if p == "/api/theme" and m == "POST":
            t = self.jbody().get("theme")
            if t not in THEMES:
                return self.reply(400, "Unknown theme")
            cfg["theme"] = t
            save_cfg(cfg)
            return self.reply(200, {"ok": True})

        if p == "/api/password" and m == "POST":
            d = self.jbody()
            if not check_pw(cfg, str(d.get("old", ""))):
                time.sleep(1)
                return self.reply(403, "Wrong password.")
            new = str(d.get("new", ""))
            if len(new) < 4:
                return self.reply(400, "Use at least 4 characters.")
            cfg["salt"], cfg["hash"] = hash_pw(new)
            save_cfg(cfg)
            tokens.clear()                         # sign every other device out
            return self.reply(200, {"token": new_token()})

        if p == "/api/wipe" and m == "POST":
            if not check_pw(cfg, str(self.jbody().get("password", ""))):
                time.sleep(1)
                return self.reply(403, "Wrong password.")
            wipe_everything()
            return self.reply(200, {"ok": True})

        if p == "/api/shutdown" and m == "POST":
            self.reply(200, {"ok": True})
            threading.Thread(target=lambda: (time.sleep(0.4), SRV.shutdown()), daemon=True).start()
            return

        if p == "/api/info":
            tot, free = mem()
            return self.reply(200, {"host": socket.gethostname(), "platform": f"{platform.system()} {platform.release()}",
                                    "uptime": uptime(), "cpu": cpu_pct, "cores": os.cpu_count() or 1, "memTotal": tot,
                                    "memFree": free, "ips": lan_ips(), "port": PORT, "online": len(streams)})

        if p == "/api/chat/stream":
            q = queue.Queue()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            with lock:
                backlog = list(history); streams.add(q)
            try:
                for msg in backlog:
                    self.wfile.write(f"data: {json.dumps(msg)}\n\n".encode())
                self.wfile.flush()
                while True:
                    try:
                        self.wfile.write(f"data: {json.dumps(q.get(timeout=15))}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                with lock:
                    streams.discard(q)
            return

        if p == "/api/chat" and m == "POST":
            d = self.jbody()
            msg = {"name": str(d.get("name") or "guest")[:24], "text": str(d.get("text") or "")[:1000], "t": int(time.time() * 1000)}
            if not msg["text"].strip():
                return self.reply(400, "Empty")
            with lock:
                history.append(msg); del history[:-100]
            broadcast(msg)
            return self.reply(200, {"ok": True})

        f = inside(ROOT, path)
        if not f:
            return self.reply(400, "Bad path")

        if p == "/api/files":
            items = []
            for name in os.listdir(f):
                s = os.stat(os.path.join(f, name))
                items.append({"name": name, "dir": os.path.isdir(os.path.join(f, name)), "size": s.st_size, "mtime": s.st_mtime * 1000})
            items.sort(key=lambda i: (not i["dir"], i["name"].lower()))
            return self.reply(200, items)

        if p == "/api/mkdir" and m == "POST":
            os.makedirs(f, exist_ok=True)
            return self.reply(200, {"ok": True})

        if p == "/api/file":
            if m == "GET":
                if not os.path.isfile(f):
                    return self.reply(404, "Not found")
                return self.send_file(f, download=bool(qs.get("dl")))
            if f == os.path.realpath(ROOT):
                return self.reply(400, "Bad path")
            if m == "PUT":
                os.makedirs(os.path.dirname(f), exist_ok=True)
                with open(f, "wb") as fh:
                    fh.write(self.body())
                return self.reply(200, {"ok": True})
            if m == "DELETE":
                shutil.rmtree(f) if os.path.isdir(f) else os.remove(f)
                return self.reply(200, {"ok": True})

        self.reply(404, "Unknown endpoint")


def main():
    global SRV
    threading.Thread(target=cpu_loop, daemon=True).start()
    SRV = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    SRV.daemon_threads = True
    print("\nLanPC is running.\n")
    print(f"  This machine:   http://localhost:{PORT}")
    for ip in lan_ips():
        print(f"  On your LAN:    http://{ip}:{PORT}")
    print("\n  " + ("Installed. Sign in with your account." if load_cfg() else "Not installed yet: open the address above to run first-time setup."))
    print(f"  Shared files:   {ROOT}\n")
    try:
        SRV.serve_forever()
    except KeyboardInterrupt:
        pass
    SRV.server_close()
    print("LanPC server stopped.")


if __name__ == "__main__":
    main()
