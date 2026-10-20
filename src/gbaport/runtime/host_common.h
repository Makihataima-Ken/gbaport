/* host_common.h - what both hosts do the same way: the command line, the ROM and save
 * files, scripted key presses and input files, the frame limit, the sound file, the
 * pictures' hashes and the end of a run. */
#ifndef HOST_COMMON_H
#define HOST_COMMON_H

#include "gba_runtime.h"

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
    const char *audio;          /* write the sound there (WAV) */
    const char *hashes;         /* write each frame's picture hash there */
    void *hashes_file;          /* the open hashes file (a FILE *) */
    void *audio_file;           /* the open WAV file (a FILE *) */
    uint32_t audio_samples;     /* written to it so far */
    int16_t sound[GBA_SOUND_BUFFER][2];  /* the samples of the last frame */
    uint32_t sound_count;
    int window;                 /* the window host's options are allowed */
    int fast;                   /* window: no frame pacing */
    int scale;                  /* window: initial size in GBA screens */
    HostPress *presses;         /* from --press and --input, in frame order */
    int press_count, press_capacity, next_press;
    uint16_t script_keys;       /* what the presses so far hold */
    uint8_t *rom;
} HostOptions;

/* Reads the command line; prints the usage and returns 2 when it is wrong. */
int host_parse(HostOptions *o, int argc, char **argv);
/* Loads the ROM and the save file into rt; returns 0, or 2 after printing why not. */
int host_open(HostOptions *o, GbaRuntime *rt, const GbaHost *host);
/* Once a frame: the frame's samples (o->sound) and the sound file, the picture's hash,
 * scripted presses due by now, the save file, the frame limit. */
void host_frame(HostOptions *o, GbaRuntime *rt);
/* While the game is stopped: applies the next scripted press; 0 when none is left. */
int host_script_wake(HostOptions *o);
/* Stores the save, finishes the sound file, reports the end and returns the exit status. */
int host_finish(HostOptions *o, GbaRuntime *rt, GbaEnd end);
/* How fast a sound device should play the GBA's samples (1.0: as they come) when
 * `queued` of them wait: a little faster with more than `target`, slower with fewer, so
 * the queue stays near `target` however the device's clock and the frame pacing drift. */
double host_sound_speed(double queued, double target);
/* The picture's 64-bit FNV-1a hash, over its colours as two bytes each (low first). */
uint64_t host_picture_hash(const GbaRuntime *rt);
/* Writes 240x160 pixels (0x00RRGGBB) as a BMP file; returns 0 on success. */
int host_write_bmp(const char *path, const uint32_t *pixels);

#endif
