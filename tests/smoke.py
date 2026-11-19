#!/usr/bin/env python3
"""Run plugin components in a disposable Quickshell host and mock Adam backend."""
import json, os, shutil, subprocess, tempfile, time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='adam-plugin-smoke-') as d:
    d = Path(d)
    plug = d / 'plugin'
    plug.mkdir()
    for name in ('Service.qml', 'Overlay.qml', 'BarWidget.qml', 'manifest.json', 'tray.py'):
        shutil.copy(root / name, plug / name)
    (plug / 'backend.py').write_text('''import json,os,sys,time
open(os.environ["TEST_PID"],"w").write(str(os.getpid()))
p=sys.argv[sys.argv.index("--state")+1]
while True:
 t=p+".tmp"
 with open(t,"w") as f: json.dump(dict(text="fixture line",playback="Playing",unavailable=False,track="fixture",updated=time.time()),f)
 os.replace(t,p)
 time.sleep(.2)
''')
    for name in ('Commons', 'Ui', 'services'):
        (d / name).symlink_to(Path('/usr/share/omarchy/shell') / name, target_is_directory=True)
    (d / 'shell.qml').write_text('''import QtQuick
import Quickshell
import "plugin" as Plugin
import qs.services as Services
ShellRoot {
  id: root
  property var svc: loader.item
  Loader { id: loader; source: "plugin/Service.qml"; onLoaded: item.userVisible = false }
  Plugin.Overlay { id: overlay; service: root.svc }
  Plugin.BarWidget { id: widget; bar: fakeBar }
  Services.PluginRegistry { id: registry }
  QtObject { id: fakeShell; function serviceFor(id) { return svc } }
  QtObject { id: fakeBar; property var shell: fakeShell; property bool vertical: false; property int barSize: 30; property color barForeground: "white"; property string fontFamily: "sans" }
  Timer { interval: 3500; running: true; onTriggered: {
    let m = JSON.parse(manifestFile.text())
    if (!registry.validateManifest(m, "test") || svc.lyric !== "fixture line" || !svc.hasContent || overlay.displayed) { console.log("SMOKE_FAIL",svc.lyric,svc.hasContent); Qt.quit(); return }
    svc.setMode("bar"); svc.userVisible = true
    if (!widget.showLyric || widget.implicitWidth <= 0 || overlay.displayed) { console.log("SMOKE_FAIL bar",widget.showLyric,widget.implicitWidth,overlay.displayed); Qt.quit(); return }
    svc.edit(); svc.userVisible = false
    if (!svc.editMode || widget.showLyric || overlay.displayed) { console.log("SMOKE_FAIL edit"); Qt.quit(); return }
    svc.edit(); svc.userVisible = false
    if (overlay.displayed) { console.log("SMOKE_FAIL toggle"); Qt.quit(); return }
    console.log("SMOKE_PASS manifest service overlay bar IPC-controls"); loader.active = false; finish.start()
  } }
  Timer { id: finish; interval: 2000; onTriggered: Qt.quit() }
  FileView { id: manifestFile; path: Quickshell.env("TEST_MANIFEST") }
}
'''.replace('import Quickshell\n', 'import Quickshell\nimport Quickshell.Io\n'))
    env = dict(os.environ, HOME=str(d), XDG_CONFIG_HOME=str(d / 'config'),
               ADAM_LYRICS_PLUGIN_STATE=str(d / 'state.json'), QML_IMPORT_PATH=str(d),
               QT_QPA_PLATFORM='wayland', TEST_PID=str(d / 'pid'), TEST_MANIFEST=str(plug / 'manifest.json'))
    proc = subprocess.Popen(['quickshell', '-p', str(d / 'shell.qml')], env=env,
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        def ipc(method, *args):
            return subprocess.run(['quickshell', 'ipc', '-p', str(d / 'shell.qml'),
                                   'call', 'omarchyLyrics', method, *args], env=env,
                                  capture_output=True, text=True, timeout=2)
        for _ in range(20):
            call = ipc('status')
            if call.returncode == 0:
                break
            time.sleep(.1)
        else:
            raise AssertionError('IPC target not available')
        assert json.loads(call.stdout)['mode'] == 'overlay'
        assert ipc('setMode', 'bar').stdout.strip() == 'ok'
        assert ipc('setMode', 'other').stdout.strip() == 'invalid mode'
        for _ in range(30):
            if (d / 'pid').exists():
                break
            time.sleep(.1)
        pid = int((d / 'pid').read_text())
        def tray_pid():
            children = Path(f'/proc/{proc.pid}/task/{proc.pid}/children').read_text().split()
            for child in children:
                try:
                    if b'tray.py' in Path(f'/proc/{child}/cmdline').read_bytes():
                        return int(child)
                except FileNotFoundError:
                    continue
            return None
        tray = tray_pid()
        assert tray, 'tray process did not start'
        deadline = time.monotonic() + 5
        while (Path(f'/proc/{pid}').exists() or Path(f'/proc/{tray}').exists()) and time.monotonic() < deadline and proc.poll() is None:
            time.sleep(.1)
        assert proc.poll() is None, 'host exited before service unload check'
        assert not Path(f'/proc/{pid}').exists(), 'worker survived service unload'
        assert not Path(f'/proc/{tray}').exists(), 'tray survived service unload'
        output = proc.communicate(timeout=10)[0]
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    print(output)
    if proc.returncode or 'SMOKE_PASS' not in output or 'SMOKE_FAIL' in output:
        raise SystemExit('smoke test failed')
    prefs = d / 'config/adam-lyrics/plugin-preferences.json'
    assert json.loads(prefs.read_text())['mode'] == 'overlay', 'preferences not persisted'
    pid = int((d / 'pid').read_text())
    for _ in range(30):
        if not Path(f'/proc/{pid}').exists():
            break
        time.sleep(.1)
    else:
        raise SystemExit('worker survived shell termination')
    print('PASS preferences persisted; worker and tray stopped on service unload while host remained running')
