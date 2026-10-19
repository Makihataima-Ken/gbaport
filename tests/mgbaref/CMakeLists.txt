# Builds mGBA's GBA core and mgbaref.c, the renderer tests' reference (tests/mgbaref.py
# runs this). The source release is GBAPORT_MGBA_URL (mgbaref.py downloads it first) and
# must match GBAPORT_MGBA_SHA256; mgbaref.py writes salt.c into the build folder.
cmake_minimum_required(VERSION 3.28)
project(gbaport_mgbaref LANGUAGES C)

include(FetchContent)
string(APPEND CMAKE_C_FLAGS " -Wno-incompatible-pointer-types -Wno-int-conversion")  # clang 23
# GBA colours throughout, blended in 5 bits per channel like the GBA: mGBA's sources take
# the definition, its generated flags.h the variable.
add_compile_definitions(COLOR_16_BIT)
set(COLOR_16_BIT ON CACHE BOOL "" FORCE)
foreach(option LIBMGBA_ONLY DISABLE_DEPS BUILD_STATIC)
    set(${option} ON CACHE BOOL "" FORCE)
endforeach()
foreach(option BUILD_SHARED M_CORE_GB USE_DEBUGGERS USE_GDB_STUB ENABLE_SCRIPTING BUILD_LTO)
    set(${option} OFF CACHE BOOL "" FORCE)
endforeach()
FetchContent_Declare(mgba URL "${GBAPORT_MGBA_URL}" URL_HASH "SHA256=${GBAPORT_MGBA_SHA256}")
FetchContent_MakeAvailable(mgba)
if(WIN32)  # mGBA links the maths library "m"; on Windows the C runtime has those functions
    add_library(m INTERFACE)
endif()

add_executable(mgbaref mgbaref.c "${CMAKE_BINARY_DIR}/salt.c")
target_include_directories(mgbaref PRIVATE "${mgba_SOURCE_DIR}/include" "${mgba_BINARY_DIR}/include")
target_compile_definitions(mgbaref PRIVATE BUILD_STATIC M_CORE_GBA)
target_link_libraries(mgbaref PRIVATE mgba)
