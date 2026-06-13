"""
Pure Python XXTEA Decryptor for Cocos2d-JS .jsc files

Usage:
    python decrypt_jsc.py <encrypted.jsc> [xxtea_key]

If key is omitted, tries common keys and also tries to find key
in the current directory (xxtea_key.txt).
"""

import struct
import sys
import os
import re

DELTA = 0x9E3779B9
MASK32 = 0xFFFFFFFF


def u32(x):
    return x & MASK32


def str_to_key(key):
    """Convert key string to 4-uint32 key array (Cocos2d-JS format)"""
    if isinstance(key, str):
        key = key.encode('utf-8')
    k = [0, 0, 0, 0]
    for i in range(min(len(key), 16)):
        k[i >> 2] |= key[i] << ((i & 3) * 8)
    return [u32(x) for x in k]


def xxtea_decrypt(data, key):
    """
    Decrypt XXTEA-encrypted data.
    Cocos2d-JS format: first uint32 = total number of uint32 values
    """
    if len(data) < 8:
        return None

    k = str_to_key(key)

    # Parse the uint32 array
    first_u32 = struct.unpack('<I', data[:4])[0]

    if 2 <= first_u32 <= 4 * 1024 * 1024:
        # First uint32 is count
        expected = first_u32 * 4
        if expected <= len(data):
            v = list(struct.unpack('<' + 'I' * first_u32, data[:expected]))
        else:
            v = list(struct.unpack('<' + 'I' * (len(data) // 4),
                                   data[:(len(data) // 4) * 4]))
    else:
        # No header - entire data is uint32 array
        v = list(struct.unpack('<' + 'I' * (len(data) // 4),
                               data[:(len(data) // 4) * 4]))

    n = len(v)
    if n < 2:
        return None

    # XXTEA decrypt
    y = v[0]
    q = 6 + 52 // n
    s = u32(q * DELTA)

    iterations = 0
    while s != 0:
        iterations += 1
        if iterations > 1000000:
            return None
        e = u32(s >> 2) & 3
        for p in range(n - 1, 0, -1):
            z = v[p - 1]
            mx = ((z >> 5 ^ y << 2) + (y >> 3 ^ z << 4)) ^ \
                 ((s ^ y) + (k[(p & 3) ^ e] ^ z))
            v[p] = u32(v[p] - mx)
            y = v[p]
        z = v[n - 1]
        mx = ((z >> 5 ^ y << 2) + (y >> 3 ^ z << 4)) ^ \
             ((s ^ y) + (k[0 ^ e] ^ z))
        v[0] = u32(v[0] - mx)
        y = v[0]
        s = u32(s - DELTA)

    # Convert back to bytes
    result = bytearray()
    for val in v:
        result.extend(struct.pack('<I', val))

    # Last uint32 often contains original data length
    if len(result) >= 4:
        data_len = struct.unpack('<I', result[-4:])[0]
        if 0 < data_len < len(result):
            result = result[:data_len]
        else:
            result = result.rstrip(b'\x00')

    return bytes(result)


def is_valid_js(data):
    """Check if decrypted data looks like JavaScript"""
    if not data or len(data) < 20:
        return False
    try:
        text = data.decode('utf-8', errors='replace')
    except:
        return False
    printable = sum(1 for c in text if c.isprintable() or c in '\n\r\t')
    if printable / max(len(text), 1) < 0.7:
        return False
    js_keywords = ['function', 'var ', 'const ', 'let ', 'this.',
                   'return', 'if (', 'else', 'for (', 'while',
                   'class ', 'import', 'export', 'module']
    score = sum(2 for w in js_keywords if w in text[:5000].lower())
    return score >= 2


COMMON_KEYS = [
    b'L5OfXzi9IbpZI=8HrYJ',
    b'HHKHDHJF',
    b'oYvELBIB5',
    b'UDZ_D0SXU',
    b'VhwuxE9G',
    b'A_oXRunL',
    b'JeoydboF',
    b'2DF73BBDDB19F0E8',
    b'3A8B422BE7A34D2E',
    b'6ABCDEF012345678',
    b'cocos2d_xxtea_key',
    b'default_xxtea_key',
    b'xxtea_key_123456',
]


def load_key_from_file(path='xxtea_key.txt'):
    if os.path.exists(path):
        with open(path, 'rb') as f:
            key = f.read().strip()
        if key:
            print(f'[+] Loaded key from {path}: {key}')
            return key
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f'[-] File not found: {filepath}')
        sys.exit(1)

    with open(filepath, 'rb') as f:
        data = f.read()

    print(f'File: {filepath} ({len(data)} bytes)')
    print(f'First 16 bytes: {data[:16].hex()}')

    # Collect keys to try
    keys_to_try = []

    # User-provided key
    if len(sys.argv) >= 3:
        keys_to_try.append(sys.argv[2].encode())

    # Key from file
    key_file = load_key_from_file()
    if key_file:
        keys_to_try.append(key_file)
    key_file = load_key_from_file(
        os.path.join(os.path.dirname(filepath), 'xxtea_key.txt'))
    if key_file and key_file not in keys_to_try:
        keys_to_try.append(key_file)

    # Common keys
    for k in COMMON_KEYS:
        if k not in keys_to_try:
            keys_to_try.append(k)

    # Try to find key in current directory
    for f in os.listdir('.'):
        if 'key' in f.lower() and f.endswith('.txt'):
            try:
                with open(f, 'rb') as kf:
                    k = kf.read().strip()
                if k and k not in keys_to_try:
                    keys_to_try.append(k)
                    print(f'[+] Found key file: {f}')
            except:
                pass

    print(f'\nTrying {len(keys_to_try)} keys...\n')

    for key in keys_to_try:
        try:
            result = xxtea_decrypt(data, key)
            if result and len(result) > 20:
                key_display = key.decode(errors='replace')
                is_js = is_valid_js(result)
                marker = '[JS!]' if is_js else '[BIN]'
                print(f'  {marker} Key: {key_display} -> {len(result)} bytes')

                if is_js:
                    text = result.decode('utf-8', errors='replace')
                    print(f'    First 300 chars:')
                    print(f'    {text[:300]}')
                    print()

                    # Save
                    out_name = os.path.splitext(filepath)[0] + '_decrypted.js'
                    with open(out_name, 'wb') as f:
                        f.write(result)
                    print(f'    [!] Saved to: {out_name}')
                    return
        except Exception as e:
            pass

    print('[-] No valid decryption found with any key.')
    print('    Use Frida/Dobby hook to capture the key from the running game.')


if __name__ == '__main__':
    main()
