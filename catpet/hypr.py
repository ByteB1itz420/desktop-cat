"""Tiny Hyprland IPC client (no subprocess spawning, so polling is cheap)."""
import json
import os
import socket


class Hypr:
    def __init__(self):
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        rt = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        self.path = None
        for p in (f"{rt}/hypr/{sig}/.socket.sock", f"/tmp/hypr/{sig}/.socket.sock"):
            if sig and os.path.exists(p):
                self.path = p
                break

    @property
    def ok(self):
        return self.path is not None

    def req(self, cmd):
        if not self.path:
            return None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.25)
                s.connect(self.path)
                s.sendall(("j/" + cmd).encode())
                chunks = []
                while True:
                    d = s.recv(65536)
                    if not d:
                        break
                    chunks.append(d)
            return json.loads(b"".join(chunks) or b"null")
        except (OSError, ValueError):
            return None

    def monitors(self):
        return self.req("monitors") or []

    def clients(self):
        return self.req("clients") or []

    def cursor(self):
        c = self.req("cursorpos")
        if isinstance(c, dict) and "x" in c:
            return c["x"], c["y"]
        return None

    def active_window(self):
        w = self.req("activewindow")
        return w if isinstance(w, dict) else None
