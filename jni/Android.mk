LOCAL_PATH := $(call my-dir)

include $(CLEAR_VARS)

LOCAL_MODULE := cocos2djs_hook
LOCAL_SRC_FILES := hook.cpp

LOCAL_C_INCLUDES := $(LOCAL_PATH)/../Dobby/include

LOCAL_LDLIBS := -llog -ldl

LOCAL_CPPFLAGS := -std=c++11 -fvisibility=hidden -Wall -Wextra

include $(BUILD_SHARED_LIBRARY)

$(call import-add-path, $(LOCAL_PATH)/..)
$(call import-module, Dobby)
