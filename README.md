# Cocos2d-JS Dobby Hook

Dobby-based native hook untuk mendecrypt dan mendump script JavaScript dari game **Cocos2d-JS** (`.jsc` files).

## Cara Kerja

Hook ini mencegat 4 fungsi utama di `libcocos2djs.so`:

| Fungsi | Kegunaan |
|---|---|
| `jsb_set_xxtea_key` | Menangkap **XXTEA encryption key** yang dipakai game |
| `evalString` | Mendump **JavaScript yang sudah didekripsi** saat dieksekusi |
| `xxtea_decrypt` | Mendump **data hasil dekripsi** langsung dari memory |
| `FileUtils::getFileData` | Mendump **file .jsc/.js mentah** yang diload game |

## Build via GitHub Actions (RECOMMENDED)

1. Fork/push repo ini ke GitHub
2. GitHub Actions akan otomatis build untuk `arm64-v8a` dan `armeabi-v7a`
3. Download artifact dari tab Actions

## Build Manual (Local)

### Prerequisites
- Android NDK r21+ (`ANDROID_NDK_HOME` environment variable)
- CMake 3.10+
- Git

### Build

```bash
chmod +x build.sh
./build.sh
```

Output:
- `build/arm64-v8a/libcocos2djs_hook.so`
- `build/armeabi-v7a/libcocos2djs_hook.so`

## Inject ke APK

### Metode 1: APKTool + Smali Patching (Manual)

```bash
# 1. Decompile APK
apktool d game.apk -o game_extracted

# 2. Copy hook .so
cp build/arm64-v8a/libcocos2djs_hook.so game_extracted/lib/arm64-v8a/

# 3. Add System.loadLibrary di smali
# Edit smali/com/game/app/Application.sali:
#   const-string v0, "cocos2djs_hook"
#   invoke-static {v0}, Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V

# 4. Rebuild & sign
apktool b game_extracted -o game_modified.apk
jarsigner -keystore my.keystore -storepass android game_modified.apk alias
```

### Metode 2: Script Otomatis

```bash
python scripts/inject_apk.py game.apk --hook ./build --output game_hooked.apk
```

### Metode 3: LD_PRELOAD (tanpa patch APK)

```bash
adb push build/arm64-v8a/libcocos2djs_hook.so /data/local/tmp/
adb shell su -c "LD_PRELOAD=/data/local/tmp/libcocos2djs_hook.so am start -n com.game.app/.MainActivity"
```

## Melihat Hasil Dump

```bash
# Cek log
adb logcat -s cocos2djs_hook

# Pull dump files
adb pull /sdcard/cocos2djs_dump/ ./dumped_scripts/

# Decrypt .jsc files
python scripts/decrypt_jsc.py dumped_scripts/assets/index.jsc

# Decrypt with key
python scripts/decrypt_jsc.py index.jsc "L5OfXzi9IbpZI=8HrYJ"
```

## Alternatif: Frida Hook

Kalau tidak bisa inject .so, pakai Frida:

```bash
# Attach ke process
python scripts/frida_dump.py com.game.app

# Spawn app
python scripts/frida_dump.py --spawn com.game.app

# List running apps
python scripts/frida_dump.py -l
```

## Output Structure

```
/sdcard/cocos2djs_dump/
├── xxtea_key.txt           # XXTEA key
├── xxtea_key.hex           # Key dalam hex
├── scripts/                # JavaScript hasil dekripsi
│   ├── main.js
│   └── ...
├── jsc/                    # Data hasil xxtea_decrypt
│   ├── xxtea_decrypted.bin
│   └── ...
└── assets/                 # File mentah dari getFileData
    ├── index.jsc
    └── ...
```

## Catatan

- Game harus **support arm64** atau **armeabi-v7a** - cek dulu arsitektur APK
- XXTEA key biasanya diset diawal saat game loading
- Kalau `jsb_set_xxtea_key` tidak terhook, coba cek logcat untuk alternatif symbol name
- Untuk game dengan **V8** engine (bukan SpiderMonkey), hook `evalString` mungkin berbeda
