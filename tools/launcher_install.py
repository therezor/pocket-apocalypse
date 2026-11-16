#!/usr/bin/env python3
"""Install build/twilight_warrior.bin through M5Launcher over USB, keeping
Launcher on the device. Wraps Launcher's own tools/serial_flasher.py with two
changes for the Cardputer's USB-Serial/JTAG port:

  - reset with esptool's watchdog reset: the RTS "hard reset" leaves the
    ESP32-S3 in download mode instead of booting Launcher;
  - open the port without asserting DTR/RTS, which would do the same.

usage: tools/launcher_install.py [--name "D4V Scythe"] [--replace twilig]
                                 [--port /dev/cu.usbmodemXXXX] [--launcher ../Launcher]
  --replace LABEL  delete that app partition first (frees its space; the
                   label is what Launcher printed, e.g. "label=twilig")

Launcher only shows up on a real power-on: once an app is installed, a USB
or software reset boots straight into the app. The script then waits (up to
--wait seconds) for you to switch the Cardputer off and on.
"""
import argparse
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('--port', default=(glob.glob('/dev/cu.usbmodem*') or [None])[0],
                help='serial port (default: first /dev/cu.usbmodem*, waited for)')
ap.add_argument('--launcher', default=os.path.join(ROOT, '..', 'Launcher'))
ap.add_argument('--file', default=os.path.join(ROOT, 'build', 'twilight_warrior.bin'))
ap.add_argument('--name', default='Doom', help='app name shown in Launcher (no spaces: the console splits on them)')
ap.add_argument('--replace', help='app partition label to delete before installing')
ap.add_argument('--wait', type=float, default=120, help='seconds to wait for Launcher after a power cycle')
args = ap.parse_args()
args.name = args.name.replace(' ', '_')
power_cycled = False
if not args.port:
    # The game turns USB serial off; after a power cycle Launcher brings it back.
    power_cycled = True
    print('[*] No Cardputer serial port: switch the Cardputer OFF and ON (waiting %ds)...' % args.wait)
    deadline = time.time() + args.wait
    while not glob.glob('/dev/cu.usbmodem*') and time.time() < deadline:
        time.sleep(0.2)
    args.port = (glob.glob('/dev/cu.usbmodem*') or [None])[0]
    if not args.port:
        sys.exit('No /dev/cu.usbmodem* port: is the Cardputer connected?')

if not args.port:
    sys.exit('No /dev/cu.usbmodem* port: is the Cardputer connected?')

sys.path.insert(0, os.path.join(args.launcher, 'tools'))
import serial  # noqa: E402
import serial_flasher as sf  # noqa: E402


def reset_board(port):
    print('[*] Resetting board on %s (watchdog reset)...' % port)
    subprocess.run([sys.executable, '-m', 'esptool', '--port', port, '--after', 'watchdog_reset', 'chip_id'],
                   check=True, capture_output=True, text=True)
    time.sleep(0.5)
    print('[*] If an app boots instead of Launcher: switch the Cardputer OFF and ON now.')


def open_serial(port, baud, delay=0.25):
    # A power cycle drops the USB port for as long as the switch is off:
    # keep retrying for the whole --wait time, not a few seconds.
    last = None
    deadline = time.time() + args.wait
    while time.time() < deadline:
        try:
            s = serial.Serial()
            s.port = (glob.glob('/dev/cu.usbmodem*') or [port])[0]
            s.baudrate = baud
            s.timeout = 0.2
            s.dtr = False
            s.rts = False
            s.open()
            return s
        except serial.SerialException as exc:
            last = exc
            time.sleep(delay)
    sys.exit('Could not open %s: %s' % (port, last))


# Right after a power cycle Launcher is already on its boot screen; a reset
# now would boot straight past it into the installed app.
sf.reset_board = (lambda port: None) if power_cycled else reset_board
sf.open_serial = open_serial

if args.replace:
    # Boot into Launcher's menu and delete the old slot over its console.
    reset_board(args.port)
    with open_serial(args.port, 115200) as ser:
        reader = sf.LineReader(ser, args.port, 115200)
        if reader.wait_for_line(lambda l: sf.BOOT_BANNER in l, args.wait, echo=False) is None:
            sys.exit('Timed out waiting for the Launcher boot banner.')
        sf.send_command(reader.ser, 'nav SelPress')
        time.sleep(0.5)
        sf.send_command(reader.ser, 'partition delete %s' % args.replace)
        reply = reader.wait_for_line(lambda l: l.startswith('OK partition') or l.startswith('ERR'), 10.0)
        print('[*] delete %s: %s' % (args.replace, reply))

sys.argv = ['serial_flasher.py', '-f', args.file, '-p', args.port, '-n', args.name, '--overwrite',
            '--boot-timeout', str(args.wait)]
sf.main()
