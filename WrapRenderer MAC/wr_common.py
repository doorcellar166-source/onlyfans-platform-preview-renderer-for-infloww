"""
Shared constants and storage for Wrap Renderer (all platforms).

Used by: wrap_renderer.py (core), overlay_win.py, overlay_mac.py.
See ARCHITECTURE.md for the full wiring map.
"""
import json
import os
import sys

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

APP_NAME = "Wrap Renderer"        # also the page <title>; overlay_win.focus_window() finds the window by it

# Geometry decoded from wrap_overlay.exe (1920x1080 reference coordinates, scaled to the screen)
REF_W, REF_H = 1920, 1080
GUIDE_LEFT_REF = 615              # left text edge
GUIDE_WRAP_DEFAULT_REF = 957      # default wrap line -> 342 px column
GUIDE_TOP_REF = 720
GUIDE_BOTTOM_REF = 950
DASH_STEP, DASH_LEN = 7, 2        # centre line: 2px dash every 7px
OVERLAY_ALPHA = 140               # 0x8C, same as the original
RED_RGB = (0xFF, 0x3B, 0x3B)      # Infloww preset
CYAN_RGB = (0x3B, 0xD1, 0xFF)     # Mobile preset
DEFAULT_MOBILE_RATIO = 257.4 / 342  # iPhone 16 Pro text width / Infloww width (updated live by the page)
# PC preset (OnlyFans web chat bubble, measured from a 1920-wide screenshot). Independent of the Infloww
# wrap line: its own left edge + absolute width (both editable on the page, pushed via /api/pc).
GUIDE_PC_LEFT_REF = 1061          # left text edge of a received bubble (bubble 1049 + 12 padding)
GUIDE_PC_WIDTH_DEFAULT = 390      # text width (bubble 414 - 2*12 padding) -> wrap at 1451
GUIDE_PC_TOP_REF = 150
GUIDE_PC_BOTTOM_REF = 920
GREEN_RGB = (0x4C, 0xE0, 0x7A)    # PC preset

# Hotkey ids are shared by both overlay modules' dispatch code.
#   id: (label, windows_vk, mac_keycode, auto_repeat)
HOTKEYS = {
    1: ("Ctrl+Shift+F9",  0x78, 101, False),  # toggle Infloww guides
    2: ("Ctrl+Shift+F10", 0x79, 109, True),   # wrap line -1
    3: ("Ctrl+Shift+F11", 0x7A, 103, True),   # wrap line +1
    4: ("Ctrl+Shift+F8",  0x77, 100, False),  # quit
    5: ("Ctrl+Shift+F7",  0x76, 98,  False),  # toggle Mobile guides
    6: ("Ctrl+Shift+F6",  0x75, 97,  False),  # show renderer window
    7: ("Ctrl+Shift+F12", 0x7B, 111, False),  # toggle PC guides
}


def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def data_dir():
    if IS_WIN:
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif IS_MAC:
        root = os.path.expanduser("~/Library/Application Support")
    else:
        root = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    d = os.path.join(root, "WrapRenderer")
    os.makedirs(d, exist_ok=True)
    return d


def settings_path():
    return os.path.join(data_dir(), "settings.json")


# ----------------------------------------------------------------------------
# Wrap-line position (1920-ref px).
# Windows: HKCU\Software\wrapoverlay\wrap, shared with the original wrap_overlay.exe.
# Elsewhere: wrap.json in data_dir().
# ----------------------------------------------------------------------------
REG_KEY = r"Software\wrapoverlay"
REG_VALUE = "wrap"


def load_wrap_ref():
    if IS_WIN:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
                return int(winreg.QueryValueEx(k, REG_VALUE)[0])
        except OSError:
            return None
    try:
        with open(os.path.join(data_dir(), "wrap.json"), encoding="utf-8") as f:
            return float(json.load(f)["wrap"])
    except (OSError, ValueError, KeyError):
        return None


def save_wrap_ref(ref):
    if IS_WIN:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
            winreg.SetValueEx(k, REG_VALUE, 0, winreg.REG_DWORD, int(ref))
        return
    with open(os.path.join(data_dir(), "wrap.json"), "w", encoding="utf-8") as f:
        json.dump({"wrap": round(float(ref), 3)}, f)


def clear_wrap():
    if IS_WIN:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, REG_VALUE)
        except OSError:
            pass
        return
    try:
        os.remove(os.path.join(data_dir(), "wrap.json"))
    except OSError:
        pass
