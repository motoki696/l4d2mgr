"""Fake Source RCON server + tests for a candidate rcon.py (import path via argv[1])."""
import importlib.util, socket, struct, sys, threading

PW = "secret"

def pkt(i, t, body=b""):
    p = struct.pack("<ii", i, t) + body + b"\x00\x00"
    return struct.pack("<i", len(p)) + p

def recv_exact(c, n):
    b = b""
    while len(b) < n:
        x = c.recv(n - len(b))
        if not x:
            raise EOFError
        b += x
    return b

def handle(c):
    try:
        while True:
            size, = struct.unpack("<i", recv_exact(c, 4))
            data = recv_exact(c, size)
            i, t = struct.unpack("<ii", data[:8])
            body = data[8:-2].decode()
            if t == 3:
                c.sendall(pkt(i, 0))
                c.sendall(pkt(i if body == PW else -1, 2))
            elif t == 2:
                if body == "big":
                    out = ("x" * 4000 + "\n") * 3  # split into several packets
                    for k in range(0, len(out), 4096):
                        c.sendall(pkt(i, 0, out[k:k + 4096].encode()))
                else:
                    c.sendall(pkt(i, 0, f"echo:{body}".encode()))
            elif t == 0:
                c.sendall(pkt(i, 0))
                c.sendall(pkt(i, 0, b"\x00\x01\x00\x00"))
    except (EOFError, OSError):
        pass
    finally:
        c.close()

def serve():
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0)); s.listen()
    def loop():
        while True:
            c, _ = s.accept()
            threading.Thread(target=handle, args=(c,), daemon=True).start()
    threading.Thread(target=loop, daemon=True).start()
    return s.getsockname()[1]

def main():
    spec = importlib.util.spec_from_file_location("rcon", sys.argv[1])
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    port = serve()
    results = []
    def check(name, fn):
        try:
            fn(); results.append((name, "PASS"))
        except Exception as e:
            results.append((name, f"FAIL {type(e).__name__}: {e}"))
    def t_basic():
        with m.RconClient("127.0.0.1", port, PW) as r:
            assert r.command("status") == "echo:status", r.command("status")
            assert r.command("sm_rotation") == "echo:sm_rotation"  # stray 0x00010000 packet ignored
    def t_big():
        with m.RconClient("127.0.0.1", port, PW) as r:
            out = r.command("big")
            assert out == ("x" * 4000 + "\n") * 3, len(out)
    def t_badauth():
        try:
            with m.RconClient("127.0.0.1", port, "wrong"):
                pass
        except m.RconAuthError:
            return
        raise AssertionError("no RconAuthError")
    def t_inject():
        with m.RconClient("127.0.0.1", port, PW) as r:
            for bad in ("a\nb", "a\x00", "x" * 1001):
                try:
                    r.command(bad)
                except m.RconError:
                    continue
                raise AssertionError(f"accepted {bad[:10]!r}")
    def t_notconn():
        r = m.RconClient("127.0.0.1", port, PW)
        try:
            r.command("status")
        except m.RconError:
            r.close(); r.close(); return
        raise AssertionError("no RconError")
    def t_refused():
        try:
            m.RconClient("127.0.0.1", 1, PW, timeout=1).connect()
        except m.RconError:
            return
        raise AssertionError("no RconError on refused")
    for n, f in [("basic+stray", t_basic), ("multi-packet", t_big), ("bad auth", t_badauth),
                 ("input validation", t_inject), ("not connected/close twice", t_notconn),
                 ("conn refused->RconError", t_refused)]:
        check(n, f)
    for n, r in results:
        print(f"{r[:4]}  {n}  {r[5:]}")

main()
