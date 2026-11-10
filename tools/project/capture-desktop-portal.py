#!/usr/bin/env python3
"""Request a screenshot through the user's GNOME portal; respect its response.

Run as the logged-in desktop user with that user's session bus. The portal may
ask the owner to share the screenshot. No Shell unsafe mode or access bypass is
used. The report contains only the portal result and resulting screenshot URI.
"""
import argparse
import json
from pathlib import Path
import secrets
import sys
import gi

gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--timeout-seconds', type=int, default=180)
    args = parser.parse_args()
    if not 30 <= args.timeout_seconds <= 900:
        parser.error('Timeout must be 30..900 seconds')
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    loop = GLib.MainLoop()
    token = 'j716f_' + secrets.token_hex(8)
    sender = bus.get_unique_name().lstrip(':').replace('.', '_')
    request = '/org/freedesktop/portal/desktop/request/' + sender + '/' + token
    state = {'result': None}

    def finish(result):
        state['result'] = result
        args.report.write_text(json.dumps(result) + '\n')
        print(json.dumps(result), flush=True)
        loop.quit()

    def response(connection, sender_name, path, interface, signal, parameters, user_data):
        code, result = parameters.unpack()
        finish({'response': code, 'uri': result.get('uri'), 'request': request})

    subscription = bus.signal_subscribe('org.freedesktop.portal.Desktop',
                                        'org.freedesktop.portal.Request', 'Response',
                                        request, None, Gio.DBusSignalFlags.NONE, response, None)
    options = {'handle_token': GLib.Variant('s', token),
               'interactive': GLib.Variant('b', False)}
    returned = bus.call_sync('org.freedesktop.portal.Desktop', '/org/freedesktop/portal/desktop',
                             'org.freedesktop.portal.Screenshot', 'Screenshot',
                             GLib.Variant('(sa{sv})', ('', options)), GLib.VariantType.new('(o)'),
                             Gio.DBusCallFlags.NONE, 15000, None).unpack()[0]
    if returned != request:
        raise RuntimeError('Unexpected portal request identity')
    print('Screenshot portal request opened', flush=True)

    def timeout():
        if state['result'] is None:
            try:
                bus.call_sync('org.freedesktop.portal.Desktop', request,
                              'org.freedesktop.portal.Request', 'Close', None, None,
                              Gio.DBusCallFlags.NONE, 5000, None)
            except GLib.Error as error:
                print('Portal cancellation: ' + str(error), file=sys.stderr, flush=True)
            finish({'response': 3, 'error': 'Screenshot portal request timed out'})
        return False

    GLib.timeout_add_seconds(args.timeout_seconds, timeout)
    if state['result'] is None:
        loop.run()
    bus.signal_unsubscribe(subscription)
    return 0 if state['result']['response'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
