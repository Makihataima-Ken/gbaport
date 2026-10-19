# jsmolka's GBA tests

Test ROMs from <https://github.com/jsmolka/gba-tests> (MIT licence), commit
`a7113b67e63f83a9b321696ddd7042ccfad6c881`. `tests/jsmolka.py` downloads them from that
commit the first time, checks their SHA-1 and caches them with the other test ROMs: like
every `.gba` file, they are not in the repository. Each CPU ROM runs its tests,
shows "All tests passed" or "Failed test N" in mode 4 and then idles; a register (r12, r7
in `thumb.gba`) holds the number of the first failed test (0 when all passed).
`tests/runtime/test_public_roms.py` reads it with the hosts' `--registers` option and
checks the picture with `--screenshot`: the register is 0 too while the tests have not
finished.

| ROM | Tests |
|---|---|
| `arm.gba` | ARM instructions: conditions, branches, flags, shifts, data processing, PSR transfers, multiplies, single and halfword transfers, swaps, block transfers |
| `thumb.gba` | Thumb instructions |
| `memory.gba` | Memory mirrors and byte writes to video memory |
| `bios.gba` | What reads of the BIOS area return, before and after a SWI and an interrupt |
| `sram.gba`, `flash64.gba`, `flash128.gba`, `none.gba` | The save chips, and a cartridge without one |
| `ppu/hello.gba`, `ppu/shades.gba`, `ppu/stripes.gba` | Pictures (text in a tiled background, shades of a palette, stripes), which `tests/runtime/test_render_public.py` compares with mGBA's |

Each ROM's `.toml` is its `game.toml`: the ROM's SHA-1, the code addresses discovery
cannot find (reached through addresses the tests store in memory), and the save chip where
the ROM's marker has no version digits.

Not used: `nes.gba`, which copies its code to
VRAM and rewrites instructions there while they run, which a static recompiler cannot
follow; and `unsafe.gba`, whose own README says it fails on real hardware.
