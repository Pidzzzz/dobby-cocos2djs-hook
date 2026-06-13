#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <stdlib.h>
#include <unistd.h>
#include <android/log.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <string>
#include <mutex>

#include "dobby.h"

#define LOG_TAG "cocos2djs_hook"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)
#define LOGD(...) __android_log_print(ANDROID_LOG_DEBUG, LOG_TAG, __VA_ARGS__)

#define DUMP_DIR "/sdcard/cocos2djs_dump"
#define MAX_SCRIPT_SIZE (4 * 1024 * 1024)
#define MAX_WAIT_SEC 120

static std::mutex g_mutex;
static bool g_hooked = false;
static char g_xxtea_key[128] = {0};
static int g_xxtea_key_len = 0;

static void ensure_dir() {
    mkdir(DUMP_DIR, 0777);
    mkdir((std::string(DUMP_DIR) + "/scripts").c_str(), 0777);
    mkdir((std::string(DUMP_DIR) + "/jsc").c_str(), 0777);
    mkdir((std::string(DUMP_DIR) + "/assets").c_str(), 0777);
}

static void dump_to_file(const char *subdir, const char *filename,
                         const void *data, int len) {
    if (!data || len <= 0 || len > MAX_SCRIPT_SIZE) return;

    std::lock_guard<std::mutex> lock(g_mutex);
    ensure_dir();

    char path[512];
    if (filename && strlen(filename) > 0) {
        const char *fname = strrchr(filename, '/');
        fname = fname ? fname + 1 : filename;
        snprintf(path, sizeof(path), "%s/%s/%s", DUMP_DIR,
                 subdir ? subdir : "", fname);
    } else {
        static int counter = 0;
        snprintf(path, sizeof(path), "%s/%s/dump_%d.bin", DUMP_DIR,
                 subdir ? subdir : "", __sync_fetch_and_add(&counter, 1));
    }

    FILE *f = fopen(path, "wb");
    if (f) {
        fwrite(data, 1, len, f);
        fclose(f);
        LOGI("SAVED: %s (%d bytes)", path, len);
    } else {
        LOGE("FAILED to write: %s", path);
    }
}

// ============================================================
// Hook: jsb_set_xxtea_key (std::string variant - NDK)
// ============================================================
typedef void (*jsb_set_xxtea_key_std_t)(const std::string &);
static jsb_set_xxtea_key_std_t orig_jsb_set_xxtea_key_std = nullptr;

static void fake_jsb_set_xxtea_key_std(const std::string &key) {
    int len = (int)key.length();
    if (len > 0 && len < (int)sizeof(g_xxtea_key)) {
        memcpy(g_xxtea_key, key.data(), len);
        g_xxtea_key_len = len;
        g_xxtea_key[len] = '\0';

        char hex[256] = {0};
        for (int i = 0; i < len && i < 64; i++)
            sprintf(hex + i * 2, "%02x", (unsigned char)g_xxtea_key[i]);

        LOGI("XXTEA_KEY(captured): len=%d hex=%s", len, hex);

        FILE *f = fopen(DUMP_DIR "/xxtea_key.txt", "wb");
        if (f) {
            fwrite(g_xxtea_key, 1, len, f);
            fclose(f);
        }
        f = fopen(DUMP_DIR "/xxtea_key.hex", "wb");
        if (f) {
            fwrite(hex, 1, len * 2, f);
            fclose(f);
        }
    }
    if (orig_jsb_set_xxtea_key_std)
        orig_jsb_set_xxtea_key_std(key);
}

// ============================================================
// Hook: jsb_set_xxtea_key (const char* variant)
// ============================================================
typedef void (*jsb_set_xxtea_key_cstr_t)(const char *key, int len);
static jsb_set_xxtea_key_cstr_t orig_jsb_set_xxtea_key_cstr = nullptr;

