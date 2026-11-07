"""
Wrap Renderer — desktop host.

  * Serves renderer.html from a localhost-only server and opens it as a chromeless
    Microsoft Edge app window (Chromium, same engine as Infloww). Python stdlib only.
  * Runs an on-screen guide overlay: a Python/ctypes port of wrap_overlay.exe, plus a
    "Mobile" preset (where an iPhone would wrap) and a "PC" preset (OnlyFans web chat bubble).
  * Tray icon (left-click toggles Infloww guides, double-click opens the renderer,
    right-click menu) and global hotkeys.

Hotkeys (same as wrap_overlay.exe, plus F7/F6/F12):
  Ctrl+Shift+F9   toggle Infloww guides            (id 1)
  Ctrl+Shift+F10  wrap line 1px left  (saved)      (id 2)
  Ctrl+Shift+F11  wrap line 1px right (saved)      (id 3)
  Ctrl+Shift+F8   quit everything                  (id 4)
  Ctrl+Shift+F7   toggle Mobile guides             (id 5)
  Ctrl+Shift+F6   show the renderer window         (id 6)
  Ctrl+Shift+F12  toggle PC guides                 (id 7)

The wrap position is shared with wrap_overlay.exe through
HKCU\\Software\\wrapoverlay\\wrap (1920-wide reference px). Don't run both at once:
they use the same hotkeys.

Where everything is used / what points to it: see ARCHITECTURE.md.
"""
import json
import os
import sys
import threading

# ----------------------------------------------------------------------------
# Geometry decoded from wrap_overlay.exe (1920x1080 reference coordinates)
# ----------------------------------------------------------------------------
REF_W, REF_H = 1920, 1080
GUIDE_LEFT_REF = 615          # left text edge
GUIDE_WRAP_DEFAULT_REF = 957  # default wrap line  -> 342 px column
GUIDE_TOP_REF = 720
GUIDE_BOTTOM_REF = 950
DASH_STEP, DASH_LEN = 7, 2    # centre line: 2px dash every 7px
OVERLAY_ALPHA = 140           # 0x8C, same as the original
COLOR_KEY = 0x010101          # transparent colour key (COLORREF)
RED = 0x3B3BFF                # COLORREF (0x00BBGGRR) for #FF3B3B  — Infloww preset
CYAN = 0xFFD13B               # COLORREF for #3BD1FF               — Mobile preset
GREEN_RGB = (0x4C, 0xE0, 0x7A)  # PC preset
GREEN = GREEN_RGB[0] | (GREEN_RGB[1] << 8) | (GREEN_RGB[2] << 16)  # COLORREF (0x00BBGGRR)
# PC preset (OnlyFans web chat bubble, measured from a 1920-wide screenshot). Independent of the Infloww
# wrap line: its own left edge + absolute width (both editable on the page, pushed via /api/pc).
GUIDE_PC_LEFT_REF = 1061      # left text edge of a received bubble
GUIDE_PC_WIDTH_DEFAULT = 390  # text width -> wrap at 1451
GUIDE_PC_TOP_REF = 150
GUIDE_PC_BOTTOM_REF = 920

REG_KEY = r"Software\wrapoverlay"
REG_VALUE = "wrap"

APP_NAME = "Wrap Renderer"
MUTEX_NAME = "wrap_renderer_singleton"
DEFAULT_MOBILE_RATIO = 257.4 / 342  # iPhone 16 Pro text width / Infloww width (updated by the UI)

HOTKEYS = {  # id: (vk, label, repeat)
    1: (0x78, "Ctrl+Shift+F9", False),
    2: (0x79, "Ctrl+Shift+F10", True),
    3: (0x7A, "Ctrl+Shift+F11", True),
    4: (0x77, "Ctrl+Shift+F8", False),
    5: (0x76, "Ctrl+Shift+F7", False),
    6: (0x75, "Ctrl+Shift+F6", False),
    7: (0x7B, "Ctrl+Shift+F12", False),  # toggle PC guides
}

IS_WIN = sys.platform == "win32"


def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def settings_path():
    root = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(root, "WrapRenderer")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "settings.json")


# ----------------------------------------------------------------------------
# Registry (shared with wrap_overlay.exe)
# ----------------------------------------------------------------------------
def reg_load_wrap_ref():
    if not IS_WIN:
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
            v, _ = winreg.QueryValueEx(k, REG_VALUE)
            return int(v)
    except OSError:
        return None


