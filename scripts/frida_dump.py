"""
Frida host script for Cocos2d-JS script dump

Usage:
    python frida_dump.py <package_name>
    python frida_dump.py spawn <package_name>
    python frida_dump.py <process_name>
    python frida_dump.py -l    # list running apps
"""

import frida
import sys
import os
import json
import time
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
OUTPUT_DIR = os.path.join(PROJECT_DIR, 'dumped_scripts')
os.makedirs(OUTPUT_DIR, exist_ok=True)


def on_message(message, data):
    if message['type'] == 'send':
        payload = message['payload']
        if isinstance(payload, str):
            print(f'[MSG] {payload}')
            return

        msg_type = payload.get('type', '')

        if msg_type == 'script':
            filename = payload.get('filename', 'unknown.js')
            content = payload.get('content', '')
            filepath = os.path.join(OUTPUT_DIR, filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8', errors='replace') as f:
                f.write(content)
            print(f'[DUMP] Script: {filepath} ({payload.get("size", 0)} bytes)')

        elif msg_type == 'xxtea_key':
            key = payload.get('key', '')
            filepath = os.path.join(OUTPUT_DIR, 'xxtea_key.txt')
            with open(filepath, 'w') as f:
                f.write(key)
            print(f'[KEY] XXTEA Key: {key} -> {filepath}')

        elif msg_type == 'xxtea_decrypted':
            data_bytes = bytes(payload.get('data', []))
            filepath = os.path.join(OUTPUT_DIR,
                                    f'xxtea_dec_{int(time.time())}.bin')
            with open(filepath, 'wb') as f:
                f.write(data_bytes)
            print(f'[DECRYPT] Data: {filepath} ({payload.get("size", 0)} bytes)')

        elif msg_type == 'file_data':
            filename = payload.get('filename', 'unknown')
            data_bytes = bytes(payload.get('data', []))
            filepath = os.path.join(OUTPUT_DIR, 'assets', filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'wb') as f:
                f.write(data_bytes)
            print(f'[FILE] Asset: {filepath} ({payload.get("size", 0)} bytes)')

        elif msg_type == 'log':
            print(f'[LOG] {payload.get("text", "")}')

    elif message['type'] == 'error':
        desc = message.get('description', '')
        stack = message.get('stack', '')
        print(f'[ERROR] {desc}')
        if stack:
            for line in stack.split('\n')[:5]:
                print(f'  {line}')


def list_apps():
    try:
        device = frida.get_usb_device()
        apps = device.enumerate_applications()
        print(f'{"PID":>8}  {"Identifier":<40}  Name')
        print('-' * 80)
        for app in sorted(apps, key=lambda x: x.name.lower()):
            print(f'{app.pid:>8}  {app.identifier:<40}  {app.name}')
    except Exception as e:
        print(f'Error: {e}')
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description='Frida-based Cocos2d-JS script dumper')
    parser.add_argument('target', nargs='?', help='Package/process name')
    parser.add_argument('-l', '--list', action='store_true',
                        help='List running apps')
    parser.add_argument('--spawn', action='store_true',
                        help='Spawn the app instead of attaching')

    args = parser.parse_args()

    if args.list:
        list_apps()
        return

    if not args.target:
        parser.print_help()
        sys.exit(1)

    # Load Frida hook JS
    hook_path = os.path.join(PROJECT_DIR, 'frida_hook.js')
    if not os.path.exists(hook_path):
        hook_path = os.path.join(SCRIPT_DIR, '..', 'frida_hook.js')

    with open(hook_path, 'r') as f:
        jscode = f.read()

    try:
        device = frida.get_usb_device()

        if args.spawn:
            pid = device.spawn([args.target])
            session = device.attach(pid)
            device.resume(pid)
            print(f'[+] Spawned: {args.target} (PID: {pid})')
            time.sleep(2)
        else:
            session = device.attach(args.target)
            print(f'[+] Attached to: {args.target}')

        script = session.create_script(jscode)
        script.on('message', on_message)
        script.load()

        print(f'[+] Hook loaded successfully')
        print(f'[+] Output directory: {OUTPUT_DIR}')
        print('[+] Waiting for scripts... (Ctrl+C to stop)')

        # Keep alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print('\n[+] Stopped by user')

    except frida.ProcessNotFoundError:
        print(f'[-] Process not found: {args.target}')
        print('    Use -l to list running apps')
        sys.exit(1)
    except frida.ServerNotStartedError:
        print('[-] frida-server is not running')
        print('    Run: adb shell su -c /data/local/tmp/frida-server &')
        sys.exit(1)


if __name__ == '__main__':
    main()
