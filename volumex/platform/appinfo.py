"""Human-readable app names from an exe's version resource."""
from __future__ import annotations

import ctypes
import struct
from ctypes import wintypes
from functools import lru_cache

from volumex.core.app_identity import pretty_exe_name

_version = ctypes.WinDLL("version")
_version.GetFileVersionInfoSizeW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD))
_version.GetFileVersionInfoSizeW.restype = wintypes.DWORD
_version.GetFileVersionInfoW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p)
_version.GetFileVersionInfoW.restype = wintypes.BOOL
_version.VerQueryValueW.argtypes = (
    ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)
)
_version.VerQueryValueW.restype = wintypes.BOOL

# Used when the resource has no \VarFileInfo\Translation: en-US with Unicode / Windows-1252 / neutral code pages.
_FALLBACK_TRANSLATIONS = ((0x0409, 0x04B0), (0x0409, 0x04E4), (0x0409, 0x0000))
_GENERIC_NAMES = frozenset({"application", "app", "program", "executable", "unknown", "n/a", "none", "-", "?"})


def _query(block: ctypes.Array, sub_block: str) -> tuple[int, int] | None:
    ptr = ctypes.c_void_p()
    length = wintypes.UINT()
    if not _version.VerQueryValueW(block, sub_block, ctypes.byref(ptr), ctypes.byref(length)) or not ptr.value:
        return None
    return ptr.value, length.value


def _version_strings(exe_path: str, fields: tuple[str, ...]) -> dict[str, str]:
    size = _version.GetFileVersionInfoSizeW(exe_path, None)
    if not size:
        return {}
    block = ctypes.create_string_buffer(size)
    if not _version.GetFileVersionInfoW(exe_path, 0, size, block):
        return {}
    translations: list[tuple[int, int]] = []
    found = _query(block, "\\VarFileInfo\\Translation")
    if found:
        ptr, nbytes = found
        raw = ctypes.string_at(ptr, nbytes)
        translations = [struct.unpack_from("<HH", raw, i) for i in range(0, nbytes - nbytes % 4, 4)]
    translations += [t for t in _FALLBACK_TRANSLATIONS if t not in translations]

    result: dict[str, str] = {}
    for field in fields:
        for lang, codepage in translations:
            found = _query(block, f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\{field}")
            if found:
                value = ctypes.wstring_at(found[0]).strip()
                if value:
                    result[field] = value
                    break
    return result


def _usable(name: str | None) -> bool:
    return bool(name) and name.lower() not in _GENERIC_NAMES and not name.lower().endswith(".exe")


@lru_cache(maxsize=512)
def display_name(exe_path: str) -> str:
    """FileDescription, else ProductName, else a name made from the exe file name."""
    if exe_path:
        try:
            strings = _version_strings(exe_path, ("FileDescription", "ProductName"))
        except OSError:
            strings = {}
        for field in ("FileDescription", "ProductName"):
            if _usable(strings.get(field)):
                return strings[field]
    return pretty_exe_name(exe_path)
