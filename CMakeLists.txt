cmake_minimum_required(VERSION 3.10)
project(cocos2djs_hook CXX)

set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(NOT DEFINED DOBBY_SOURCE_DIR)
    set(DOBBY_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/Dobby")
endif()

if(NOT EXISTS "${DOBBY_SOURCE_DIR}/include/dobby.h")
    message(FATAL_ERROR "Dobby not found at ${DOBBY_SOURCE_DIR}. "
            "Run: git submodule update --init --recursive")
endif()

add_subdirectory(${DOBBY_SOURCE_DIR} dobby_build)

add_library(cocos2djs_hook SHARED jni/hook.cpp)

target_include_directories(cocos2djs_hook PRIVATE
    ${DOBBY_SOURCE_DIR}/include
)

target_link_libraries(cocos2djs_hook
    Dobby
    log
    dl
)
