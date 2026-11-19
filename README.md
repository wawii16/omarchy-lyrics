# Omarchy Lyrics

A third-party native Omarchy shell plugin for synchronized lyrics. The plugin is named for Omarchy to leave room for future players, but **Adam Apple Music is currently the only supported backend**. It bundles its own backend and does not depend on the standalone `~/adam-lyrics` application or its tray.

## Requirements

- Omarchy shell with the schema-1 service/overlay/bar-widget plugin API, Quickshell and Hyprland.
- `python3`, `busctl`, and a running Adam client with MPRIS and its local lyrics engine (default `https://127.0.0.1:20025`).
- `/usr/bin/python3` with Python GObject, GTK 3 and Ayatana AppIndicator 3 for the tray; a StatusNotifier host such as Omarchy's tray widget must be enabled. Missing tray dependencies do not prevent IPC controls or the backend, but the tray process retries every 10 seconds.
- A Wayland session with `XDG_RUNTIME_DIR` set. The backend itself uses only the Python standard library.

## Installation (opt-in)

Nothing is installed or enabled automatically. Stop the old standalone companion before enabling this plugin to avoid duplicate overlays, tray icons and polling. An older bar-only plugin may be installed as `adam.lyrics`; disable it separately if present. This plugin uses the distinct ID `io.github.wawii16.omarchy-lyrics` and does not overwrite it. Do not modify Adam.

From this directory:

```sh
mkdir -p "$HOME/.config/omarchy/plugins"
test ! -e "$HOME/.config/omarchy/plugins/io.github.wawii16.omarchy-lyrics" || { echo 'plugin directory already exists' >&2; exit 1; }
cp -R . "$HOME/.config/omarchy/plugins/io.github.wawii16.omarchy-lyrics"
omarchy-shell shell rescanPlugins
omarchy plugin enable io.github.wawii16.omarchy-lyrics
```

Position the widget using Omarchy's bar controls. In bar mode the widget must be included in the bar layout; it hides on vertical bars. To stop the plugin, run `omarchy plugin disable io.github.wawii16.omarchy-lyrics`; this changes shell configuration. Remove the plugin directory only if it is this plugin. There is no Quit action that would terminate the entire Omarchy shell.

## Controls

Use the **Omarchy Lyrics** system-tray menu to switch between overlay and bar, show or hide lyrics in either mode, or edit/lock the overlay position. Editing switches to and shows the overlay; drag the card, then select edit/lock again. The normal overlay is click-through. The tray menu uses toggle labels rather than showing current state. Select overlay mode to show the overlay again; changing to bar preserves the current visibility setting.

Alternatively, run against the active Omarchy shell:

```sh
omarchy-shell omarchyLyrics status
omarchy-shell omarchyLyrics setMode overlay
omarchy-shell omarchyLyrics setMode bar
omarchy-shell omarchyLyrics toggle     # show/hide lyrics for this session
omarchy-shell omarchyLyrics edit       # show overlay and unlock dragging
omarchy-shell omarchyLyrics edit       # lock and save position
```

The shell's `summon`/`hide` methods also open/close the overlay. Position and display mode persist in `$XDG_CONFIG_HOME/adam-lyrics/plugin-preferences.json` (default `~/.config/adam-lyrics/plugin-preferences.json`); visibility and edit mode are session-only. The service owns both worker and tray and stops them on unload.

## Storefront and state

The backend uses `--storefront`, then `ADAM_LYRICS_STOREFRONT`, then `storefront` in `$XDG_CONFIG_HOME/adam-lyrics/config.json`, then `us`. Set the environment variable in the shell's environment or create your own config, for example `{"storefront":"us"}`. Choose the storefront appropriate to your account. No credentials are stored. A missing lyric may be storefront-specific. The loopback Adam engine uses a self-signed TLS certificate, so certificate verification is disabled for that endpoint only.

Runtime state is separate from the old companion: `$XDG_RUNTIME_DIR/adam-lyrics-plugin-state.json`; `ADAM_LYRICS_PLUGIN_STATE` overrides it. Files older than 10 seconds are treated as stale. The service supervises the backend and retries a failed worker after three seconds. The backend reads Adam MPRIS track and position and fetches line-timed TTML. VLC timing is disabled by default because the VLC endpoint does not identify its track; MPRIS can lag or freeze on some Adam versions. The standalone backend supports `--unsafe-vlc-clock` as an explicit opt-in to duration-only matching, which can select another track's clock; the plugin service does not pass this flag. Missing lyrics show a five-second notice. Paused lines remain visible; stopped or empty lines are hidden. When Adam reports `Stopped` for both playback and pause, the backend cannot reliably distinguish pause from stop.

## Validation

```sh
python3 -m unittest -v test_backend
python3 -m unittest discover -s tests -v
dbus-run-session -- python3 tests/smoke.py
dbus-run-session -- /usr/bin/python3 tests/tray_integration.py
```

The smoke test uses a temporary HOME/config/plugin copy, mock backend and isolated state. It launches a separate Quickshell instance on the current Wayland compositor but keeps its overlay hidden. It validates the installed Omarchy registry's manifest parser, actual QML component loading, service data, widget bindings, IPC, preferences, and worker/tray shutdown on service unload while the test host continues. The tray integration test uses a private D-Bus StatusNotifier watcher, actual indicator and DBusMenu events to exercise the QML service controls. Neither installs or enables the plugin or alters the running Omarchy shell. They need a live Wayland session and local Omarchy QML libraries; the backend is mocked.

The full Omarchy host enable/disable lifecycle, visible tray rendering and physical clicking, physical drag, real bar rendering, multi-monitor placement, special-workspace/fullscreen behavior, and a live Adam end-to-end session have not been verified in this isolated build. The overlay targets Quickshell's default screen and uses the original fullscreen-detection logic. MPRIS or Adam API differences, unavailable TTML, or a mismatched storefront can prevent lyrics from appearing.
