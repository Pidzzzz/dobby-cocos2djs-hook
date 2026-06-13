cmake_minimum_required(VERSION 3.10)
project(cocos2djs_hook CXX)

set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(NOT DEFINED DOBBY_SOURCE_DIR)
    set(DOBBY_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/Dobby")
endif()

# Use stable Dobby commit (pre-refactor, supports both arm64 and arm32)
set(DOBBY_COMMIT "e9fe7fbecae47a2287e761080f8b1133cc22e8fa")

# Auto-download Dobby if not found
if(NOT EXISTS "${DOBBY_SOURCE_DIR}/include/dobby.h")
    message(STATUS "Dobby not found at ${DOBBY_SOURCE_DIR}, downloading commit ${DOBBY_COMMIT}...")
    file(DOWNLOAD
        "https://github.com/jmpews/Dobby/archive/${DOBBY_COMMIT}.zip"
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
    file(GLOB dobby_dirs "${CMAKE_BINARY_DIR}/dobby_extract/Dobby-${DOBBY_COMMIT}")
    list(LENGTH dobby_dirs num_dirs)
    if(num_dirs EQUAL 1)
        file(RENAME "${dobby_dirs}" "${DOBBY_SOURCE_DIR}")
        message(STATUS "Dobby downloaded and extracted to ${DOBBY_SOURCE_DIR}")
    else()
        message(FATAL_ERROR "Failed to find extracted Dobby directory")
    endif()
endif()

add_subdirectory(${DOBBY_SOURCE_DIR} dobby_build)

# Fix duplicate symbols in old Dobby's Logger::Shared() with modern compilers
if(TARGET dobby)
    set_target_properties(dobby PROPERTIES LINK_FLAGS "-Wl,--allow-multiple-definition")
endif()

add_library(cocos2djs_hook SHARED jni/hook.cpp)

target_include_directories(cocos2djs_hook PRIVATE
    ${DOBBY_SOURCE_DIR}/include
)

# Link against dobby_static to avoid shared lib issues
target_link_libraries(cocos2djs_hook
    dobby_static
    log
    dl
)