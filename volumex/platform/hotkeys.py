"""System-wide hotkeys via RegisterHotKey, delivered through Qt's native event filter.

RegisterHotKey(NULL, ...) posts WM_HOTKEY to the registering thread's queue, so
GlobalHotkeys must be created and used on the GUI thread (the one running the Qt
event loop).
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

from PyQt5.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, pyqtSignal

log = logging.getLogger(__name__)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

# Display order follows Windows conventions ("Win+Shift+S", "Ctrl+Alt+Del").
_MODIFIERS = (("Win", MOD_WIN), ("Ctrl", MOD_CONTROL), ("Alt", MOD_ALT), ("Shift", MOD_SHIFT))
_MODIFIER_ALIASES = {
    "win": MOD_WIN, "windows": MOD_WIN, "meta": MOD_WIN, "super": MOD_WIN,
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
}


def _key_table() -> dict[str, int]:
    keys = {chr(c): c for c in range(ord("A"), ord("Z") + 1)}
    keys.update({str(d): 0x30 + d for d in range(10)})
    keys.update({f"F{n}": 0x6F + n for n in range(1, 25)})
    keys.update({f"Num{d}": 0x60 + d for d in range(10)})
    keys.update({
        "Up": 0x26, "Down": 0x28, "Left": 0x25, "Right": 0x27,
        "PgUp": 0x21, "PgDn": 0x22, "Home": 0x24, "End": 0x23, "Ins": 0x2D, "Del": 0x2E,
        "Space": 0x20, "Enter": 0x0D, "Tab": 0x09, "Esc": 0x1B, "Backspace": 0x08,
        "Pause": 0x13, "PrtSc": 0x2C, "ScrollLock": 0x91,
        "NumMultiply": 0x6A, "NumAdd": 0x6B, "NumSubtract": 0x6D, "NumDecimal": 0x6E, "NumDivide": 0x6F,
        "Plus": 0xBB, "Minus": 0xBD, "Comma": 0xBC, "Period": 0xBE,
        "VolumeMute": 0xAD, "VolumeDown": 0xAE, "VolumeUp": 0xAF,
        "MediaNext": 0xB0, "MediaPrev": 0xB1, "MediaStop": 0xB2, "MediaPlayPause": 0xB3,
    })
    return keys


_KEY_NAMES = _key_table()  # canonical name -> VK
_VK_NAMES = {vk: name for name, vk in _KEY_NAMES.items()}
_KEY_ALIASES = {name.lower(): vk for name, vk in _KEY_NAMES.items()}
_KEY_ALIASES.update({
    "pageup": 0x21, "prior": 0x21, "pagedown": 0x22, "pgdown": 0x22, "next": 0x22,
    "insert": 0x2D, "delete": 0x2E, "return": 0x0D, "escape": 0x1B,
    "printscreen": 0x2C, "numpad0": 0x60, "numpad1": 0x61, "numpad2": 0x62, "numpad3": 0x63,
    "numpad4": 0x64, "numpad5": 0x65, "numpad6": 0x66, "numpad7": 0x67, "numpad8": 0x68,
    "numpad9": 0x69, "=": 0xBB, "-": 0xBD, ",": 0xBC, ".": 0xBE,
})


def _parse_key(lower: str) -> int | None:
    if lower in _KEY_ALIASES:
        return _KEY_ALIASES[lower]
    if len(lower) == 4 and lower.startswith("vk"):  # raw code, as written by format_combo
        try:
            return int(lower[2:], 16)
        except ValueError:
            return None
    return None


def parse_combo(combo: str) -> tuple[int, int]:
    """'Ctrl+Alt+PgUp' -> (MOD_CONTROL | MOD_ALT, VK_PRIOR). Case-insensitive.
    Raises ValueError unless there is exactly one known non-modifier key."""
    mods, vk = 0, None
    parts = [p.strip() for p in combo.split("+")]
    if not combo.strip() or any(not p for p in parts):
        raise ValueError(f"Invalid hotkey: {combo!r}")
    for part in parts:
        lower = part.lower()
        if lower in _MODIFIER_ALIASES:
            mods |= _MODIFIER_ALIASES[lower]
        else:
            key = _parse_key(lower)
            if key is None:
                raise ValueError(f"Unknown key {part!r} in hotkey {combo!r}")
            if vk is not None:
                raise ValueError(f"Hotkey has more than one key: {combo!r}")
            vk = key
    if vk is None:
        raise ValueError(f"Hotkey has no key: {combo!r}")
    return mods, vk


def format_combo(mods: int, vk: int) -> str:
    """(MOD_CONTROL | MOD_ALT, 0x26) -> 'Ctrl+Alt+Up'. MOD_NOREPEAT is ignored."""
    parts = [name for name, flag in _MODIFIERS if mods & flag]
    parts.append(_VK_NAMES.get(vk, f"VK{vk:02X}"))
    return "+".join(parts)


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.UnregisterHotKey.restype = wintypes.BOOL


class _WmHotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, on_hotkey) -> None:
        super().__init__()
        self._on_hotkey = on_hotkey

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and not msg.hWnd:
                return self._on_hotkey(int(msg.wParam)), 0
        return False, 0


class GlobalHotkeys(QObject):
    """Emits activated(name) when a registered combo is pressed anywhere in Windows."""

    activated = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._names: dict[int, str] = {}  # hotkey id -> name
        self._next_id = 1
        self._filter = _WmHotkeyFilter(self._on_hotkey)
        app = QCoreApplication.instance()
        if app is None:
            raise RuntimeError("GlobalHotkeys needs a QCoreApplication")
        app.installNativeEventFilter(self._filter)

    def register(self, name: str, combo: str) -> bool:
        """Bind `name` to `combo` (replacing its previous combo). False if the combo is
        invalid or already taken by another program."""
        self.unregister(name)
        try:
            mods, vk = parse_combo(combo)
        except ValueError as exc:
            log.warning("%s", exc)
            return False
        hotkey_id = self._next_id
        if not _user32.RegisterHotKey(None, hotkey_id, mods | MOD_NOREPEAT, vk):
            log.info("Hotkey %s (%s) is taken: error %d", combo, name, ctypes.get_last_error())
            return False
        self._next_id += 1
        self._names[hotkey_id] = name
        return True

    def unregister(self, name: str) -> None:
        for hotkey_id, registered in list(self._names.items()):
            if registered == name:
                _user32.UnregisterHotKey(None, hotkey_id)
                del self._names[hotkey_id]

    def unregister_all(self) -> None:
        for hotkey_id in self._names:
            _user32.UnregisterHotKey(None, hotkey_id)
        self._names.clear()

    def _on_hotkey(self, hotkey_id: int) -> bool:
        name = self._names.get(hotkey_id)
        if name is None:
            return False
        self.activated.emit(name)
        return True
