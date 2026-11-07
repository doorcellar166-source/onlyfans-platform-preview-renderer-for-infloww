# Wrap Renderer: wiring map

Use this before replacing or hooking into any piece. Every function lists who calls it and what it depends on, so you can find everything a change might break.

## Files

| File | Role | Used by |
|---|---|---|
| `Start Wrap Renderer.bat` | Finds or installs Python, makes the desktop shortcut, launches `wrap_renderer.py` with pythonw | user double-click |
| `wrap_renderer.py` | Desktop host: localhost server, Edge app window, overlay, tray, hotkeys (stdlib only) | launcher, desktop shortcut |
| `renderer.html` | Editor, paste/copy, previews, calibration UI (also works standalone in a browser) | served at `/` by `make_handler()` (`STATIC` map) |
| `roboto.css` | Roboto 400/700 normal + italic as data-URI woff2 | `<link>` in `renderer.html`; served via `STATIC` |
| `%APPDATA%\WrapRenderer\settings.json` | Calibration, toggles, learned class names, last draft | `POST/GET /api/settings` ← `saveSettings()` / `loadSettings()` in JS |
| `%APPDATA%\WrapRenderer\running.json` | Port + token of the running copy | `App.serve` writes; `signal_running_instance` reads (second launch → `/api/open`); `App.quit` deletes |
| `%APPDATA%\WrapRenderer\window-profile\` | Separate Edge profile for the app window | `App.open_window` |
| `HKCU\Software\wrapoverlay\wrap` (DWORD, 1920-ref px) | Wrap line position, **shared with the original wrap_overlay.exe** | `reg_load_wrap_ref`, `reg_save_wrap_ref`, `reg_clear_wrap` |

## Calibration constants (change these together)

| Constant | Where | Also referenced by |
|---|---|---|
| Overlay left 615 / wrap 957 / top 720 / bottom 950 (1920×1080 ref) | `GUIDE_*_REF` in `wrap_renderer.py` | `OVERLAY_LEFT_REF`, `OVERLAY_WRAP_DEFAULT_REF` in `renderer.html` (default Infloww width = 342); `state()["leftRef"]` |
| PC left 1061 / width 390 / top 150 / bottom 920 (1920×1080 ref; OnlyFans web chat bubble). Width is absolute, not derived from the Infloww wrap | `GUIDE_PC_LEFT_REF`, `GUIDE_PC_WIDTH_DEFAULT`, `GUIDE_PC_TOP_REF`, `GUIDE_PC_BOTTOM_REF` in `wrap_renderer.py` | `PC_LEFT_REF_DEFAULT`, `PC_WIDTH_DEFAULT` in `renderer.html` (`S.pcLeft`/`S.pcWidth`, pushed by `pushPcToHost()`) |
| Font sizes per level, per platform | `DEFAULTS.sizes` in `renderer.html` | `applyPaneVars()` (CSS vars `--xs…--xl`), `nearestLevel()` (paste mapping uses the **infloww** table), `resolveStyle()` (`<font size>`), `exportHTML()` (inline `font-size`) |
| Measured/placeholder flags | `DEFAULTS.measured` | `buildCalibration()` tags only. They're always reset from DEFAULTS on load |
| Colours | CSS vars on `#infTxt`, `#phone.light/.dark`, `#ed`; `PALETTE.infloww` | `exportHTML()` uses `PALETTE.infloww`; toolbar swatches use `PALETTE.infloww` |
| Phone text width = `deviceW × (device pct or bubblePct)% − 2 × bubblePad` | `mobileTextWidth()` | `applyPaneVars()`, `doRefresh()` meta, `pushRatioToHost()` → overlay mobile line |
| Line height 24px | `DEFAULTS.lineHeight` | `applyPaneVars()` |
| Hotkey ids/keys (id 7 = Ctrl+Shift+F12, PC guides) | `HOTKEYS` in `wrap_renderer.py` | `Overlay.run()` (register), `Overlay._proc()` (dispatch by id), tray tooltip and menu labels, `#gInf/#gPC/#gMob` labels in `renderer.html`, README |

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

## wrap_renderer.py functions

| Function | Called by | Depends on |
|---|---|---|
| `Overlay.run()` | `App.overlay.start()` in `main()` | Win32 bindings, `HOTKEYS`, `reg_load_wrap_ref` |
| `Overlay._proc()` | Windows (WNDPROC) | `_paint`, `_menu`, `_refresh`, `_quit`, `on_open` |
| `Overlay._paint()` | `WM_PAINT` | `GUIDE_*`, `mobile_ratio`, `pc_left_ref`/`pc_width_ref`, brushes (red/cyan/green) |
| `Overlay.toggle/nudge/reset_wrap/set_ratio/set_pc/balloon/stop` | `/api/*` handlers, `App._watch`, `App.quit`, `main()` | post `WM_APP_*` to the overlay thread (thread-safe) |
| `Overlay.state()` | `/api/state`, `/api/toggle`, `/api/nudge`, `/api/reset` | lock |
| `make_handler(app)` → `/api/state, toggle, ratio, pc, nudge, reset, settings, open` | page via `makeHttpHost`; `/api/open` from `signal_running_instance` | `X-Token` must equal `App.token` |
| `App.open_window` | `main()`, tray double-click/menu, Ctrl+Shift+F6, `/api/open` | `find_browser`, `FindWindowW(APP_NAME)`. **Page `<title>` must stay "Wrap Renderer"** |
| `App._watch` | `open_window` | shows the "still in tray" balloon when the window closes |
| `App.quit` | tray Quit, Ctrl+Shift+F8 | closes the window, `Overlay.stop`, deletes `running.json` |

## Hook points for add-ons

- **New text format** (e.g. underline): add a key to `plainStyle/pick/same`, a class in `spanFor` + CSS, a toolbar button → `applyFormat`, parsing in `resolveStyle`, output in `exportHTML`.
- **New device**: add to `DEVICES`.
- **New overlay preset**: add a flag to `Overlay`, a branch in `_paint`, a hotkey in `HOTKEYS` + `_proc`, a menu item in `_menu`, a key in `state()`, and a button + `hostState` handling in `renderer.html`.
