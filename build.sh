#!/bin/bash
set -e

echo "=========================================="
echo "  cocos2djs Dobby Hook - Build Script"
echo "=========================================="

# Find NDK
ANDROID_NDK=${ANDROID_NDK_HOME:-$NDK}
if [ -z "$ANDROID_NDK" ]; then
    if [ -d "$HOME/Android/Sdk/ndk" ]; then
        ANDROID_NDK=$(ls -d $HOME/Android/Sdk/ndk/*/ 2>/dev/null | sort -V | tail -1)
    elif [ -d "$HOME/Library/Android/sdk/ndk" ]; then
        ANDROID_NDK=$(ls -d $HOME/Library/Android/sdk/ndk/*/ 2>/dev/null | sort -V | tail -1)
    fi
fi

if [ -z "$ANDROID_NDK" ]; then
    echo "ERROR: ANDROID_NDK_HOME not set"
    echo "Usage: export ANDROID_NDK_HOME=/path/to/android-ndk"
    exit 1
fi

echo "NDK: $ANDROID_NDK"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Clean
rm -rf build
mkdir -p build

# Build for arm64-v8a
echo ""
echo "=== Building arm64-v8a ==="
mkdir -p build/arm64-v8a
cd build/arm64-v8a
cmake -DCMAKE_TOOLCHAIN_FILE="$ANDROID_NDK/build/cmake/android.toolchain.cmake" \
      -DANDROID_ABI=arm64-v8a \
      -DANDROID_PLATFORM=android-21 \
      -DCMAKE_BUILD_TYPE=Release \
      "$SCRIPT_DIR"
make -j$(nproc)
cd "$SCRIPT_DIR"

# Build for armeabi-v7a
echo ""
echo "=== Building armeabi-v7a ==="
mkdir -p build/armeabi-v7a
cd build/armeabi-v7a
cmake -DCMAKE_TOOLCHAIN_FILE="$ANDROID_NDK/build/cmake/android.toolchain.cmake" \
      -DANDROID_ABI=armeabi-v7a \
      -DANDROID_PLATFORM=android-21 \
      -DCMAKE_BUILD_TYPE=Release \
      "$SCRIPT_DIR"
make -j$(nproc)
cd "$SCRIPT_DIR"

echo ""
echo "=========================================="
echo "  Build Complete!"
echo "=========================================="
echo "  arm64-v8a:    build/arm64-v8a/libcocos2djs_hook.so"
echo "  armeabi-v7a:  build/armeabi-v7a/libcocos2djs_hook.so"
echo "=========================================="
