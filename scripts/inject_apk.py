"""
Automatically inject Dobby hook .so into an APK

Usage:
    python inject_apk.py game.apk [--hook hook.so] [--output modified.apk]

Requires:
    - apktool (in PATH)
    - jarsigner (from JDK)
    - zipalign (from Android SDK)
"""

import os
import sys
import shutil
import subprocess
import tempfile
import zipfile
import argparse
import struct
import hashlib


def check_tool(name):
    """Check if a tool is available"""
    path = shutil.which(name)
    if path:
        print(f'[+] Found {name}: {path}')
        return True
    print(f'[-] {name} not found in PATH')
    return False


def get_abi_dirs(apk_path):
    """Get available ABI directories from the APK"""
    abis = []
    with zipfile.ZipFile(apk_path, 'r') as z:
        for entry in z.namelist():
            if entry.startswith('lib/') and entry.count('/') >= 2:
                parts = entry.split('/')
                abi = parts[1]
                if abi not in abis:
                    abis.append(abi)
    return abis


def find_hook_so(hook_path, target_abi):
    """Find the right .so for the target ABI, or any compatible one"""
    if not os.path.isdir(hook_path):
        if os.path.isfile(hook_path):
            return hook_path
        return None

    name_variants = [
        f'libcocos2djs_hook.so',
        f'libcocos2djs_hook_{target_abi}.so',
        f'libcocos2djs_hook.so',
    ]

    for name in name_variants:
        candidate = os.path.join(hook_path, name)
        if os.path.exists(candidate):
            return candidate

    # Try ABI-specific subdirectories
    for sub in [target_abi, 'arm64-v8a', 'armeabi-v7a', 'x86_64', 'x86']:
        candidate = os.path.join(hook_path, sub, 'libcocos2djs_hook.so')
        if os.path.exists(candidate):
            return candidate

    return None


def patch_so_for_preload(so_path):
    """
    Modify .so to add explicit dependency on libcocos2djs_hook.so.
    Alternative: use LD_PRELOAD trick via modified wrapper script.
    """
    # This is a no-op - we'll use the smali injection method instead
    return True


