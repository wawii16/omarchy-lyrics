#!/usr/bin/python3
"""StatusNotifier menu; commands travel only to the owning QML service."""
import signal
import sys

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AyatanaAppIndicator3', '0.1')
from gi.repository import Gtk, GLib, AyatanaAppIndicator3 as AppIndicator


def main():
    indicator = AppIndicator.Indicator.new('omarchy-lyrics', 'audio-x-generic',
                                           AppIndicator.IndicatorCategory.APPLICATION_STATUS)
    indicator.set_title('Omarchy Lyrics')
    menu = Gtk.Menu()
    for label, command in (
        ('Show / hide lyrics', 'toggle'),
        ('Overlay mode', 'overlay'),
        ('Bar mode', 'bar'),
        ('Edit / lock overlay position', 'edit'),
    ):
        item = Gtk.MenuItem(label=label)
        item.connect('activate', lambda _item, value=command: print(value, flush=True))
        menu.append(item)
    menu.show_all()
    indicator.set_menu(menu)
    indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM,
                         lambda: (Gtk.main_quit(), False)[1])
    try:
        Gtk.main()
    except BrokenPipeError:
        return 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
