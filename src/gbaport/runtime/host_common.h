/* host_common.h - what both hosts do the same way: the command line, the ROM and save
 * files, scripted key presses, the frame limit and the end of a run. */
#ifndef HOST_COMMON_H
#define HOST_COMMON_H

#include "gba_runtime.h"

enum { HOST_MAX_PRESSES = 64 };

typedef struct {
    unsigned long frame;  /* from this VBlank on (0: from the start) */
    uint16_t keys;        /* the GBA keys held, 1 = pressed */
} HostPress;

typedef struct {
    const char *rom_path;
    char save_path[1024];
    unsigned long frame_limit;  /* 0: no limit */
    int registers;              /* print the CPU registers when the run ends */
    const char *screenshot;     /* write the last picture there (BMP) */
    int window;                 /* the window host's options are allowed */
    int fast;                   /* window: no frame pacing */
    int scale;                  /* window: initial size in GBA screens */
    HostPress presses[HOST_MAX_PRESSES];
    int press_count, next_press;
    uint16_t script_keys;       /* what the presses so far hold */
    uint8_t *rom;
} HostOptions;

/* Reads the command line; prints the usage and returns 2 when it is wrong. */
int host_parse(HostOptions *o, int argc, char **argv);
/* Loads the ROM and the save file into rt; returns 0, or 2 after printing why not. */
int host_open(HostOptions *o, GbaRuntime *rt, const GbaHost *host);
/* Once a frame: scripted presses due by now, the save file, the frame limit. */
void host_frame(HostOptions *o, GbaRuntime *rt);
/* While the game is stopped: applies the next scripted press; 0 when none is left. */
int host_script_wake(HostOptions *o);
/* Stores the save, reports the end and returns the exit status. */
int host_finish(HostOptions *o, GbaRuntime *rt, GbaEnd end);
/* Writes 240x160 pixels (0x00RRGGBB) as a BMP file; returns 0 on success. */
int host_write_bmp(const char *path, const uint32_t *pixels);

#endif