def reg_save_wrap_ref(ref):
    if not IS_WIN:
        return
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
        winreg.SetValueEx(k, REG_VALUE, 0, winreg.REG_DWORD, int(ref))


def reg_clear_wrap():
    if not IS_WIN:
        return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, REG_VALUE)
    except OSError:
        pass


# ----------------------------------------------------------------------------
# Win32 bindings
# ----------------------------------------------------------------------------
if IS_WIN:
    import ctypes
    from ctypes import wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32")
    shell32 = ctypes.WinDLL("shell32")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                    ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                    ("lpszClassName", wt.LPCWSTR)]

    class PAINTSTRUCT(ctypes.Structure):
        _fields_ = [("hdc", wt.HDC), ("fErase", wt.BOOL), ("rcPaint", wt.RECT), ("fRestore", wt.BOOL),
                    ("fIncUpdate", wt.BOOL), ("rgbReserved", ctypes.c_byte * 32)]

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("uFlags", wt.UINT),
                    ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON), ("szTip", wt.WCHAR * 128),
                    ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD), ("szInfo", wt.WCHAR * 256),
                    ("uVersion", wt.UINT), ("szInfoTitle", wt.WCHAR * 64), ("dwInfoFlags", wt.DWORD),
                    ("guidItem", GUID), ("hBalloonIcon", wt.HICON)]

    def _sig(fn, args, res=wt.BOOL):
        fn.argtypes, fn.restype = args, res
        return fn

    _sig(user32.DefWindowProcW, [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM], LRESULT)
    _sig(user32.RegisterClassW, [ctypes.POINTER(WNDCLASSW)], wt.ATOM)
    _sig(user32.CreateWindowExW, [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID], wt.HWND)
    _sig(user32.SetLayeredWindowAttributes, [wt.HWND, wt.DWORD, wt.BYTE, wt.DWORD])
    _sig(user32.ShowWindow, [wt.HWND, ctypes.c_int])
    _sig(user32.RegisterHotKey, [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT])
    _sig(user32.UnregisterHotKey, [wt.HWND, ctypes.c_int])
    _sig(user32.GetMessageW, [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT])
    _sig(user32.TranslateMessage, [ctypes.POINTER(wt.MSG)])
    _sig(user32.DispatchMessageW, [ctypes.POINTER(wt.MSG)], LRESULT)
    _sig(user32.PostMessageW, [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM])
    _sig(user32.BeginPaint, [wt.HWND, ctypes.POINTER(PAINTSTRUCT)], wt.HDC)
    _sig(user32.EndPaint, [wt.HWND, ctypes.POINTER(PAINTSTRUCT)])
    _sig(user32.FillRect, [wt.HDC, ctypes.POINTER(wt.RECT), wt.HBRUSH], ctypes.c_int)
    _sig(user32.GetClientRect, [wt.HWND, ctypes.POINTER(wt.RECT)])
    _sig(user32.InvalidateRect, [wt.HWND, ctypes.c_void_p, wt.BOOL])
    _sig(user32.CreatePopupMenu, [], wt.HMENU)
    _sig(user32.AppendMenuW, [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR])
    _sig(user32.TrackPopupMenu, [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, ctypes.c_void_p], ctypes.c_int)
    _sig(user32.DestroyMenu, [wt.HMENU])
    _sig(user32.GetCursorPos, [ctypes.POINTER(wt.POINT)])
    _sig(user32.SetForegroundWindow, [wt.HWND])
    _sig(user32.LoadIconW, [wt.HINSTANCE, ctypes.c_void_p], wt.HICON)
    _sig(user32.DestroyWindow, [wt.HWND])
    _sig(user32.PostQuitMessage, [ctypes.c_int], None)
    _sig(user32.GetSystemMetrics, [ctypes.c_int], ctypes.c_int)
    _sig(user32.RegisterWindowMessageW, [wt.LPCWSTR], wt.UINT)
    _sig(user32.MessageBoxW, [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT], ctypes.c_int)
    _sig(user32.FindWindowW, [wt.LPCWSTR, wt.LPCWSTR], wt.HWND)
    _sig(gdi32.CreateSolidBrush, [wt.DWORD], wt.HBRUSH)
    _sig(gdi32.DeleteObject, [wt.HANDLE])
    _sig(shell32.Shell_NotifyIconW, [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)])
    _sig(kernel32.GetModuleHandleW, [wt.LPCWSTR], wt.HMODULE)
    _sig(kernel32.CreateMutexW, [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR], wt.HANDLE)

    WM_DESTROY, WM_CLOSE, WM_PAINT, WM_HOTKEY = 0x0002, 0x0010, 0x000F, 0x0312
    WM_APP_TRAY, WM_APP_REFRESH, WM_APP_BALLOON = 0x8001, 0x8002, 0x8003
    WM_LBUTTONUP, WM_LBUTTONDBLCLK, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0203, 0x0205, 0x007B
    WS_POPUP = 0x80000000
    WS_EX = 0x08000000 | 0x00080000 | 0x80 | 0x20 | 0x08  # NOACTIVATE|LAYERED|TOOLWINDOW|TRANSPARENT|TOPMOST
    LWA_COLORKEY, LWA_ALPHA = 0x1, 0x2
    MOD_SHIFT, MOD_CONTROL, MOD_NOREPEAT = 0x4, 0x2, 0x4000
    NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
    NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
    MF_STRING, MF_CHECKED, MF_SEPARATOR = 0x0, 0x8, 0x800
    TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x2, 0x100
    SW_HIDE, SW_SHOWNOACTIVATE = 0, 4


