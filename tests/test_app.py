"""Integration tests for l4d2mgr_web against local MariaDB + fake RCON server."""
import os, re, socket, struct, subprocess, sys, threading
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web"))

os.environ.update({
    "L4D2MGR_DB_USER": "l4d2mgr_web", "L4D2MGR_DB_PASSWORD": "webpw",
    "L4D2MGR_SESSION_SECRET": "x" * 40, "L4D2MGR_SERVER_ID": "1",
})

RCON_LOG: list[str] = []

def _pkt(i, t, body=b""):
    p = struct.pack("<ii", i, t) + body + b"\x00\x00"
    return struct.pack("<i", len(p)) + p

def _rx(c, n):
    b = b""
    while len(b) < n:
        x = c.recv(n - len(b))
        if not x:
            raise EOFError
        b += x
    return b

def _handle(c):
    try:
        while True:
            size, = struct.unpack("<i", _rx(c, 4)); d = _rx(c, size)
            i, t = struct.unpack("<ii", d[:8]); body = d[8:-2].decode()
            if t == 3:
                c.sendall(_pkt(i, 0)); c.sendall(_pkt(i if body == "rconpass" else -1, 2))
            elif t == 2:
                RCON_LOG.append(body)
                out = "hostname: test <script>alert(1)</script>\nmap: c1m1_hotel" if body == "status" else f"ok:{body}"
                c.sendall(_pkt(i, 0, out.encode()))
            elif t == 0:
                c.sendall(_pkt(i, 0)); c.sendall(_pkt(i, 0, b"\x00\x01\x00\x00"))
    except (EOFError, OSError):
        pass
    finally:
        c.close()

def _serve():
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 27999)); s.listen()
    def loop():
        while True:
            c, _ = s.accept(); threading.Thread(target=_handle, args=(c,), daemon=True).start()
    threading.Thread(target=loop, daemon=True).start()

def sql(q):
    return subprocess.run(["mysql", "-N", "-e", q], capture_output=True, text=True, check=True).stdout.strip()

_serve()
from fastapi.testclient import TestClient
from l4d2mgr_web.app import app
from l4d2mgr_web import core

results = []
def check(name, cond, info=""):
    results.append((name, bool(cond), info))

def csrf_of(html):
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    return m.group(1) if m else None

def new_client():
    return TestClient(app, base_url="http://testserver", follow_redirects=False)

def login(c, user, pw="testpass"):
    tok = csrf_of(c.get("/login").text)
    return c.post("/login", data={"username": user, "password": pw, "csrf": tok})

# --- basic
c = new_client()
check("healthz", c.get("/healthz").text == "ok")
r = c.get("/login")
check("login page has csrf", csrf_of(r.text))
check("security headers", r.headers.get("x-frame-options") == "DENY" and "default-src 'self'" in r.headers.get("content-security-policy", ""))
check("index requires login", c.get("/").status_code == 303)

# --- login CSRF
r = new_client().post("/login", data={"username": "motoki2", "password": "testpass", "csrf": "bogus"})
check("login rejects bad csrf (403)", r.status_code == 403, r.status_code)

# --- auth matrix
for user, pw, expect in [("motoki2", "testpass", True), ("motoki2", "wrong", False), ("noperm", "testpass", False),
                         ("grpuser", "testpass", True), ("legacy", "x", False), ("CONSOLE", "", False), ("nouser", "testpass", False)]:
    core.limiter.reset("testclient")
    cc = new_client(); r = login(cc, user, pw)
    ok = r.headers.get("location") == "/"
    check(f"auth {user}/{'ok' if expect else 'ng'}", ok == expect, r.headers.get("location"))

# --- rate limit
core.limiter.reset("testclient")
cc = new_client()
for _ in range(5):
    login(cc, "motoki2", "wrong")
r = login(cc, "motoki2", "testpass")
check("rate limit blocks correct pw after 5 failures", r.headers.get("location") == "/login")
core.limiter.reset("testclient")

