"""Test-only assembler (Keystone). Never imported by gbaport itself."""

import keystone

_ARM = keystone.Ks(keystone.KS_ARCH_ARM, keystone.KS_MODE_ARM)
_THUMB = keystone.Ks(keystone.KS_ARCH_ARM, keystone.KS_MODE_THUMB)


def assemble(text: str, *, thumb: bool = False, addr: int = 0x08000000) -> bytes:
    """Assemble UAL ``text`` (statements separated by newlines) located at ``addr``."""
    encoding, _ = (_THUMB if thumb else _ARM).asm(text, addr)
    if encoding is None:
        raise ValueError(f"Keystone produced no bytes for {text!r}")
    return bytes(encoding)
