"""
macOS overlay backend: click-through guide window, menu-bar item, global hotkeys.

  * Guides: borderless transparent NSWindow above everything, ignores the mouse, on every Space.
  * Menu bar: "⫼" item (the tray equivalent) with Open / guides / reset / Quit.
  * Hotkeys: Carbon RegisterEventHotKey (no Accessibility permission needed).
    Same keys as Windows: Ctrl+Shift+F6…F11 (on laptops add fn).

Needs PyObjC (pyobjc-framework-Cocoa), which "Start Wrap Renderer.command" installs into a private venv.

Interface (same as overlay_win.Overlay; used by wrap_renderer.App):
  Overlay(on_open, on_quit) .start() .ready .state() .toggle(name) .set_ratio(r) .nudge(d)
  .reset_wrap() .balloon(title, text) .stop() .run_main_loop(done) .focus_window(proc) .close_window(proc)
Module functions: set_dpi_aware(), acquire_single_instance(), notify(msg)
"""
import ctypes
import ctypes.util
import os
import subprocess
import sys
import threading

import objc  # noqa: F401  (loads the bridge)
from AppKit import (NSApplication, NSBackingStoreBuffered, NSBezierPath, NSColor, NSMenu, NSMenuItem,
                    NSRunningApplication, NSScreen, NSStatusBar, NSVariableStatusItemLength, NSView, NSWindow,
                    NSRectFillUsingOperation)
from Foundation import NSMakeRect, NSObject
from PyObjCTools import AppHelper

from wr_common import (APP_NAME, CYAN_RGB, DASH_LEN, DASH_STEP, DEFAULT_MOBILE_RATIO, GREEN_RGB, GUIDE_BOTTOM_REF,
                       GUIDE_LEFT_REF, GUIDE_PC_BOTTOM_REF, GUIDE_PC_LEFT_REF, GUIDE_PC_TOP_REF,
                       GUIDE_PC_WIDTH_DEFAULT, GUIDE_TOP_REF, GUIDE_WRAP_DEFAULT_REF, HOTKEYS, OVERLAY_ALPHA,
                       RED_RGB, REF_H, REF_W, clear_wrap, data_dir, load_wrap_ref, save_wrap_ref)

_OVERLAY = None  # the single Overlay instance; read by GuideView / MenuTarget / hotkey callback

NS_ACTIVATION_ACCESSORY = 1          # no Dock icon
NS_STATUS_WINDOW_LEVEL = 25          # above normal and floating windows
NS_COMPOSITE_COPY = 1
NS_ACTIVATE_IGNORING_OTHER_APPS = 1 << 1
COLLECTION = (1 << 0) | (1 << 4) | (1 << 6) | (1 << 8)  # all Spaces | stationary | ignores cycle | fullscreen aux


def _nscolor(rgb):
    r, g, b = rgb
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r / 255, g / 255, b / 255, OVERLAY_ALPHA / 255)


# ----------------------------------------------------------------------------
# Carbon global hotkeys
# ----------------------------------------------------------------------------
_carbon = ctypes.CDLL(ctypes.util.find_library("Carbon"))


def _fourcc(s):
    return int.from_bytes(s.encode("ascii"), "big")


class EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


EventHandlerProc = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
_carbon.GetApplicationEventTarget.argtypes = []
_carbon.InstallEventHandler.restype = ctypes.c_int32
_carbon.InstallEventHandler.argtypes = [ctypes.c_void_p, EventHandlerProc, ctypes.c_ulong,
                                        ctypes.POINTER(EventTypeSpec), ctypes.c_void_p, ctypes.c_void_p]
_carbon.RegisterEventHotKey.restype = ctypes.c_int32
_carbon.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, EventHotKeyID, ctypes.c_void_p,
                                        ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
_carbon.GetEventParameter.restype = ctypes.c_int32
_carbon.GetEventParameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                      ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]
K_EVENT_CLASS_KEYBOARD = _fourcc("keyb")
K_EVENT_HOTKEY_PRESSED = 5
K_PARAM_DIRECT = _fourcc("----")
K_TYPE_HOTKEY_ID = _fourcc("hkid")
CARBON_SHIFT, CARBON_CONTROL = 0x0200, 0x1000
HOTKEY_SIGNATURE = _fourcc("WRen")