# --- dashboard
c = new_client(); login(c, "motoki2")
r = c.get("/")
check("dashboard 200", r.status_code == 200, r.status_code)
check("status via RCON shown", "map: c1m1_hotel" in r.text, r.text[:300] if r.status_code == 200 else "")
check("status XSS escaped", "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text)
check("rotation 14 rows", r.text.count("/toggle") == 14)
tok = csrf_of(r.text)

# --- CSRF on actions
r = c.post("/rotation/add", data={"map_name": "c5m1_waterfront", "csrf": "bad"})
check("action rejects bad csrf", r.status_code == 403)

# --- add / invalid
RCON_LOG.clear()
c.post("/rotation/add", data={"map_name": "c1m2_streets", "csrf": tok})
rows = sql("SELECT map FROM l4d2mgr.rotation WHERE server_id=1 ORDER BY position")
check("add appends", rows.splitlines()[-1] == "c1m2_streets")
check("add triggers sm_rotation_reload", "sm_rotation_reload" in RCON_LOG, RCON_LOG)
before = sql("SELECT COUNT(*) FROM l4d2mgr.rotation")
c.post("/rotation/add", data={"map_name": "c1m1_hotel;quit", "csrf": tok})
check("add rejects injection", sql("SELECT COUNT(*) FROM l4d2mgr.rotation") == before)

# --- move
first_id, second_id = sql("SELECT id FROM l4d2mgr.rotation WHERE server_id=1 ORDER BY position LIMIT 2").split()
c.post(f"/rotation/{second_id}/move", data={"direction": "up", "csrf": tok})
check("move up swaps", sql("SELECT id FROM l4d2mgr.rotation WHERE server_id=1 ORDER BY position LIMIT 1") == second_id)
r = c.post(f"/rotation/{second_id}/move", data={"direction": "up", "csrf": tok})
check("move up at top -> handled", r.status_code == 303)
c.post(f"/rotation/{second_id}/move", data={"direction": "down", "csrf": tok})
check("move down restores", sql("SELECT id FROM l4d2mgr.rotation WHERE server_id=1 ORDER BY position LIMIT 1") == first_id)
check("positions unique & no -1", sql("SELECT COUNT(*) FROM l4d2mgr.rotation WHERE position<0") == "0")

# --- toggle / delete
c.post(f"/rotation/{first_id}/toggle", data={"csrf": tok})
check("toggle disables", sql(f"SELECT enabled FROM l4d2mgr.rotation WHERE id={first_id}") == "0")
c.post(f"/rotation/{first_id}/toggle", data={"csrf": tok})
last_id = sql("SELECT id FROM l4d2mgr.rotation WHERE map='c1m2_streets'")
c.post(f"/rotation/{last_id}/delete", data={"csrf": tok})
check("delete removes", sql(f"SELECT COUNT(*) FROM l4d2mgr.rotation WHERE id={last_id}") == "0")

# --- server actions
RCON_LOG.clear()
c.post("/server/changelevel", data={"map_name": "c2m1_highway", "csrf": tok})
check("changelevel sent", "changelevel c2m1_highway" in RCON_LOG, RCON_LOG)
RCON_LOG.clear()
c.post("/server/changelevel", data={"map_name": "c2m1_highway; quit", "csrf": tok})
check("changelevel rejects injection", RCON_LOG == [], RCON_LOG)
c.post("/server/next", data={"csrf": tok})
check("next sends sm_rotation_next", "sm_rotation_next" in RCON_LOG, RCON_LOG)

# --- non-ASCII csrf must not 500
r = c.post("/server/next", data={"csrf": "トークン"})
check("non-ASCII csrf -> 403 not 500", r.status_code == 403, r.status_code)

# --- audit
acts = sql("SELECT GROUP_CONCAT(DISTINCT action) FROM l4d2mgr.audit_log")
check("audit recorded", all(a in acts for a in ["login", "login_failed", "rotation_add", "changelevel"]), acts)

# --- session revalidation
sql("UPDATE sourcebans.sb_admins SET extraflags=0 WHERE user='motoki2'")
check("revoked admin kicked out", c.get("/").status_code == 303)
sql("UPDATE sourcebans.sb_admins SET extraflags=16777216 WHERE user='motoki2'")

# --- logout
c2 = new_client(); login(c2, "motoki2"); t2 = csrf_of(c2.get("/").text)
c2.post("/logout", data={"csrf": t2})
check("logout", c2.get("/").status_code == 303)

# --- detections (AC)
sql("DELETE FROM l4d2mgr.detections")
sql("INSERT INTO l4d2mgr.detections (server_id, detector, severity, steamid, steamid64, name, map, detail) VALUES (1,'speedhack',3,'STEAM_1:0:123','76561197960265974','<script>x</script>','c2m1_highway','cmd/s=75.0 ratio=2.50'),(1,'speedhack',1,'STEAM_1:1:9','0','legit','c1m1_hotel','ratio=1.26'),(2,'speedhack',3,'STEAM_1:0:5','0','other','c1m1_hotel','other server')")
d1, d2, d3 = sql("SELECT id FROM l4d2mgr.detections ORDER BY id").split()
c = new_client(); login(c, "motoki2")
r = c.get("/detections")
check("detections page 200", r.status_code == 200, r.status_code)
check("detections XSS escaped", "<script>x</script>" not in r.text and "&lt;script&gt;" in r.text)
check("detections server filter", "other server" not in r.text)
check("steam profile link only when id64", r.text.count("steamcommunity.com/profiles/") == 1)
tok = csrf_of(r.text)
r = c.post(f"/detections/{d1}/submit", data={"csrf": "bad"})
check("detection submit rejects bad csrf", r.status_code == 403)
sql("DELETE FROM sourcebans.sb_submissions")
c.post(f"/detections/{d1}/submit", data={"csrf": tok})
check("submit -> status submitted", sql(f"SELECT status FROM l4d2mgr.detections WHERE id={d1}") == "submitted")
sub = sql("SELECT SteamId, ModID, server, subname, archiv, LEFT(reason,30) FROM sourcebans.sb_submissions")
check("submit -> sb_submissions row", sub.startswith("STEAM_1:0:123\t17\t1\tmotoki2\t0\t[l4d2mgr AC] speedhack sev3"), sub)
c.post(f"/detections/{d1}/submit", data={"csrf": tok})
check("double submit blocked", sql("SELECT COUNT(*) FROM sourcebans.sb_submissions") == "1")
c.post(f"/detections/{d2}/dismiss", data={"csrf": tok})
check("dismiss", sql(f"SELECT status, reviewed_by FROM l4d2mgr.detections WHERE id={d2}") == "dismissed\tmotoki2")
c.post(f"/detections/{d3}/dismiss", data={"csrf": tok})
check("cannot touch other server's detection", sql(f"SELECT status FROM l4d2mgr.detections WHERE id={d3}") == "new")
r = c.get("/detections?status=all")
check("status=all shows both", str(d1) in r.text and "legit" in r.text)
check("bad status param falls back", c.get("/detections?status=zzz").status_code == 200)

npass = sum(1 for _, ok, _ in results if ok)
for n, ok, info in results:
    print(("PASS " if ok else "FAIL ") + n + ("" if ok else f"   -> {info}"))
print(f"{npass}/{len(results)}")
