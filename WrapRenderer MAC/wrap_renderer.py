"""
Wrap Renderer — desktop host (Windows + macOS). Python stdlib only on Windows; PyObjC on macOS.

  * Serves renderer.html from a localhost-only server and opens it as a chromeless
    Edge/Chrome app window (Chromium, same engine as Infloww).
  * On-screen wrap guides (Infloww + PC + Mobile presets), tray / menu-bar item, global hotkeys —
    implemented per OS in overlay_win.py / overlay_mac.py behind the same interface.

Hotkeys (both OSes; Mac laptops add fn):
  Ctrl+Shift+F9 Infloww guides · F12 PC guides · F7 Mobile guides · F10/F11 nudge wrap line · F6 show window · F8 quit

Wiring map: ARCHITECTURE.md.
"""
import json
import os
import subprocess
import threading
import time

from wr_common import APP_NAME, IS_MAC, IS_WIN, data_dir, resource_path, settings_path  # noqa: F401

if IS_WIN:
    import overlay_win as backend
elif IS_MAC:
    import overlay_mac as backend
else:  # Linux / tests: no overlay, everything else works
    backend = None


class NullOverlay:
    """Stand-in backend with the same interface (used on Linux and in tests)."""
    def __init__(self, on_change=None, on_open=None, on_quit=None):
        self.on_open, self.on_quit = on_open, on_quit
        self.ready = threading.Event()
        self.show = {"infloww": False, "mobile": False, "pc": False}
        self.ratio, self.wrap_ref = 257.4 / 342, 957.0
        self.pc = (1061.0, 390.0)

    def start(self): self.ready.set()
    def state(self): return {**self.show, "wrapRef": self.wrap_ref, "leftRef": 615, "screen": [1920, 1080], "hotkeyErrors": [], "available": False}
    def toggle(self, name): self.show[name] = not self.show.get(name, False)
    def set_ratio(self, r): self.ratio = r
    def set_pc(self, left, width): self.pc = (left, width)
    def nudge(self, d): self.wrap_ref += d
    def reset_wrap(self): self.wrap_ref = 957.0
    def balloon(self, title, text): pass
    def stop(self): pass
    def run_main_loop(self, done): done.wait()
    def focus_window(self, proc): return False
    def close_window(self, proc): pass


# ----------------------------------------------------------------------------
# JS bridge: a tiny localhost HTTP server (stdlib only, nothing to pip install).
# renderer.html calls /api/* with the X-Token header (see makeHttpHost() in the page).
# ----------------------------------------------------------------------------
STATIC = {"/": ("renderer.html", "text/html; charset=utf-8"),
          "/renderer.html": ("renderer.html", "text/html; charset=utf-8"),
          "/roboto.css": ("roboto.css", "text/css; charset=utf-8")}
PREFERRED_PORT = 47811


def load_settings_text():
    try:
        with open(settings_path(), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def save_settings_text(text):
    tmp = settings_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, settings_path())


def make_handler(app):
    from http.server import BaseHTTPRequestHandler

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # pythonw has no stderr; default logging would crash
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authed(self):
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            return self.headers.get("X-Token") == app.token or f"t={app.token}" in q.split("&")

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in STATIC:
                name, ctype = STATIC[path]
                with open(resource_path(name), "rb") as f:
                    return self._send(200, f.read(), ctype)
            if not path.startswith("/api/") or not self._authed():
                return self._send(404, {"error": "not found"})
            if path == "/api/state":
                app.last_poll = time.time()
                return self._send(200, app.overlay.state())
            if path == "/api/settings":
                return self._send(200, {"text": load_settings_text()})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if not path.startswith("/api/") or not self._authed():
                return self._send(404, {"error": "not found"})
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                body = {}
            ov = app.overlay
            if path == "/api/toggle":
                ov.toggle(body.get("name"))
                return self._send(200, ov.state())
            if path == "/api/ratio":
                ov.set_ratio(float(body.get("ratio") or 0))
                return self._send(200, {"ok": True})
            if path == "/api/pc":
                ov.set_pc(float(body.get("left") or 0), float(body.get("width") or 0))
                return self._send(200, {"ok": True})
            if path == "/api/nudge":
                ov.nudge(int(body.get("d") or 0))
                return self._send(200, ov.state())
            if path == "/api/reset":
                ov.reset_wrap()
                return self._send(200, ov.state())
            if path == "/api/settings":
                save_settings_text(body.get("text") or "{}")
                return self._send(200, {"ok": True})
            if path == "/api/closed":  # beacon from the page as its window closes
                app.last_poll = 0.0
                return self._send(200, {"ok": True})
            if path == "/api/open":  # sent by a second launch
                threading.Thread(target=app.open_window, daemon=True).start()
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})

    return Handler