@EventHandlerProc
def _hotkey_handler(_callref, event, _userdata):
    hk = EventHotKeyID()
    _carbon.GetEventParameter(event, K_PARAM_DIRECT, K_TYPE_HOTKEY_ID, None, ctypes.sizeof(hk), None,
                              ctypes.byref(hk))
    if _OVERLAY:
        try:
            _OVERLAY._hotkey(hk.id)
        except Exception as e:
            print("hotkey error:", e, file=sys.stderr)
    return 0


# ----------------------------------------------------------------------------
# Cocoa classes
# ----------------------------------------------------------------------------
class GuideView(NSView):
    def isFlipped(self):  # top-left origin, same maths as Windows
        return True

    def drawRect_(self, rect):
        NSColor.clearColor().set()
        NSRectFillUsingOperation(rect, NS_COMPOSITE_COPY)
        if _OVERLAY:
            _OVERLAY._draw()


class MenuTarget(NSObject):
    def openRenderer_(self, sender):
        _OVERLAY._async(_OVERLAY.on_open)

    def toggleInfloww_(self, sender):
        _OVERLAY.toggle("infloww")

    def toggleMobile_(self, sender):
        _OVERLAY.toggle("mobile")

    def togglePC_(self, sender):
        _OVERLAY.toggle("pc")

    def resetWrap_(self, sender):
        _OVERLAY.reset_wrap()

    def quitApp_(self, sender):
        _OVERLAY._async(_OVERLAY.on_quit)

    def menuNeedsUpdate_(self, menu):
        _OVERLAY._sync_menu()


