'use strict';

// ============================================================
//  Frida Hook for Cocos2d-JS Script Dump
//  Alternative when Dobby .so injection is not possible
// ============================================================

const DUMP_DIR = '/sdcard/cocos2djs_dump/';
let xxteaKey = null;

function ensureDir() {
    Java.perform(() => {
        try {
            const dir = Java.use('java.io.File').$new(DUMP_DIR);
            if (!dir.exists()) dir.mkdirs();
            ['scripts', 'jsc', 'assets'].forEach(sub => {
                const sd = Java.use('java.io.File').$new(DUMP_DIR + sub);
                if (!sd.exists()) sd.mkdirs();
            });
        } catch (e) { console.error('mkdir error:', e); }
    });
}

function saveToFile(filename, data) {
    if (!data || data.length === 0) return;
    Java.perform(() => {
        try {
            ensureDir();
            const fos = Java.use('java.io.FileOutputStream').$new(DUMP_DIR + filename);
            fos.write(data);
            fos.close();
            console.log(`[SAVED] ${filename} (${data.length} bytes)`);
        } catch (e) { console.error(`save error [${filename}]:`, e); }
    });
}

function saveText(filename, text) {
    saveToFile(filename, Memory.readByteArray(ptr(text), text.length * 2));
}

function hexdump(arr) {
    return Array.prototype.map.call(new Uint8Array(arr), b =>
        b.toString(16).padStart(2, '0')).join('');
}

// ============================================================
// Hook: jsb_set_xxtea_key
// ============================================================
function hookSetXXTEAKey() {
    const symName = Module.findExportByName('libcocos2djs.so',
        '_Z17jsb_set_xxtea_keyRKNSt6__ndk112basic_stringIcNS_11char_traitsIcEENS_9allocatorIcEEEE');
    const symName2 = Module.findExportByName('libcocos2djs.so',
        '_Z17jsb_set_xxtea_keyRKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE');
    const symName3 = Module.findExportByName('libcocos2djs.so', 'jsb_set_xxtea_key');

    const addr = symName || symName2 || symName3;
    if (!addr) {
        console.log('[-] jsb_set_xxtea_key not found via export, scanning symbols...');
        const syms = Module.enumerateSymbolsSync('libcocos2djs.so');
        for (const s of syms) {
            if (s.name.includes('jsb_set_xxtea_key')) {
                hookXXTEAAt(s.address);
                return;
            }
        }
        console.log('[-] jsb_set_xxtea_key not found anywhere');
        return;
    }
    hookXXTEAAt(addr);
}

function hookXXTEAAt(addr) {
    console.log('[+] jsb_set_xxtea_key at ' + addr);
    Interceptor.attach(addr, {
        onEnter(args) {
            try {
                // Try std::string: read ptr from arg0 (string object)
                const dataPtr = Memory.readPointer(args[0]);
                if (dataPtr.toInt32() > 0x1000 && dataPtr.toInt32() < 0x80000000) {
                    xxteaKey = Memory.readCString(dataPtr);
                } else {
                    xxteaKey = Memory.readCString(args[0]);
                }
                if (xxteaKey) {
                    console.log(`[KEY] XXTEA Key: "${xxteaKey}" (${xxteaKey.length} chars)`);
                    saveText('xxtea_key.txt', xxteaKey);
                }
            } catch (e) {
                console.log('[-] Error reading key:', e.message);
            }
        }
    });
}

