"""
Windows overlay backend: click-through guide window, tray icon, global hotkeys (Win32 via ctypes).
A port of wrap_overlay.exe plus the Mobile preset.

Interface (same as overlay_mac.Overlay; used by wrap_renderer.App):
  Overlay(on_open, on_quit) .start() .ready .state() .toggle(name) .set_ratio(r) .nudge(d)
  .reset_wrap() .balloon(title, text) .stop() .run_main_loop(done) .focus_window(proc) .close_window(proc)
Module functions: set_dpi_aware(), acquire_single_instance(), notify(msg)
"""
import sys
import threading

from wr_common import (APP_NAME, CYAN_RGB, DASH_LEN, DASH_STEP, DEFAULT_MOBILE_RATIO, GREEN_RGB, GUIDE_BOTTOM_REF,
                       GUIDE_LEFT_REF, GUIDE_PC_BOTTOM_REF, GUIDE_PC_LEFT_REF, GUIDE_PC_TOP_REF,
                       GUIDE_PC_WIDTH_DEFAULT, GUIDE_TOP_REF, GUIDE_WRAP_DEFAULT_REF, HOTKEYS, IS_WIN,
                       OVERLAY_ALPHA, RED_RGB, REF_H, REF_W, clear_wrap, load_wrap_ref, save_wrap_ref)

MUTEX_NAME = "wrap_renderer_singleton"
COLOR_KEY = 0x010101  # transparent colour key (COLORREF)


def _colorref(rgb):
    r, g, b = rgb
    return (b << 16) | (g << 8) | r


RED = _colorref(RED_RGB)    # 0x3B3BFF, same as the original
CYAN = _colorref(CYAN_RGB)
GREEN = _colorref(GREEN_RGB)

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
            save_wrap_ref(self.wrap_px * REF_W // self.sw)
        self._post(WM_APP_REFRESH if IS_WIN else 0)

    def reset_wrap(self):
        clear_wrap()
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
        ref = load_wrap_ref()
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

        for hid, (label, vk, _mac, repeat) in HOTKEYS.items():
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
            clear_wrap()
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
        if pc:  # starts at the Infloww text edge, PC text width
            pl, pr = left, self._x(GUIDE_LEFT_REF + pcw)  # same left edge as the Infloww text; width is absolute
            pt, pb = top, bottom  # same vertical span as the Infloww guides
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
                        save_wrap_ref(self.wrap_px * REF_W // self.sw)
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

    # ---- window helpers + main loop (called by wrap_renderer.App / main) ----
    def focus_window(self, proc):
        h = user32.FindWindowW("Chrome_WidgetWin_1", APP_NAME)  # browser windows only: an Explorer tab can share this title
        if h:
            user32.ShowWindow(h, 9)  # SW_RESTORE
            user32.SetForegroundWindow(h)
            return True
        return False

    def close_window(self, proc):
        h = user32.FindWindowW("Chrome_WidgetWin_1", APP_NAME)  # browser windows only: an Explorer tab can share this title
        if h:
            user32.PostMessageW(h, WM_CLOSE, 0, 0)

    def run_main_loop(self, done):
        done.wait()


def acquire_single_instance():
    """True if we're the only copy. Keeps the mutex handle alive for the process lifetime."""
    global _MUTEX
    _MUTEX = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def notify(msg):
    user32.MessageBoxW(None, msg, APP_NAME, 0x40)


_MUTEX = None