def find_browser():
    """Edge/Chrome-family browser for the app window. Returns exe path or None (then: default browser)."""
    if IS_MAC:
        cands = [os.path.join(root, app) for root in ("/Applications", os.path.expanduser("~/Applications"))
                 for app in ("Google Chrome.app/Contents/MacOS/Google Chrome",
                             "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                             "Brave Browser.app/Contents/MacOS/Brave Browser",
                             "Chromium.app/Contents/MacOS/Chromium")]
    else:
        cands = []
        for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            root = os.environ.get(env)
            if root:
                cands += [os.path.join(root, r"Microsoft\Edge\Application\msedge.exe"),
                          os.path.join(root, r"Google\Chrome\Application\chrome.exe")]
    return next((c for c in cands if os.path.isfile(c)), None)


def port_file():
    return os.path.join(data_dir(), "running.json")


# ----------------------------------------------------------------------------
# App wiring
# ----------------------------------------------------------------------------
class App:
    def __init__(self):
        import secrets
        self.token = secrets.token_urlsafe(18)
        self.port = None
        self.httpd = None
        self.browser = None      # browser process that owns the renderer window
        self.last_poll = 0.0     # last /api/state hit = a renderer window is open
        self.quitting = False
        self.hide_note_shown = False
        self.done = threading.Event()
        Overlay = backend.Overlay if backend else NullOverlay
        self.overlay = Overlay(on_open=self.open_window, on_quit=self.quit)

    def url(self):
        return f"http://127.0.0.1:{self.port}/?t={self.token}"

    def serve(self):
        from http.server import ThreadingHTTPServer
        for port in (PREFERRED_PORT, 0):
            try:
                self.httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(self))
                break
            except OSError:
                continue
        self.port = self.httpd.server_address[1]
        with open(port_file(), "w", encoding="utf-8") as f:
            json.dump({"port": self.port, "token": self.token}, f)
        threading.Thread(target=self.httpd.serve_forever, daemon=True, name="http").start()

    def window_open(self):
        # Minimised windows get their timers throttled (down to ~1/min), so allow a long gap;
        # the page's "closed" beacon resets last_poll immediately when the window really closes.
        return time.time() - self.last_poll < 90.0

    def open_window(self):
        """Focus the renderer window if it's open, otherwise open one.
        Callers: main(), tray/menu-bar Open, Ctrl+Shift+F6, /api/open (second launch)."""
        if (IS_WIN or self.window_open()) and self.overlay.focus_window(self.browser):
            return
        exe = find_browser()
        if not exe:
            import webbrowser
            webbrowser.open(self.url())
            return
        profile = os.path.join(data_dir(), "window-profile")
        args = [exe, f"--app={self.url()}", f"--user-data-dir={profile}", "--window-size=1500,940",
                "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"]
        proc = subprocess.Popen(args, close_fds=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if self.browser is None or self.browser.poll() is not None:
            self.browser = proc
            threading.Thread(target=self._watch, args=(proc,), daemon=True).start()

    def _watch(self, proc):
        proc.wait()  # Windows: exits when the last renderer window closes
        if not self.quitting and not self.hide_note_shown and IS_WIN:
            self.hide_note_shown = True
            self.overlay.balloon(APP_NAME, "Still running in the tray. Double-click the icon to reopen, right-click to quit.")

    def quit(self):
        """Callers: tray/menu-bar Quit, Ctrl+Shift+F8."""
        self.quitting = True
        self.overlay.close_window(self.browser)
        try:
            os.remove(port_file())
        except OSError:
            pass
        self.done.set()
        self.overlay.stop()


def signal_running_instance():
    """Second launch: ask the running copy to show its window."""
    try:
        import urllib.request
        with open(port_file(), encoding="utf-8") as f:
            info = json.load(f)
        req = urllib.request.Request(f"http://127.0.0.1:{info['port']}/api/open", data=b"{}", method="POST",
                                     headers={"X-Token": info["token"], "Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).read()
        return True
    except Exception:
        return False


def main():
    if backend:
        backend.set_dpi_aware()
        if not backend.acquire_single_instance():  # already running -> just show its window
            if not signal_running_instance():
                backend.notify("Wrap Renderer is already running — look for it in the tray / menu bar.")
            return
    app = App()
    app.overlay.start()          # Windows: starts its own thread. macOS: sets up Cocoa on this (main) thread.
    app.overlay.ready.wait(3)
    app.serve()
    app.open_window()
    app.overlay.run_main_loop(app.done)  # returns on quit
    if app.httpd:
        app.httpd.shutdown()


if __name__ == "__main__":
    main()