// ============================================================
// Hook: evalString
// ============================================================
function hookEvalString() {
    let addr = Module.findExportByName('libcocos2djs.so', 'evalString');
    if (!addr) {
        const syms = Module.enumerateSymbolsSync('libcocos2djs.so');
        for (const s of syms) {
            if (s.name.includes('evalString')) {
                addr = s.address;
                break;
            }
        }
    }
    if (!addr) { console.log('[-] evalString not found'); return; }

    console.log('[+] evalString at ' + addr);
    Interceptor.attach(addr, {
        onEnter(args) {
            try {
                const scriptPtr = args[1];
                const scriptLen = args[2].toInt32();
                let filename = args[3] ? args[3].readCString() : null;

                if (scriptLen > 10 && scriptLen < 0x200000) {
                    if (!filename) filename = `eval_${Date.now()}.js`;
                    filename = filename.replace(/.*\//, '');
                    const script = scriptPtr.readCString(scriptLen);
                    console.log(`[JS] ${filename} (${scriptLen} bytes)`);
                    saveToFile(`scripts/${filename}`,
                        Memory.readByteArray(scriptPtr, scriptLen));
                }
            } catch (e) { /* skip bad reads */ }
        }
    });
}

// ============================================================
// Hook: xxtea_decrypt
// ============================================================
function hookXXTeadDecrypt() {
    let addr = Module.findExportByName('libcocos2djs.so', 'xxtea_decrypt');
    if (!addr) {
        const syms = Module.enumerateSymbolsSync('libcocos2djs.so');
        for (const s of syms) {
            if (s.name.includes('xxtea_decrypt')) {
                addr = s.address;
                break;
            }
        }
    }
    if (!addr) { console.log('[-] xxtea_decrypt not found'); return; }

    console.log('[+] xxtea_decrypt at ' + addr);
    Interceptor.attach(addr, {
        onEnter(args) {
            this.inData = args[0];
            this.inLen = args[1].toInt32();
            this.inKey = args[2];
            this.inKeyLen = args[3].toInt32();
        },
        onLeave(retval) {
            if (retval.isNull()) return;
            try {
                // Try to get out_len - varies by arch
                let outLenPtr = null;
                // arm64: x4 holds out_len ptr, arm: r3
                const ctx = this.context;
                if (ctx.x4) outLenPtr = Memory.readPointer(ctx.x4);
                else if (ctx.r3) outLenPtr = Memory.readPointer(ctx.r3);

                if (outLenPtr) {
                    const outLen = outLenPtr.toInt32();
                    if (outLen > 10 && outLen < 0x100000) {
                        const dec = retval.readByteArray(outLen);
                        console.log(`[DECRYPT] xxtea: ${this.inLen} -> ${outLen} bytes`);
                        saveToFile(`jsc/decrypted_${Date.now()}.bin`, dec);
                    }
                }
            } catch (e) { /* skip */ }
        }
    });
}

// ============================================================
// Hook: getFileData (capture encrypted JSC files)
// ============================================================
function hookGetFileData() {
    // Try both std::string and const char* variants
    const syms = Module.enumerateSymbolsSync('libcocos2djs.so');
    let addr = null;
    for (const s of syms) {
        if (s.name.includes('getFileData') && s.name.includes('FileUtils')) {
            addr = s.address;
            console.log('[+] getFileData at ' + addr + ' (' + s.name + ')');
            break;
        }
    }
    if (!addr) { console.log('[-] getFileData not found'); return; }

    Interceptor.attach(addr, {
        onEnter(args) {
            try {
                // filename is usually arg1 (arg0 = this)
                let filename = null;
                try {
                    const ptr = Memory.readPointer(args[1]);
                    if (ptr.toInt32() > 0x1000) filename = ptr.readCString();
                } catch (e) {
                    filename = args[1].readCString();
                }

                if (filename && (filename.endsWith('.jsc') ||
                    filename.endsWith('.js') || filename.endsWith('.json'))) {
                    this.fname = filename.replace(/.*\//, '');
                    console.log(`[FILE] Loading: ${filename}`);
                }
            } catch (e) { /* skip */ }
        },
        onLeave(retval, state) {
            if (this.fname && !retval.isNull()) {
                try {
                    // Get size from output parameter
                    let sizePtr = null;
                    const ctx = this.context;
                    if (ctx.x3) sizePtr = Memory.readPointer(ctx.x3);
                    else if (ctx.r2) sizePtr = Memory.readPointer(ctx.r2);

                    if (sizePtr) {
                        const size = sizePtr.toInt32();
                        if (size > 0 && size < 0x200000) {
                            const data = retval.readByteArray(size);
                            console.log(`[FILE] Got: ${this.fname} (${size} bytes)`);
                            saveToFile(`assets/${this.fname}`, data);
                        }
                    }
                } catch (e) { /* skip */ }
                this.fname = null;
            }
        }
    });
}

// ============================================================
// Main
// ============================================================
function waitForLib() {
    const lib = Module.findBaseAddress('libcocos2djs.so');
    if (!lib) {
        console.log('[-] Waiting for libcocos2djs.so...');
        setTimeout(waitForLib, 2000);
        return;
    }

    console.log(`[+] libcocos2djs.so at ${lib}`);
    hookSetXXTEAKey();
    hookEvalString();
    hookXXTeadDecrypt();
    hookGetFileData();

    console.log('[+] All hooks installed!');
    console.log(`[+] Output: ${DUMP_DIR}`);
}

Java.perform(() => {
    console.log('');
    console.log('=== Cocos2d-JS Frida Dump Tool ===');
    console.log('');
    setTimeout(waitForLib, 3000);
});
