# Wrap Renderer: wiring map

Use this before replacing or hooking into any piece. Every function lists who calls it and what it depends on, so you can find everything a change might break.

## Files

| File | Role | Used by |
|---|---|---|
| `Start Wrap Renderer (Windows).bat` | Finds or installs Python, makes the desktop shortcut, launches `wrap_renderer.py` with pythonw | user double-click |
| `Start Wrap Renderer (Mac).command` | Finds Python 3, creates a venv with PyObjC in `~/Library/Application Support/WrapRenderer/venv`, makes `~/Desktop/Wrap Renderer.app` (osacompile; **hard-codes this folder's path**), launches | user double-click |
| `wrap_renderer.py` | Shared core: localhost server, browser app window, App lifecycle, `NullOverlay` for Linux/tests. Picks the backend by OS | both launchers and shortcuts |
| `wr_common.py` | Constants (geometry, colours, `HOTKEYS` table, `APP_NAME`), data dir, wrap-line storage | `wrap_renderer.py`, `overlay_win.py`, `overlay_mac.py` |
| `overlay_win.py` | Windows backend: Win32 overlay, tray, `RegisterHotKey`, `FindWindowW` focus, mutex | `wrap_renderer.py` (when `IS_WIN`) |
| `overlay_mac.py` | macOS backend: NSWindow overlay, NSStatusItem menu, Carbon `RegisterEventHotKey`, NSRunningApplication focus, flock single-instance | `wrap_renderer.py` (when `IS_MAC`) |
| `renderer.html` | Editor, paste/copy, previews, calibration UI (also works standalone in a browser) | served at `/` by `make_handler()` (`STATIC` map) |
| `roboto.css` | Roboto 400/700 normal + italic as data-URI woff2 | `<link>` in `renderer.html`; served via `STATIC` |
| `data_dir()/settings.json` (Win `%APPDATA%\WrapRenderer`, Mac `~/Library/Application Support/WrapRenderer`) | Calibration, toggles, learned class names, last draft | `POST/GET /api/settings` ← `saveSettings()` / `loadSettings()` in JS |
| `data_dir()/running.json` | Port + token of the running copy | `App.serve` writes; `signal_running_instance` reads (second launch → `/api/open`); `App.quit` deletes |
| `data_dir()/window-profile/` | Separate Edge profile for the app window | `App.open_window` |
| Wrap line: Win `HKCU\Software\wrapoverlay\wrap` (DWORD, **shared with wrap_overlay.exe**); Mac `data_dir()/wrap.json` | 1920-ref px | `load_wrap_ref`, `save_wrap_ref`, `clear_wrap` in `wr_common.py` |

## Calibration constants (change these together)

| Constant | Where | Also referenced by |
|---|---|---|
| Overlay left 615 / wrap 957 / top 720 / bottom 950 (1920×1080 ref) | `GUIDE_*_REF` in `wr_common.py` | `OVERLAY_LEFT_REF`, `OVERLAY_WRAP_DEFAULT_REF` in `renderer.html` (default Infloww width = 342); `state()["leftRef"]` |
| PC left 1061 / width 390 / top 150 / bottom 920 (1920×1080 ref; OnlyFans web chat bubble). Width is absolute, not derived from the Infloww wrap | `GUIDE_PC_LEFT_REF`, `GUIDE_PC_WIDTH_DEFAULT`, `GUIDE_PC_TOP_REF`, `GUIDE_PC_BOTTOM_REF` in `wr_common.py` | `PC_LEFT_REF_DEFAULT`, `PC_WIDTH_DEFAULT` in `renderer.html` (`S.pcLeft`/`S.pcWidth`, pushed by `pushPcToHost()`) |
| Font sizes per level, per platform | `DEFAULTS.sizes` in `renderer.html` | `applyPaneVars()` (CSS vars `--xs…--xl`), `nearestLevel()` (paste mapping uses the **infloww** table), `resolveStyle()` (`<font size>`), `exportHTML()` (inline `font-size`) |
| Measured/placeholder flags | `DEFAULTS.measured` | `buildCalibration()` tags only. They're always reset from DEFAULTS on load |
| Colours | CSS vars on `#infTxt`, `#phone.light/.dark`, `#ed`; `PALETTE.infloww` | `exportHTML()` uses `PALETTE.infloww`; toolbar swatches use `PALETTE.infloww` |
| Phone text width = `deviceW × (device pct or bubblePct)% − 2 × bubblePad` | `mobileTextWidth()` | `applyPaneVars()`, `doRefresh()` meta, `pushRatioToHost()` → overlay mobile line |
| Line height 24px | `DEFAULTS.lineHeight` | `applyPaneVars()` |
| Hotkey ids/keys (Win VK + Mac keycode; id 7 = Ctrl+Shift+F12, PC guides) | `HOTKEYS` in `wr_common.py` | `overlay_win.Overlay.run()` + `_proc()`; `overlay_mac.Overlay._register_hotkeys()` + `_hotkey()`; tray/menu labels in both; `#gInf/#gPC/#gMob` labels in `renderer.html`; README |

## renderer.html functions

| Function | Called by | Depends on |
|---|---|---|
| `walk(root,{collapse,learn})` | `syncFromDom`, `indexAt`, `doPaste` (pasted HTML), tests | `resolveStyle`, `BLOCK`, `SKIP`, `pick` |
| `resolveStyle(el,inh,learn)` | `walk` | `classToken`, `classifyColor`, `toPx`, `nearestLevel`, `S.sizes.infloww` |
| `classToken(tok)` | `resolveStyle` | `SIZE_CTX`, `SIZE_WORDS`. **Edit this to map Infloww's real class names** |
| `classifyColor(str)` | `resolveStyle` | `parseColor` (canvas normaliser) |
| `runsHTML(arr)` / `spanFor` | `renderEditor`, `renderPane` | `same`, `esc` |
| `exportHTML(arr)` | `copyAll`, `exportSelection` (Ctrl+C / Ctrl+X) | `S.exportBreaks`, `S.exportInlineStyles`, `S.learned`, `PALETTE.infloww`, `S.sizes.infloww`; writes `#insExport` |
| `renderEditor()` | `modelReplace`, `applyFormat`, `restore`, input normaliser, `loadSample`, boot | `runsHTML` |
| `getSel()` / `setSel()` / `indexAt()` / `pointAt()` | every model op, `updateToolbar`, selectionchange | `walk` (counting must match the model) |
| `modelReplace` / `modelInsertText` | `beforeinput` (Enter, pending-style typing), `doPaste`, cut | `renderEditor`, `setSel`, `refresh` |
| `applyFormat(key,val)` | toolbar buttons, Ctrl+B/I, `beforeinput` format* | `pending`, `styleAt`, `pushHistory` |
| `pushHistory` / `undo` / `redo` | `beforeinput`, keydown Ctrl+Z/Y, model ops | `snap`, `restore` |
| `doPaste(html,text)` | editor `paste` event, `pasteButton` | `walk(collapse:true)`, `S.learned`, `updateInspector` |
| `restoreCopiedSpaces(doc)` | `doPaste` | Turns Chrome's bare `<span>&nbsp;</span>` copy marker back into a plain space; other NBSPs stay |
| `#mobOS` button | user | Switches `S.device` between `android` and `S.lastIphone`; `applyPaneVars()` sets `.ios` / `.android` on `#mobTxt`, which set measured symbol widths |
| `applyPaneVars()` | boot, calibration change, `hostState`, guide/theme toggles | `S`, `mobileTextWidth`, `deviceWidth`, `pushRatioToHost` |
| `PANES` (const) | `doRefresh`, `applyPaneVars`, `bindUi` | Pane order + element ids. Toggles `S.panes` from the top-bar Previews buttons (`#pvInf/#pvPC/#pvMob`) |
| `doRefresh()` (via `refresh()` rAF) | any model or settings change | `PANES`, `S.panes`, `splitLines`, `renderPane`, `visualLines`; calls `saveSettingsSoon`. Compares **visible panes only**: hidden panes are `display:none` and can't be measured, so badges shrink to the panes on screen |
| `visualLines(div)` | `doRefresh` | `Range.getClientRects` |
| `makeHttpHost(token)` | `boot()` (token from `?t=`) | `/api/*` endpoints in `make_handler` |
| `pollHost()` (every 400ms) | `boot()` | `host.get_state`, calls `hostState` on change |
| `window.hostState(st)` | `pollHost`, `#gInf/#gPC/#gMob` click results, boot | `syncInflowwFromHost`, `applyPaneVars` |
| `pushRatioToHost()` | `applyPaneVars` | `host.set_mobile_ratio` |
| `pushPcToHost()` | `applyPaneVars` | `host.set_pc(left,width)` → `POST /api/pc` → `Overlay.set_pc` |
| `saveSettings` / `loadSettings` | `saveSettingsSoon`, boot | `host.save_settings/load_settings`, or localStorage in browser mode |

## Python functions

Both `overlay_win.Overlay` and `overlay_mac.Overlay` (and `NullOverlay`) implement the same interface: `start, ready, state, toggle, set_ratio, set_pc, nudge, reset_wrap, balloon, stop, run_main_loop, focus_window, close_window`. Each module also has `set_dpi_aware, acquire_single_instance, notify`. `set_pc(left,width)` is implemented by both `overlay_win` and `overlay_mac` (the NullOverlay stub stores it). **Change one, change all three.**

| Function | Called by | Depends on |
|---|---|---|
| `overlay_win.Overlay.run()` | its `start()` (thread) in `main()` | Win32 bindings, `HOTKEYS`, `load_wrap_ref` |
| `overlay_mac.Overlay.start()` | `main()` on the main thread | AppKit, Carbon, `HOTKEYS`, `load_wrap_ref` |
| `overlay_mac.GuideView.drawRect_` / `MenuTarget.*` / `_hotkey_handler` | Cocoa / Carbon | module global `_OVERLAY` |
| `Overlay._proc()` | Windows (WNDPROC) | `_paint`, `_menu`, `_refresh`, `_quit`, `on_open` |
| `Overlay._paint()` | `WM_PAINT` | `GUIDE_*`, `mobile_ratio`, `pc_left_ref`/`pc_width_ref`, brushes (red/cyan/green) |
| `Overlay.toggle/nudge/reset_wrap/set_ratio/set_pc/balloon/stop` | `/api/*` handlers, `App._watch`, `App.quit`, `main()` | post `WM_APP_*` to the overlay thread (thread-safe) |
| `Overlay.state()` | `/api/state`, `/api/toggle`, `/api/nudge`, `/api/reset` | lock |
| `make_handler(app)` → `/api/state, toggle, ratio, pc, nudge, reset, settings, open` | page via `makeHttpHost`; `/api/open` from `signal_running_instance` | `X-Token` must equal `App.token` |
| `App.open_window` | `main()`, tray/menu-bar Open, Ctrl+Shift+F6, `/api/open` | `find_browser`, `overlay.focus_window` (Win: `FindWindowW(APP_NAME)`, so **page `<title>` must stay "Wrap Renderer"**; Mac: activate the browser pid if `window_open()`) |
| `App.window_open` | `open_window` | `last_poll` (set by `/api/state`, reset by the page's `pagehide` beacon to `/api/closed`) |
| `App._watch` | `open_window` | shows the "still in tray" balloon when the window closes |
| `App.quit` | tray Quit, Ctrl+Shift+F8 | closes the window, `Overlay.stop`, deletes `running.json` |

## Hook points for add-ons

- **New text format** (e.g. underline): add a key to `plainStyle/pick/same`, a class in `spanFor` + CSS, a toolbar button → `applyFormat`, parsing in `resolveStyle`, output in `exportHTML`.
- **New device**: add to `DEVICES`.
- **New overlay preset**: add a flag to `Overlay`, a branch in `_paint`, a hotkey in `HOTKEYS` + `_proc`, a menu item in `_menu`, a key in `state()`, and a button + `hostState` handling in `renderer.html`.