def set_dpi_aware():
    """Physical-pixel coordinates, same as the original's SetProcessDPIAware. Must run before any window."""
    if not IS_WIN:
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# ----------------------------------------------------------------------------
# Overlay + tray + hotkeys (own thread, own message loop)
# ----------------------------------------------------------------------------
MENU_OPEN, MENU_INF, MENU_MOB, MENU_RESET, MENU_QUIT, MENU_PC = 1, 2, 3, 4, 5, 6


class Overlay(threading.Thread):
    """Click-through topmost guide window. Callers: App (wrap_renderer.py), Api methods.
    Callbacks: on_change(state_dict), on_open(), on_quit()."""

    def __init__(self, on_change=None, on_open=None, on_quit=None):
        super().__init__(daemon=True, name="overlay")
        self.on_change = on_change or (lambda st: None)
        self.on_open = on_open or (lambda: None)
        self.on_quit = on_quit or (lambda: None)
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.hwnd = None
        self.show_infloww = False
        self.show_mobile = False
        self.show_pc = False
        self.mobile_ratio = DEFAULT_MOBILE_RATIO
        self.pc_left_ref = GUIDE_PC_LEFT_REF       # 1920-ref px, set by the page via set_pc()
        self.pc_width_ref = GUIDE_PC_WIDTH_DEFAULT
        self.hotkey_errors = []
        self.sw, self.sh = REF_W, REF_H
        self.wrap_px = GUIDE_WRAP_DEFAULT_REF
        self._balloon = None
        self._wndproc = None  # keep the ctypes callback alive
        self.taskbar_created = None  # set in run(); _proc can fire before that

    # ---- geometry -----------------------------------------------------------
    def _x(self, ref):
        return int(ref * self.sw // REF_W)  # int: set_pc() stores floats and wt.RECT rejects them

    def _y(self, ref):
        return int(ref * self.sh // REF_H)

    def wrap_ref(self):
        return round(self.wrap_px * REF_W / self.sw, 2)

    def state(self):
        with self.lock:
            return {"infloww": self.show_infloww, "mobile": self.show_mobile, "pc": self.show_pc,
                    "wrapRef": self.wrap_ref(), "leftRef": GUIDE_LEFT_REF,
                    "screen": [self.sw, self.sh], "hotkeyErrors": list(self.hotkey_errors),
                    "available": IS_WIN}

    # ---- thread-safe API (called from the webview thread) -------------------
    def toggle(self, name):
        with self.lock:
            if name == "infloww":
                self.show_infloww = not self.show_infloww
            elif name == "mobile":
                self.show_mobile = not self.show_mobile
            elif name == "pc":
                self.show_pc = not self.show_pc
        self._post(WM_APP_REFRESH if IS_WIN else 0)

    def set_ratio(self, r):
        if r and 0.2 < r < 3:
            with self.lock:
                self.mobile_ratio = r
            self._post(WM_APP_REFRESH if IS_WIN else 0, notify=False)

    def set_pc(self, left, width):
        """PC guide: left text edge + text width, both 1920-ref px."""
        if left and width and 0 < left < REF_W and 50 < width < REF_W:
            with self.lock:
                self.pc_left_ref, self.pc_width_ref = float(left), float(width)
            self._post(WM_APP_REFRESH if IS_WIN else 0, notify=False)

    def nudge(self, d):
        with self.lock:
            self.wrap_px += int(d)
            reg_save_wrap_ref(self.wrap_px * REF_W // self.sw)
        self._post(WM_APP_REFRESH if IS_WIN else 0)

    def reset_wrap(self):
        reg_clear_wrap()
        with self.lock:
            self.wrap_px = self._x(GUIDE_WRAP_DEFAULT_REF)
        self._post(WM_APP_REFRESH if IS_WIN else 0)

    def balloon(self, title, text):
        self._balloon = (title, text)
        self._post(WM_APP_BALLOON if IS_WIN else 0, notify=False)

    def stop(self):
        if IS_WIN and self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def _post(self, msg, notify=True):
        if IS_WIN and self.hwnd and msg:
            user32.PostMessageW(self.hwnd, msg, 1 if notify else 0, 0)
        elif not IS_WIN and notify:
            self.on_change(self.state())

    # ---- thread body ----------------------------------------------------------
    def run(self):
        if not IS_WIN:
            self.ready.set()
            return
        hinst = kernel32.GetModuleHandleW(None)
        self.sw, self.sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        ref = reg_load_wrap_ref()
        self.wrap_px = self._x(ref if ref is not None else GUIDE_WRAP_DEFAULT_REF)

        self.key_brush = gdi32.CreateSolidBrush(COLOR_KEY)
        self.red_brush = gdi32.CreateSolidBrush(RED)
        self.cyan_brush = gdi32.CreateSolidBrush(CYAN)
        self.green_brush = gdi32.CreateSolidBrush(GREEN)
        self._wndproc = WNDPROC(self._proc)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.hbrBackground = self.key_brush
        wc.lpszClassName = "wraprenderer_overlay"
        user32.RegisterClassW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(WS_EX, wc.lpszClassName, "wrap renderer overlay", WS_POPUP,
                                           0, 0, self.sw, self.sh, None, None, hinst, None)
        user32.SetLayeredWindowAttributes(self.hwnd, COLOR_KEY, OVERLAY_ALPHA, LWA_COLORKEY | LWA_ALPHA)
        user32.ShowWindow(self.hwnd, SW_HIDE)

        for hid, (vk, label, repeat) in HOTKEYS.items():
            mods = MOD_CONTROL | MOD_SHIFT | (0 if repeat else MOD_NOREPEAT)
            if not user32.RegisterHotKey(self.hwnd, hid, mods, vk):
                self.hotkey_errors.append(label)

        self.taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        self.hicon = user32.LoadIconW(None, ctypes.c_void_p(32512))  # IDI_APPLICATION
        self._tray(NIM_ADD)
        self.ready.set()

        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        for b in (self.key_brush, self.red_brush, self.cyan_brush, self.green_brush):
            gdi32.DeleteObject(b)

    # ---- tray -----------------------------------------------------------------
    def _nid(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        return nid

    def _tray(self, op):
        nid = self._nid()
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_APP_TRAY
        nid.hIcon = self.hicon
        nid.szTip = f"{APP_NAME} (Ctrl+Shift+F9 Infloww, F12 PC, F7 Mobile, F8 quit)"[:127]
        shell32.Shell_NotifyIconW(op, ctypes.byref(nid))

    def _show_balloon(self):
        if not self._balloon:
            return
        title, text = self._balloon
        self._balloon = None
        nid = self._nid()
        nid.uFlags = NIF_INFO
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        nid.dwInfoFlags = 0x1  # NIIF_INFO
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def _menu(self):
        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        m = user32.CreatePopupMenu()
        with self.lock:
            inf, mob, pc = self.show_infloww, self.show_mobile, self.show_pc
        user32.AppendMenuW(m, MF_STRING, MENU_OPEN, "Open renderer\tCtrl+Shift+F6")
        user32.AppendMenuW(m, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(m, MF_STRING | (MF_CHECKED if inf else 0), MENU_INF, "Infloww guides\tCtrl+Shift+F9")
        user32.AppendMenuW(m, MF_STRING | (MF_CHECKED if pc else 0), MENU_PC, "PC guides\tCtrl+Shift+F12")
        user32.AppendMenuW(m, MF_STRING | (MF_CHECKED if mob else 0), MENU_MOB, "Mobile guides\tCtrl+Shift+F7")
        user32.AppendMenuW(m, MF_STRING, MENU_RESET, "Reset wrap line to default")
        user32.AppendMenuW(m, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(m, MF_STRING, MENU_QUIT, "Quit\tCtrl+Shift+F8")
        user32.SetForegroundWindow(self.hwnd)
        cmd = user32.TrackPopupMenu(m, TPM_RIGHTBUTTON | TPM_RETURNCMD, pt.x, pt.y, 0, self.hwnd, None)
        user32.DestroyMenu(m)
        user32.PostMessageW(self.hwnd, 0, 0, 0)  # WM_NULL: lets the menu close cleanly
        if cmd == MENU_OPEN:
            self._async(self.on_open)
        elif cmd == MENU_INF:
            self.show_infloww = not self.show_infloww
            self._refresh(True)
        elif cmd == MENU_MOB:
            self.show_mobile = not self.show_mobile
            self._refresh(True)
        elif cmd == MENU_PC:
            self.show_pc = not self.show_pc
            self._refresh(True)
        elif cmd == MENU_RESET:
            reg_clear_wrap()
            self.wrap_px = self._x(GUIDE_WRAP_DEFAULT_REF)
            self._refresh(True)
        elif cmd == MENU_QUIT:
            self._quit()

    # ---- painting / state ------------------------------------------------------
    def _refresh(self, notify):
        visible = self.show_infloww or self.show_mobile or self.show_pc
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE if visible else SW_HIDE)
        user32.InvalidateRect(self.hwnd, None, True)
        if notify:
            st = self.state()
            self._async(lambda: self.on_change(st))

    def _paint(self, hwnd):
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        rc = wt.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rc))
        user32.FillRect(hdc, ctypes.byref(rc), self.key_brush)
        with self.lock:
            inf, mob, wrap, ratio = self.show_infloww, self.show_mobile, self.wrap_px, self.mobile_ratio
            pc, pcl, pcw = self.show_pc, self.pc_left_ref, self.pc_width_ref
        left, top, bottom = self._x(GUIDE_LEFT_REF), self._y(GUIDE_TOP_REF), self._y(GUIDE_BOTTOM_REF)

        def bar(x, y0, y1, brush):
            r = wt.RECT(x, y0, x + 1, y1)
            user32.FillRect(hdc, ctypes.byref(r), brush)

        def dashed(x, brush):
            y = top
            while y < bottom:
                bar(x, y, y + DASH_LEN, brush)
                y += DASH_STEP

        if inf:
            bar(left, top, bottom, self.red_brush)
            bar(wrap, top, bottom, self.red_brush)
            dashed((left + wrap) // 2, self.red_brush)
        if mob:
            mwrap = left + round((wrap - left) * ratio)
            if not inf:
                bar(left, top, bottom, self.cyan_brush)
            bar(mwrap, top, bottom, self.cyan_brush)
            dashed((left + mwrap) // 2, self.cyan_brush)
        if pc:  # own left edge + absolute width, own vertical span (chat pane, not the composer)
            pl, pr = self._x(pcl), self._x(pcl + pcw)
            pt, pb = self._y(GUIDE_PC_TOP_REF), self._y(GUIDE_PC_BOTTOM_REF)
            bar(pl, pt, pb, self.green_brush)
            bar(pr, pt, pb, self.green_brush)
            y = pt
            while y < pb:
                bar((pl + pr) // 2, y, y + DASH_LEN, self.green_brush)
                y += DASH_STEP
        user32.EndPaint(hwnd, ctypes.byref(ps))

    def _quit(self):
        user32.DestroyWindow(self.hwnd)
        self._async(self.on_quit)

    @staticmethod
    def _async(fn):
        threading.Thread(target=fn, daemon=True).start()

    def _proc(self, hwnd, msg, wp, lp):
        try:
            if msg == WM_PAINT:
                self._paint(hwnd)
                return 0
            if msg == WM_HOTKEY:
                if wp == 1:
                    self.show_infloww = not self.show_infloww
                elif wp == 5:
                    self.show_mobile = not self.show_mobile
                elif wp == 7:
                    self.show_pc = not self.show_pc
                elif wp in (2, 3):
                    with self.lock:
                        self.wrap_px += -1 if wp == 2 else 1
                        reg_save_wrap_ref(self.wrap_px * REF_W // self.sw)
                elif wp == 4:
                    self._quit()
                    return 0
                elif wp == 6:
                    self._async(self.on_open)
                    return 0
                self._refresh(True)
                return 0
            if msg == WM_APP_TRAY:
                ev = lp & 0xFFFF
                if ev == WM_LBUTTONUP:
                    self.show_infloww = not self.show_infloww
                    self._refresh(True)
                elif ev == WM_LBUTTONDBLCLK:
                    self._async(self.on_open)
                elif ev in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._menu()
                return 0
            if msg == WM_APP_REFRESH:
                self._refresh(bool(wp))
                return 0
            if msg == WM_APP_BALLOON:
                self._show_balloon()
                return 0
            if msg == self.taskbar_created:
                self._tray(NIM_ADD)
                return 0
            if msg == WM_DESTROY:
                self._tray(NIM_DELETE)
                user32.PostQuitMessage(0)
                return 0
        except Exception as e:  # never let an exception escape a WNDPROC
            print("overlay error:", e, file=sys.stderr)
        return user32.DefWindowProcW(hwnd, msg, wp, lp)


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
            return self.headers.get("X-Token") == app.token

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in STATIC:
                name, ctype = STATIC[path]
                with open(resource_path(name), "rb") as f:
                    return self._send(200, f.read(), ctype)
            if not path.startswith("/api/") or not self._authed():
                return self._send(404, {"error": "not found"})
            if path == "/api/state":
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
            if path == "/api/open":  # sent by a second launch
                threading.Thread(target=app.open_window, daemon=True).start()
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})

    return Handler


def find_browser():
    """Edge ships with Windows; Chrome as fallback. Returns exe path or None."""
    cands = []
    for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        root = os.environ.get(env)
        if root:
            cands += [os.path.join(root, r"Microsoft\Edge\Application\msedge.exe"),
                      os.path.join(root, r"Google\Chrome\Application\chrome.exe")]
    return next((c for c in cands if os.path.isfile(c)), None)


def port_file():
    return os.path.join(os.path.dirname(settings_path()), "running.json")


# ----------------------------------------------------------------------------
# App wiring
# ----------------------------------------------------------------------------
class App:
    def __init__(self):
        import secrets
        self.token = secrets.token_urlsafe(18)
        self.port = None
        self.httpd = None
        self.browser = None
        self.quitting = False
        self.hide_note_shown = False
        self.done = threading.Event()
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

    def _existing_window(self):
        if IS_WIN:
            return user32.FindWindowW("Chrome_WidgetWin_1", APP_NAME)  # browser windows only: an Explorer tab can share this title
        return None

    def open_window(self):
        """Focus the renderer window if open, otherwise open it as a chromeless Edge app window.
        Callers: main(), tray double-click/menu, Ctrl+Shift+F6, /api/open (second launch)."""
        h = self._existing_window()
        if h:
            user32.ShowWindow(h, 9)  # SW_RESTORE
            user32.SetForegroundWindow(h)
            return
        exe = find_browser()
        if not exe:
            import webbrowser
            webbrowser.open(self.url())
            return
        profile = os.path.join(os.path.dirname(settings_path()), "window-profile")
        args = [exe, f"--app={self.url()}", f"--user-data-dir={profile}", "--window-size=1500,940",
                "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"]
        import subprocess
        proc = subprocess.Popen(args, close_fds=True)
        if self.browser is None or self.browser.poll() is not None:
            self.browser = proc
            threading.Thread(target=self._watch, args=(proc,), daemon=True).start()

    def _watch(self, proc):
        proc.wait()  # the window's own browser process exits when its last window closes
        if not self.quitting and not self.hide_note_shown:
            self.hide_note_shown = True
            self.overlay.balloon(APP_NAME, "Still running in the tray. Double-click the icon to reopen, right-click to quit.")

    def quit(self):
        self.quitting = True
        h = self._existing_window()
        if h:
            user32.PostMessageW(h, 0x0010, 0, 0)  # WM_CLOSE the renderer window
        self.overlay.stop()
        try:
            os.remove(port_file())
        except OSError:
            pass
        self.done.set()


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
    set_dpi_aware()
    if IS_WIN:
        kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS -> just open the existing window
            if not signal_running_instance():
                user32.MessageBoxW(None, "Wrap Renderer is already running — check the tray.", APP_NAME, 0x40)
            return
    app = App()
    app.overlay.start()
    app.overlay.ready.wait(3)
    app.serve()
    app.open_window()
    app.done.wait()
    if app.httpd:
        app.httpd.shutdown()


if __name__ == "__main__":
    main()
