# Builds SDL3 as a static library for gbaport's window host (gbaport/native/sdl3.py runs
# this). The source release comes from GBAPORT_SDL3_URL and must match GBAPORT_SDL3_SHA256.
cmake_minimum_required(VERSION 3.28)
project(gbaport_sdl3 LANGUAGES C)

include(FetchContent)
set(SDL_SHARED OFF CACHE BOOL "" FORCE)
set(SDL_STATIC ON CACHE BOOL "" FORCE)
set(SDL_TEST_LIBRARY OFF CACHE BOOL "" FORCE)
set(SDL_INSTALL ON CACHE BOOL "" FORCE)
FetchContent_Declare(SDL3 URL "${GBAPORT_SDL3_URL}" URL_HASH "SHA256=${GBAPORT_SDL3_SHA256}")
FetchContent_MakeAvailable(SDL3)