# ----------------------------------------------------------------------------
# Overlay
# ----------------------------------------------------------------------------
class Overlay:
    """Callers: wrap_renderer.App (constructor, start, run_main_loop, focus/close, stop),
    /api/* handlers (toggle, set_ratio, nudge, reset_wrap, state)."""

    def __init__(self, on_change=None, on_open=None, on_quit=None):
        self.on_change = on_change or (lambda st: None)
        self.on_open = on_open or (lambda: None)
        self.on_quit = on_quit or (lambda: None)
        self.lock = threading.Lock()
        self.ready = threading.Event()
        self.show_infloww = False
        self.show_mobile = False
        self.show_pc = False
        self.mobile_ratio = DEFAULT_MOBILE_RATIO
        self.pc_left_ref = float(GUIDE_PC_LEFT_REF)      # 1920-ref units, set by the page via set_pc()
        self.pc_width_ref = float(GUIDE_PC_WIDTH_DEFAULT)
        self.hotkey_errors = []
        self.sw, self.sh = float(REF_W), float(REF_H)
        self.wrap_px = float(GUIDE_WRAP_DEFAULT_REF)
        self._hotkey_refs = []

    # ---- geometry (points) ----------------------------------------------------
    def _x(self, ref):
        return ref * self.sw / REF_W

    def _y(self, ref):
        return ref * self.sh / REF_H

    def wrap_ref(self):
        return round(self.wrap_px * REF_W / self.sw, 2)

    def state(self):
        with self.lock:
            return {"infloww": self.show_infloww, "mobile": self.show_mobile, "pc": self.show_pc,
                    "wrapRef": self.wrap_ref(), "leftRef": GUIDE_LEFT_REF,
                    "screen": [self.sw, self.sh], "hotkeyErrors": list(self.hotkey_errors),
                    "available": True}

    # ---- setup: must run on the main thread before run_main_loop -----------------
    def start(self):
        global _OVERLAY
        _OVERLAY = self
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NS_ACTIVATION_ACCESSORY)

        frame = NSScreen.mainScreen().frame()
        self.sw, self.sh = float(frame.size.width), float(frame.size.height)
        ref = load_wrap_ref()
        self.wrap_px = self._x(ref if ref is not None else GUIDE_WRAP_DEFAULT_REF)
        self.red, self.cyan, self.green = _nscolor(RED_RGB), _nscolor(CYAN_RGB), _nscolor(GREEN_RGB)

        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(frame, 0, NSBackingStoreBuffered, False)
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setIgnoresMouseEvents_(True)
        win.setHasShadow_(False)
        win.setLevel_(NS_STATUS_WINDOW_LEVEL)
        win.setCollectionBehavior_(COLLECTION)
        win.setReleasedWhenClosed_(False)
        view = GuideView.alloc().initWithFrame_(NSMakeRect(0, 0, self.sw, self.sh))
        win.setContentView_(view)
        win.setFrame_display_(frame, False)
        win.orderOut_(None)
        self.win, self.view = win, view

        self._build_menu()
        self._register_hotkeys()
        self.ready.set()

    def _build_menu(self):
        self.target = MenuTarget.alloc().init()
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self.item.button().setTitle_("⫼")
        self.item.button().setToolTip_(f"{APP_NAME} (Ctrl+Shift+F9 Infloww, F12 PC, F7 Mobile, F8 quit)")
        menu = NSMenu.alloc().init()
        menu.setAutoenablesItems_(False)
        menu.setDelegate_(self.target)

        def add(title, action):
            it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
            it.setTarget_(self.target)
            menu.addItem_(it)
            return it

        add("Open renderer  (⌃⇧F6)", "openRenderer:")
        menu.addItem_(NSMenuItem.separatorItem())
        self.mi_inf = add("Infloww guides  (⌃⇧F9)", "toggleInfloww:")
        self.mi_pc = add("PC guides  (⌃⇧F12)", "togglePC:")
        self.mi_mob = add("Mobile guides  (⌃⇧F7)", "toggleMobile:")
        add("Reset wrap line to default", "resetWrap:")
        menu.addItem_(NSMenuItem.separatorItem())
        add("Quit  (⌃⇧F8)", "quitApp:")
        self.item.setMenu_(menu)

    def _sync_menu(self):
        self.mi_inf.setState_(1 if self.show_infloww else 0)
        self.mi_mob.setState_(1 if self.show_mobile else 0)
        self.mi_pc.setState_(1 if self.show_pc else 0)

    def _register_hotkeys(self):
        target = _carbon.GetApplicationEventTarget()
        spec = EventTypeSpec(K_EVENT_CLASS_KEYBOARD, K_EVENT_HOTKEY_PRESSED)
        _carbon.InstallEventHandler(target, _hotkey_handler, 1, ctypes.byref(spec), None, None)
        for hid, (label, _vk, keycode, _rep) in HOTKEYS.items():
            ref = ctypes.c_void_p()
            err = _carbon.RegisterEventHotKey(keycode, CARBON_CONTROL | CARBON_SHIFT,
                                              EventHotKeyID(HOTKEY_SIGNATURE, hid), target, 0, ctypes.byref(ref))
            if err:
                self.hotkey_errors.append(label)
            else:
                self._hotkey_refs.append(ref)

    # ---- events (main thread) --------------------------------------------------------
    def _hotkey(self, hid):
        if hid == 1:
            self.toggle("infloww")
        elif hid == 5:
            self.toggle("mobile")
        elif hid == 7:
            self.toggle("pc")
        elif hid in (2, 3):
            self.nudge(-1 if hid == 2 else 1)
        elif hid == 4:
            self._async(self.on_quit)
        elif hid == 6:
            self._async(self.on_open)

    def _refresh(self):
        if self.show_infloww or self.show_mobile or self.show_pc:
            self.win.orderFrontRegardless()
        else:
            self.win.orderOut_(None)
        self.view.setNeedsDisplay_(True)

    def _draw(self):
        with self.lock:
            inf, mob, wrap, ratio = self.show_infloww, self.show_mobile, self.wrap_px, self.mobile_ratio
            pc, pcl, pcw = self.show_pc, self.pc_left_ref, self.pc_width_ref
        left, top, bottom = self._x(GUIDE_LEFT_REF), self._y(GUIDE_TOP_REF), self._y(GUIDE_BOTTOM_REF)

        def bar(x, y0, y1, color):
            color.set()
            NSBezierPath.fillRect_(NSMakeRect(round(x), y0, 1, y1 - y0))

        def dashed(x, color):
            y = top
            while y < bottom:
                bar(x, y, min(y + DASH_LEN, bottom), color)
                y += DASH_STEP

        if inf:
            bar(left, top, bottom, self.red)
            bar(wrap, top, bottom, self.red)
            dashed((left + wrap) / 2, self.red)
        if mob:
            mwrap = left + (wrap - left) * ratio
            if not inf:
                bar(left, top, bottom, self.cyan)
            bar(mwrap, top, bottom, self.cyan)
            dashed((left + mwrap) / 2, self.cyan)
        if pc:  # own left edge + absolute width, own vertical span (chat pane, not the composer)
            pl, pr = self._x(pcl), self._x(pcl + pcw)
            pt, pb = self._y(GUIDE_PC_TOP_REF), self._y(GUIDE_PC_BOTTOM_REF)
            bar(pl, pt, pb, self.green)
            bar(pr, pt, pb, self.green)
            y = pt
            while y < pb:
                bar((pl + pr) / 2, y, min(y + DASH_LEN, pb), self.green)
                y += DASH_STEP

    # ---- thread-safe API ---------------------------------------------------------
    def toggle(self, name):
        with self.lock:
            if name == "infloww":
                self.show_infloww = not self.show_infloww
            elif name == "mobile":
                self.show_mobile = not self.show_mobile
            elif name == "pc":
                self.show_pc = not self.show_pc
        AppHelper.callAfter(self._refresh)

    def set_ratio(self, r):
        if r and 0.2 < r < 3:
            with self.lock:
                self.mobile_ratio = r
            AppHelper.callAfter(self._refresh)

    def set_pc(self, left, width):
        """PC guide: left text edge + text width, both 1920-ref units."""
        if left and width and 0 < left < REF_W and 50 < width < REF_W:
            with self.lock:
                self.pc_left_ref, self.pc_width_ref = float(left), float(width)
            AppHelper.callAfter(self._refresh)

    def nudge(self, d):
        with self.lock:
            self.wrap_px += d
            save_wrap_ref(self.wrap_px * REF_W / self.sw)
        AppHelper.callAfter(self._refresh)

    def reset_wrap(self):
        clear_wrap()
        with self.lock:
            self.wrap_px = self._x(GUIDE_WRAP_DEFAULT_REF)
        AppHelper.callAfter(self._refresh)

    def balloon(self, title, text):
        script = f'display notification {_as_str(text)} with title {_as_str(title)}'
        subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(self):
        AppHelper.callAfter(NSApplication.sharedApplication().terminate_, None)

    def run_main_loop(self, done):
        AppHelper.runEventLoop(installInterrupt=True)

    # ---- renderer window helpers ------------------------------------------------------
    def focus_window(self, proc):
        """proc = the browser process running our app window (wrap_renderer.App.open_window)."""
        if proc is None or proc.poll() is not None:
            return False
        ra = NSRunningApplication.runningApplicationWithProcessIdentifier_(proc.pid)
        if ra is None:
            return False
        ra.activateWithOptions_(NS_ACTIVATE_IGNORING_OTHER_APPS)
        return True

    def close_window(self, proc):
        if proc is not None and proc.poll() is None:
            proc.terminate()  # our private browser profile, so this only closes the renderer

    @staticmethod
    def _async(fn):
        threading.Thread(target=fn, daemon=True).start()


def _as_str(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def set_dpi_aware():
    pass  # macOS works in points already


_LOCK_FH = None


def acquire_single_instance():
    global _LOCK_FH
    import fcntl
    _LOCK_FH = open(os.path.join(data_dir(), "instance.lock"), "w")
    try:
        fcntl.flock(_LOCK_FH, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def notify(msg):
    subprocess.Popen(["osascript", "-e", f'display dialog {_as_str(msg)} with title {_as_str(APP_NAME)} buttons {{"OK"}}'],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