static void fake_jsb_set_xxtea_key_cstr(const char *key, int len) {
    if (key && len > 0 && len < (int)sizeof(g_xxtea_key)) {
        memcpy(g_xxtea_key, key, len);
        g_xxtea_key_len = len;
        g_xxtea_key[len] = '\0';
        LOGI("XXTEA_KEY(captured cstr): len=%d key=%s", len, key);

        FILE *f = fopen(DUMP_DIR "/xxtea_key.txt", "wb");
        if (f) {
            fwrite(g_xxtea_key, 1, len, f);
            fclose(f);
        }
    }
    if (orig_jsb_set_xxtea_key_cstr)
        orig_jsb_set_xxtea_key_cstr(key, len);
}

// ============================================================
// Hook: evalString - dump decrypted JS
// ============================================================
typedef void *(*evalString_t)(void *ctx, const char *script,
                               int script_len, const char *filename);
static evalString_t orig_evalString = nullptr;

static void *fake_evalString(void *ctx, const char *script,
                              int script_len, const char *filename) {
    if (script && script_len > 0) {
        LOGI("evalString: file=%s len=%d",
             filename ? filename : "null", script_len);
        dump_to_file("scripts", filename, script, script_len);
    }
    return orig_evalString(ctx, script, script_len, filename);
}

// ============================================================
// Hook: xxtea_decrypt
// ============================================================
typedef unsigned char *(*xxtea_decrypt_t)(const unsigned char *data,
        int data_len, const unsigned char *key, int key_len, int *out_len);
static xxtea_decrypt_t orig_xxtea_decrypt = nullptr;

static unsigned char *fake_xxtea_decrypt(const unsigned char *data,
        int data_len, const unsigned char *key, int key_len, int *out_len) {
    unsigned char *result = orig_xxtea_decrypt(data, data_len,
                                                key, key_len, out_len);
    if (result && out_len && *out_len > 0 && *out_len < MAX_SCRIPT_SIZE) {
        LOGI("xxtea_decrypt: in=%d out=%d", data_len, *out_len);
        dump_to_file("jsc", "xxtea_decrypted.bin", result, *out_len);
    }
    return result;
}

// ============================================================
// Hook: FileUtils::getFileData (JSC file loading)
// ============================================================
typedef void *(*getFileData_t)(void *self, const char *filename,
                                const char *mode, size_t *outSize);
static getFileData_t orig_getFileData = nullptr;

static void *fake_getFileData(void *self, const char *filename,
                               const char *mode, size_t *outSize) {
    void *result = orig_getFileData(self, filename, mode, outSize);

    if (result && outSize && *outSize > 0 && *outSize < MAX_SCRIPT_SIZE) {
        const char *ext = strrchr(filename ? filename : "", '.');
        if (ext && (strcasecmp(ext, ".jsc") == 0 ||
                    strcasecmp(ext, ".js") == 0 ||
                    strcasecmp(ext, ".json") == 0)) {
            LOGI("getFileData: %s (%zu bytes) -> will dump encrypted",
                 filename ? filename : "null", *outSize);
            dump_to_file("assets", filename, result, (int)*outSize);
        }
    }
    return result;
}

// ============================================================
// Symbol resolution helpers
// ============================================================
static void *try_dlsym(void *handle, const char **names, int count) {
    for (int i = 0; i < count; i++) {
        void *addr = dlsym(handle, names[i]);
        if (addr) {
            LOGI("SYMBOL: %s -> %p", names[i], addr);
            return addr;
        }
    }
    return nullptr;
}

