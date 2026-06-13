cmake_minimum_required(VERSION 3.10)
project(cocos2djs_hook CXX)

set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(NOT DEFINED DOBBY_SOURCE_DIR)
    set(DOBBY_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/Dobby")
endif()

# Auto-download Dobby if not found
if(NOT EXISTS "${DOBBY_SOURCE_DIR}/include/dobby.h")
    message(STATUS "Dobby not found at ${DOBBY_SOURCE_DIR}, downloading...")
    file(DOWNLOAD
        "https://github.com/jmpews/Dobby/archive/refs/heads/master.zip"
        "${CMAKE_BINARY_DIR}/dobby.zip"
        STATUS download_status
        LOG download_log
        SHOW_PROGRESS)
    list(GET download_status 0 status_code)
    if(NOT status_code EQUAL 0)
        message(STATUS "Download log: ${download_log}")
        message(FATAL_ERROR "Failed to download Dobby")
    endif()
    file(ARCHIVE_EXTRACT
        INPUT "${CMAKE_BINARY_DIR}/dobby.zip"
        DESTINATION "${CMAKE_BINARY_DIR}/dobby_extract")
    file(GLOB dobby_dirs "${CMAKE_BINARY_DIR}/dobby_extract/Dobby-*")
    list(LENGTH dobby_dirs num_dirs)
    if(num_dirs EQUAL 1)
        file(RENAME "${dobby_dirs}" "${DOBBY_SOURCE_DIR}")
        message(STATUS "Dobby downloaded and extracted to ${DOBBY_SOURCE_DIR}")
    else()
        message(FATAL_ERROR "Failed to find extracted Dobby directory")
    endif()

    # ==========================================================
    # Apply patches to fix Dobby (commit 5dfc854) build issues
    # ==========================================================

    # Fix 1: registers-arm.h - Cpu.h was renamed to CpuRegister.h
    set(PATCH_FILE "${DOBBY_SOURCE_DIR}/source/core/arch/arm/registers-arm.h")
    if(EXISTS "${PATCH_FILE}")
        file(READ "${PATCH_FILE}" patch_content)
        string(REPLACE "#include \"core/arch/Cpu.h\"" "#include \"core/arch/CpuRegister.h\"" patch_content "${patch_content}")
        file(WRITE "${PATCH_FILE}" "${patch_content}")
        message(STATUS "[PATCH] registers-arm.h: Cpu.h -> CpuRegister.h")
    endif()

    # Fix 2: Create missing Cpu.h stub that redirects to CpuRegister.h
    set(PATCH_FILE "${DOBBY_SOURCE_DIR}/source/core/arch/Cpu.h")
    if(NOT EXISTS "${PATCH_FILE}")
        file(WRITE "${PATCH_FILE}" "#pragma once\n#include \"core/arch/CpuRegister.h\"\n")
        message(STATUS "[PATCH] Created Cpu.h stub")
    endif()

    # Fix 3: os_arch_features.h - circular include, replace OSMemory with POSIX calls
    set(PATCH_FILE "${DOBBY_SOURCE_DIR}/common/os_arch_features.h")
    if(EXISTS "${PATCH_FILE}")
        file(READ "${PATCH_FILE}" patch_content)
        string(REPLACE "#include \"PlatformUnifiedInterface/platform.h\"" "#include <sys/mman.h>\n#include <unistd.h>" patch_content "${patch_content}")
        string(REPLACE "  auto page = (void *)ALIGN_FLOOR(address, OSMemory::PageSize());\n  if (!OSMemory::SetPermission(page, OSMemory::PageSize(), kReadExecute)) {\n    return;\n  }" "  long page_size = sysconf(_SC_PAGESIZE);\n  auto page = (void *)ALIGN_FLOOR(address, page_size);\n  mprotect(page, page_size, PROT_READ | PROT_EXEC);" patch_content "${patch_content}")
        file(WRITE "${PATCH_FILE}" "${patch_content}")
        message(STATUS "[PATCH] os_arch_features.h: fixed circular include + OSMemory")
    endif()

    # Fix 4: closure_bridge_arm64.asm - ADRP/PAGE not supported with LLVM
    set(PATCH_FILE "${DOBBY_SOURCE_DIR}/source/TrampolineBridge/ClosureTrampolineBridge/arm64/closure_bridge_arm64.asm")
    if(EXISTS "${PATCH_FILE}")
        file(READ "${PATCH_FILE}" patch_content)
        string(REPLACE "adrp TMP_REG_0, cdecl(common_closure_bridge_handler)@PAGE\nadd TMP_REG_0, TMP_REG_0, cdecl(common_closure_bridge_handler)@PAGEOFF" "ldr TMP_REG_0, common_closure_bridge_handler_addr" patch_content "${patch_content}")
        file(WRITE "${PATCH_FILE}" "${patch_content}")
        message(STATUS "[PATCH] closure_bridge_arm64.asm: replaced ADRP with LDR")
    endif()

    # Fix 5: Linux ProcessRuntime.cc - load_address -> base, start -> start()
    set(PATCH_FILE "${DOBBY_SOURCE_DIR}/source/Backend/UserMode/PlatformUtil/Linux/ProcessRuntime.cc")
    if(EXISTS "${PATCH_FILE}")
        file(READ "${PATCH_FILE}" patch_content)
        string(REPLACE "module.load_address" "module.base" patch_content "${patch_content}")
        string(REPLACE "a.start < b.start" "a.start() < b.start()" patch_content "${patch_content}")
        if(NOT patch_content MATCHES "#include <inttypes.h>")
            string(REPLACE "#include <sys/mman.h>" "#include <sys/mman.h>\n#include <inttypes.h>" patch_content "${patch_content}")
        endif()
        file(WRITE "${PATCH_FILE}" "${patch_content}")
        message(STATUS "[PATCH] ProcessRuntime.cc: load_address -> base, added inttypes.h")
    endif()

    # Fix 6: dobby_symbol_resolver.cc - load_address -> base
    set(PATCH_FILE "${DOBBY_SOURCE_DIR}/builtin-plugin/SymbolResolver/elf/dobby_symbol_resolver.cc")
    if(EXISTS "${PATCH_FILE}")
        file(READ "${PATCH_FILE}" patch_content)
        string(REPLACE "module.load_address" "module.base" patch_content "${patch_content}")
        file(WRITE "${PATCH_FILE}" "${patch_content}")
        message(STATUS "[PATCH] dobby_symbol_resolver.cc: load_address -> base")
    endif()

    # Fix 7: code-patch-tool-posix.cc - missing ALIGN_FLOOR via linear_allocator.h
    set(PATCH_FILE "${DOBBY_SOURCE_DIR}/source/Backend/UserMode/ExecMemory/code-patch-tool-posix.cc")
    if(EXISTS "${PATCH_FILE}")
        file(READ "${PATCH_FILE}" patch_content)
        if(NOT patch_content MATCHES "linear_allocator.h")
            string(REPLACE "#include <string.h>" "#include <string.h>\n#include \"common/linear_allocator.h\"" patch_content "${patch_content}")
            file(WRITE "${PATCH_FILE}" "${patch_content}")
            message(STATUS "[PATCH] code-patch-tool-posix.cc: added linear_allocator.h")
        endif()
    endif()

    # Fix 8: Link with lowercase 'dobby' (newer Dobby uses lowercase targets)
    set(DOBBY_TARGET "dobby")
    set(DOBBY_STATIC_TARGET "dobby_static")
endif()

add_subdirectory(${DOBBY_SOURCE_DIR} dobby_build)

add_library(cocos2djs_hook SHARED jni/hook.cpp)

target_include_directories(cocos2djs_hook PRIVATE
    ${DOBBY_SOURCE_DIR}/include
)

target_link_libraries(cocos2djs_hook
    ${DOBBY_TARGET}
    log
    dl
)