def add_load_library_smali(extracted_dir, package_name):
    """
    Add System.loadLibrary to the main activity's smali
    so our hook .so is loaded early.
    """
    import re

    # Find the main activity smali
    manifest_path = os.path.join(extracted_dir, 'AndroidManifest.xml')
    if not os.path.exists(manifest_path):
        print(f'[-] AndroidManifest.xml not found')
        return False

    # Try to find launcher activity from AndroidManifest.xml
    package = None
    with open(manifest_path, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
        # Extract package name
        m = re.search(r'package="([^"]+)"', content)
        if m:
            package = m.group(1).replace('.', '/')

    if not package:
        package = package_name.replace('.', '/')

    # Search for main activity smali
    smali_dir = os.path.join(extracted_dir, 'smali')
    if not os.path.exists(smali_dir):
        smali_dir = os.path.join(extracted_dir, 'smali_classes2')
        if not os.path.exists(smali_dir):
            print('[-] No smali directory found')
            return False

    # Find the Application or main Activity's smali
    target_smali = None
    for root, dirs, files in os.walk(smali_dir):
        for f in files:
            if f.endswith('.smali') and 'Application' in f and '\\' not in f:
                # Found Application class
                path = os.path.join(root, f)
                with open(path, 'r', encoding='utf-8', errors='replace') as sf:
                    if '.super' in sf.read() and 'Application' in sf.read():
                        target_smali = path
                        break
        if target_smali:
            break

    if not target_smali:
        # Try to find any smali that extends Application
        for root, dirs, files in os.walk(smali_dir):
            for f in files:
                if f.endswith('.smali'):
                    path = os.path.join(root, f)
                    with open(path, 'r', encoding='utf-8', errors='replace') as sf:
                        content = sf.read()
                        if 'Landroid/app/Application' in content:
                            target_smali = path
                            break
            if target_smali:
                break

    if not target_smali:
        print('[-] Could not find Application smali class')
        return False

    print(f'[+] Found Application smali: {target_smali}')

    # Read and check if loadLibrary is already there
    with open(target_smali, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()

    if 'cocos2djs_hook' in content:
        print('[+] Hook library already referenced in smali')
        return True

    # Add loadLibrary call in the static initializer or onCreate
    # Find the right place to insert
    lines = content.split('\n')
    insert_pos = -1

    for i, line in enumerate(lines):
        # Insert in <clinit> or after constructor
        if '.method static constructor <clinit>()V' in line:
            insert_pos = i + 1
            break
        if '.method public constructor <init>()V' in line:
            insert_pos = i
            break

    if insert_pos == -1:
        print('[-] Could not find insertion point in smali')
        return False

    # Insert the loadLibrary call
    lib_load = [
        '',
        '    const-string v0, "cocos2djs_hook"',
        '',
        '    invoke-static {v0}, Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V',
        '',
    ]

    for l in reversed(lib_load):
        lines.insert(insert_pos, l)

    with open(target_smali, 'wb') as f:
        f.write('\n'.join(lines).encode('utf-8'))

    print(f'[+] Added System.loadLibrary("cocos2djs_hook") to smali')
    return True


def inject_hook(apk_path, hook_so_path, output_path, package_name=None):
    """
    Main injection routine
    """
    temp_dir = tempfile.mkdtemp(prefix='apk_inject_')
    extracted_dir = os.path.join(temp_dir, 'extracted')

    try:
        # Step 1: Decompile APK
        print(f'\n[1/6] Decompiling APK with apktool...')
        result = subprocess.run(
            ['apktool', 'd', '-f', '-o', extracted_dir, apk_path],
            capture_output=True, text=True)
        if result.returncode != 0:
            print(f'[-] apktool failed: {result.stderr}')
            return False
        print('[+] Decompiled successfully')

        # Step 2: Check available ABIs
        print(f'\n[2/6] Analyzing APK architecture...')
        apk_abis = get_abi_dirs(apk_path)
        print(f'    Found ABIs: {apk_abis}')

        if not apk_abis:
            print('[-] No native libraries found in APK')
            return False

        # Step 3: Copy hook .so for each ABI
        print(f'\n[3/6] Copying hook library...')
        copied = False
        for abi in apk_abis:
            lib_dir = os.path.join(extracted_dir, 'lib', abi)
            os.makedirs(lib_dir, exist_ok=True)

            hook_file = find_hook_so(hook_so_path, abi)
            if hook_file:
                dest = os.path.join(lib_dir, 'libcocos2djs_hook.so')
                shutil.copy2(hook_file, dest)
                print(f'    [+] Copied to lib/{abi}/libcocos2djs_hook.so')
                copied = True
            else:
                print(f'    [-] No compatible hook for {abi}, skipping')

        if not copied:
            print('[-] Could not copy hook library for any ABI')
            return False

        # Step 4: Patch smali to load our library
        print(f'\n[4/6] Patching smali to load hook...')
        if package_name:
            add_load_library_smali(extracted_dir, package_name)
        else:
            # Try to auto-detect package from AndroidManifest
            manifest = os.path.join(extracted_dir, 'AndroidManifest.xml')
            if os.path.exists(manifest):
                import re
                with open(manifest, 'r', encoding='utf-8',
                          errors='replace') as f:
                    content = f.read()
                    m = re.search(r'package="([^"]+)"', content)
                    if m:
                        add_load_library_smali(extracted_dir, m.group(1))
                    else:
                        add_load_library_smali(extracted_dir, 'com.game.app')
            else:
                add_load_library_smali(extracted_dir, 'com.game.app')

        # Step 5: Rebuild APK
        print(f'\n[5/6] Rebuilding APK...')
        result = subprocess.run(
            ['apktool', 'b', '-o', output_path, extracted_dir],
            capture_output=True, text=True)
        if result.returncode != 0:
            print(f'[-] Rebuild failed: {result.stderr}')
            return False
        print(f'[+] Rebuilt: {output_path}')

        # Step 6: Sign APK
        print(f'\n[6/6] Signing APK...')
        keystore = os.path.expanduser('~/.android/debug.keystore')
        if os.path.exists(keystore):
            result = subprocess.run([
                'apksigner', 'sign', '--ks', keystore,
                '--ks-pass', 'pass:android', output_path
            ], capture_output=True, text=True)
            if result.returncode == 0:
                print('[+] Signed with debug keystore')
            else:
                print(f'[!] Signing issue: {result.stderr}')
                print('    Try: jarsigner -keystore debug.keystore '
                      f'-storepass android {output_path} androiddebugkey')
        else:
            print('[!] No debug keystore found. Sign manually:')
            print(f'    jarsigner -keystore my.keystore {output_path} alias')

        print(f'\n[+] Done! Modified APK: {output_path}')
        print(f'    Install: adb install {output_path}')
        return True

    finally:
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(
        description='Inject Dobby hook .so into Android APK')
    parser.add_argument('apk', help='Path to APK file')
    parser.add_argument('--hook', '-k', default='./build',
                        help='Path to libcocos2djs_hook.so or build dir')
    parser.add_argument('--output', '-o', default=None,
                        help='Output APK path')
    parser.add_argument('--package', '-p', default=None,
                        help='Package name (for smali patching)')

    args = parser.parse_args()

    if not os.path.exists(args.apk):
        print(f'[-] APK not found: {args.apk}')
        sys.exit(1)

    hook_path = args.hook
    if not os.path.exists(hook_path):
        print(f'[-] Hook .so not found: {hook_path}')
        print('    Build first with: ./build.sh')
        sys.exit(1)

    output = args.output or os.path.splitext(args.apk)[0] + '_hooked.apk'

    # Check required tools
    print('=== Checking tools ===')
    tools_ok = all([
        check_tool('apktool'),
    ])

    if not tools_ok:
        print('\n[-] Missing required tools. Install:')
        print('    apktool: https://ibotpeaches.github.io/Apktool/')
        sys.exit(1)

    print(f'\nAPK: {args.apk}')
    print(f'Hook: {hook_path}')
    print(f'Output: {output}')
    print()

    inject_hook(args.apk, hook_path, output, args.package)


if __name__ == '__main__':
    main()