// ============================================================
// Main hook logic
// ============================================================
static void install_hooks() {
    if (g_hooked) return;
    g_hooked = true;

    void *handle = dlopen("libcocos2djs.so", RTLD_LAZY | RTLD_LOCAL);
    if (!handle) {
        LOGE("dlopen libcocos2djs.so failed: %s", dlerror());
        g_hooked = false;
        return;
    }
    LOGI("libcocos2djs.so loaded");

    ensure_dir();

    // 1. Hook jsb_set_xxtea_key - std::string variants
    const char *key_std_names[] = {
        "_Z17jsb_set_xxtea_keyRKNSt6__ndk112basic_stringIcNS_11char_traitsIcEENS_9allocatorIcEEEE",
        "_Z17jsb_set_xxtea_keyRKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE",
        "_Z17jsb_set_xxtea_keyRKSs",
        "jsb_set_xxtea_key",
    };
    void *key_std_addr = try_dlsym(handle, key_std_names, 4);
    if (key_std_addr) {
        DobbyHook(key_std_addr, (void *)fake_jsb_set_xxtea_key_std,
                  (void **)&orig_jsb_set_xxtea_key_std);
        LOGI("HOOKED: jsb_set_xxtea_key(std::string) at %p", key_std_addr);
    } else {
        // Try const char* variant
        void *key_cstr_addr = dlsym(handle, "jsb_set_xxtea_key");
        if (key_cstr_addr) {
            DobbyHook(key_cstr_addr, (void *)fake_jsb_set_xxtea_key_cstr,
                      (void **)&orig_jsb_set_xxtea_key_cstr);
            LOGI("HOOKED: jsb_set_xxtea_key(cstr) at %p", key_cstr_addr);
        } else {
            LOGE("jsb_set_xxtea_key NOT FOUND");
        }
    }

    // 2. Hook evalString
    void *eval_addr = dlsym(handle, "evalString");
    if (!eval_addr) {
        const char *eval_names[] = {
            "_Z10evalStringP7JSScriptPKciS2_",
            "_Z10evalStringP8JSContextP8JSScriptPKciS4_",
            "_Z10evalStringP8JSContextP7JSScriptPKciS3_",
        };
        eval_addr = try_dlsym(handle, eval_names, 3);
    }
    if (eval_addr) {
        DobbyHook(eval_addr, (void *)fake_evalString,
                  (void **)&orig_evalString);
        LOGI("HOOKED: evalString at %p", eval_addr);
    } else {
        LOGE("evalString NOT FOUND");
    }

    // 3. Hook xxtea_decrypt
    const char *xxtea_names[] = {
        "xxtea_decrypt",
        "_Z13xxtea_decryptPKhiS0_iPi",
        "_Z13xxtea_decryptPhiiPi",
    };
    void *xxtea_addr = try_dlsym(handle, xxtea_names, 3);
    if (xxtea_addr) {
        DobbyHook(xxtea_addr, (void *)fake_xxtea_decrypt,
                  (void **)&orig_xxtea_decrypt);
        LOGI("HOOKED: xxtea_decrypt at %p", xxtea_addr);
    } else {
        LOGE("xxtea_decrypt NOT FOUND");
    }

    // 4. Hook FileUtils::getFileData
    const char *fileutil_names[] = {
        "_ZN7cocos2d9FileUtils11getFileDataEPKcS2_Pm",
        "_ZN7cocos2d9FileUtils11getFileDataERKNSt6__ndk112basic_stringIcNS1_11char_traitsIcEENS1_9allocatorIcEEEES9_Pm",
        "_ZN7cocos2d9FileUtils11getFileDataERKSsS2_Pm",
    };
    void *fileutil_addr = try_dlsym(handle, fileutil_names, 3);
    if (fileutil_addr) {
        DobbyHook(fileutil_addr, (void *)fake_getFileData,
                  (void **)&orig_getFileData);
        LOGI("HOOKED: getFileData at %p", fileutil_addr);
    } else {
        LOGE("getFileData NOT FOUND");
    }

    dlclose(handle);
    LOGI("All hooks installed successfully");
}

// ============================================================
// Constructor - auto-run when library is loaded
// ============================================================
__attribute__((constructor))
static void on_load() {
    LOGI("=== cocos2djs Dobby Hook v2.0 loaded ===");

    // Wait for libcocos2djs.so to be loaded by the app
    for (int i = 0; i < MAX_WAIT_SEC * 2; i++) {
        void *handle = dlopen("libcocos2djs.so", RTLD_NOLOAD);
        if (handle) {
            dlclose(handle);
            LOGI("libcocos2djs.so detected, installing hooks...");
            install_hooks();
            return;
        }
        usleep(500000);
    }
    LOGE("Timed out waiting for libcocos2djs.so");
}
