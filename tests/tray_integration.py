#!/usr/bin/python3
"""Exercise real StatusNotifier menu -> QML controls on a private D-Bus session.

Run with: dbus-run-session -- /usr/bin/python3 tests/tray_integration.py
Requires a Wayland session, GTK3 and Ayatana AppIndicator.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import gi
from gi.repository import Gio, GLib

ROOT = Path(__file__).resolve().parents[1]
WATCHER_XML = '''<node><interface name="org.kde.StatusNotifierWatcher">
<method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
<method name="RegisterStatusNotifierHost"><arg type="s" direction="in"/></method>
<property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
<property name="RegisteredStatusNotifierItems" type="as" access="read"/>
<property name="ProtocolVersion" type="i" access="read"/>
</interface></node>'''


def watcher(filename):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    Gio.bus_own_name_on_connection(bus, 'org.kde.StatusNotifierWatcher', Gio.BusNameOwnerFlags.NONE, None, None)
    info = Gio.DBusNodeInfo.new_for_xml(WATCHER_XML).interfaces[0]
    def method(_conn, sender, _path, _iface, name, params, invocation):
        if name == 'RegisterStatusNotifierItem':
            item = params.unpack()[0]
            Path(filename).write_text(json.dumps([sender if item.startswith('/') else item,
                                                  item if item.startswith('/') else '/StatusNotifierItem']))
        invocation.return_value(None)
    def prop(_conn, _sender, _path, _iface, name):
        return {'IsStatusNotifierHostRegistered': GLib.Variant('b', True),
                'RegisteredStatusNotifierItems': GLib.Variant('as', []),
                'ProtocolVersion': GLib.Variant('i', 0)}[name]
    bus.register_object('/StatusNotifierWatcher', info, method, prop, None)
    print('READY', flush=True)
    GLib.MainLoop().run()


def wait_for(fn, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            value = fn()
            if value:
                return value
        except (OSError, ValueError, subprocess.CalledProcessError):
            pass
        time.sleep(.1)
    raise AssertionError('timed out waiting for test condition')


def main():
    if len(sys.argv) > 1:
        watcher(sys.argv[1]); return
    with tempfile.TemporaryDirectory(prefix='omarchy-lyrics-tray-test-') as tmp:
        tmp = Path(tmp)
        registered = tmp / 'registered'
        watch = subprocess.Popen([sys.executable, __file__, str(registered)], stdout=subprocess.PIPE, text=True)
        host = None
        try:
            assert watch.stdout.readline().strip() == 'READY'
            # Isolate both configuration and backend state from the user's installation.
            env = dict(os.environ, HOME=str(tmp), XDG_CONFIG_HOME=str(tmp / 'config'),
                       ADAM_LYRICS_PLUGIN_STATE=str(tmp / 'state.json'), QT_QPA_PLATFORM='wayland')
            # A copied service points at a harmless backend, not the real Adam session.
            service = (ROOT / 'Service.qml').read_text()
            (tmp / 'Service.qml').write_text(service)
            (tmp / 'tray.py').write_text((ROOT / 'tray.py').read_text())
            (tmp / 'backend.py').write_text('import time\ntime.sleep(60)\n')
            (tmp / 'shell.qml').write_text('import QtQuick\nimport Quickshell\nShellRoot { Loader { source: "Service.qml" } }\n')
            host = subprocess.Popen(['quickshell', '-p', str(tmp / 'shell.qml')], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            busname, itempath = wait_for(lambda: json.loads(registered.read_text()))
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            def dbus(path, iface, method, args, signature):
                return bus.call_sync(busname, path, iface, method, args,
                                     GLib.VariantType.new(signature), Gio.DBusCallFlags.NONE, 3000, None).unpack()
            menu = dbus(itempath, 'org.freedesktop.DBus.Properties', 'Get',
                        GLib.Variant('(ss)', ('org.kde.StatusNotifierItem', 'Menu')), '(v)')[0]
            layout = dbus(menu, 'com.canonical.dbusmenu', 'GetLayout',
                          GLib.Variant('(iias)', (0, -1, [])), '(u(ia{sv}av))')[1]
            entries = {child[1].get('label'): child[0] for child in layout[2]}
            expected = {'Show / hide lyrics', 'Overlay mode', 'Bar mode', 'Edit / lock overlay position'}
            assert set(entries) == expected, entries
            def ipc():
                result = subprocess.run(['quickshell', 'ipc', '-p', str(tmp / 'shell.qml'), 'call',
                                         'omarchyLyrics', 'status'], env=env, capture_output=True, text=True, check=True)
                return json.loads(result.stdout)
            wait_for(ipc)
            def click(label):
                dbus(menu, 'com.canonical.dbusmenu', 'Event',
                     GLib.Variant('(isvu)', (entries[label], 'clicked', GLib.Variant('i', 0), 0)), '()')
            click('Bar mode'); wait_for(lambda: ipc()['mode'] == 'bar')
            click('Show / hide lyrics'); wait_for(lambda: not ipc()['visible'])
            click('Edit / lock overlay position'); wait_for(lambda: ipc()['mode'] == 'overlay' and ipc()['edit'] and ipc()['visible'])
            click('Edit / lock overlay position'); wait_for(lambda: not ipc()['edit'])
            click('Overlay mode'); wait_for(lambda: ipc()['mode'] == 'overlay')
            print('PASS private watcher registration, real DBus menu actions -> QML state')
        finally:
            if host:
                host.terminate(); host.wait(timeout=5)
            watch.terminate(); watch.wait(timeout=5)


if __name__ == '__main__':
    main()
