# Wrap Renderer

Paste or type a PPV message and see how it wraps in **Infloww**, **PC** (OnlyFans web chat) and on an **iPhone** side by side. It also puts on-screen wrap guides over the real Infloww window.

## Launch

**Windows:** double-click **`Start Wrap Renderer (Windows).bat`**. The first time, it finds your Python (or installs it automatically with winget), puts a **Wrap Renderer** shortcut on your desktop, and opens the app. After that, use the shortcut. Quit the old `wrap_overlay.exe` first (same hotkeys).

**Mac:** double-click **`Start Wrap Renderer (Mac).command`**. The first time, macOS may say it can't verify the file: right-click it, choose **Open**, then **Open** again. The first run sets up a private Python environment (about 30 seconds, needs internet) and puts a **Wrap Renderer** app on your Desktop. Use that from then on. The app lives in the menu bar as **⫼**. The Desktop app points at this folder, so if you move the folder, delete the Desktop app and run the .command again.

Launching again while it's running just brings the window back. The window opens in Edge or Chrome (Mac: Chrome, Edge or Brave; otherwise your default browser).

## Hotkeys

| Keys | Action |
|---|---|
| Ctrl+Shift+F9 | Infloww guides on/off (red; same as the old overlay) |
| Ctrl+Shift+F12 | PC guides on/off (green; OnlyFans web chat bubble, left edge 1061 / width 390, both editable in the app) |
| Ctrl+Shift+F7 | Mobile guides on/off (cyan line = where the iPhone wraps) |
| Ctrl+Shift+F10 / F11 | Move the wrap line 1px left/right (saved; the Infloww preview follows) |
| Ctrl+Shift+F6 | Show the renderer window |
| Ctrl+Shift+F8 | Quit |
| Alt+1 / Alt+2 / Alt+3 | Preview guides on/off (inside the app) |
| Ctrl+B / Ctrl+I / Ctrl+Z / Ctrl+Y | Bold / italic / undo / redo |

On a Mac the hotkeys are the same: Control+Shift+F-key. On laptop keyboards hold **fn** as well, e.g. fn+⌃⇧F9.

Windows tray icon: left-click toggles Infloww guides, double-click opens the window, right-click opens the menu (Quit is there). Mac: click **⫼** in the menu bar for the same menu. Closing the window leaves the app running.

Previews: the panes keep their real width and scroll sideways when the window is too narrow. Use the **Previews** buttons at the top right to hide a pane; the others slide over, and the wrap badges compare only the panes still showing.

The on-screen guides use the same positions as the Windows overlay, scaled to your screen. On a Mac, Infloww's column may sit somewhere else. Use F10/F11 to line up the wrap line, and tell me if the left guide needs to move too.

## What's calibrated (from your screenshots)

- Font: Roboto on both. Body 16px, line height 24px. The blue headline is **20px bold on both platforms**.
- Infloww text column: 342px (overlay default; the screenshot fits 334–347).
- iPhone 16 Pro: bubble = 70% of 402pt, 12px padding, so the text column is 257.4px. All visible line breaks in both screenshots reproduce exactly.
- Sizes in Infloww, measured from your TEST message: Smallest 12, Small 14, Medium 16, Large 20, Largest 26. On the phone, Medium and Large are measured. The others are assumed to match because those two did. The grey colour is still a placeholder.

The mobile on-screen guide is exact for body text. Sizes scale the same way on both platforms as far as measured, so it should hold for Large too.
