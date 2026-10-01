"""parse_combo/format_combo only: never registers a real hotkey."""
from __future__ import annotations

import pytest

from volumex.platform.hotkeys import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    MOD_WIN,
    format_combo,
    parse_combo,
)


@pytest.mark.parametrize(
    ("combo", "expected"),
    [
        ("Ctrl+Alt+Up", (MOD_CONTROL | MOD_ALT, 0x26)),
        ("Ctrl+Alt+Down", (MOD_CONTROL | MOD_ALT, 0x28)),
        ("Ctrl+Shift+F9", (MOD_CONTROL | MOD_SHIFT, 0x78)),
        ("Win+Alt+B", (MOD_WIN | MOD_ALT, ord("B"))),
        ("Ctrl+Alt+PgUp", (MOD_CONTROL | MOD_ALT, 0x21)),
        ("Ctrl+Alt+PgDn", (MOD_CONTROL | MOD_ALT, 0x22)),
        ("Ctrl+Alt+0", (MOD_CONTROL | MOD_ALT, 0x30)),
        ("F24", (0, 0x87)),
        ("ctrl + alt + pageup", (MOD_CONTROL | MOD_ALT, 0x21)),
        ("Control+Meta+m", (MOD_CONTROL | MOD_WIN, ord("M"))),
        ("Alt+Num5", (MOD_ALT, 0x65)),
        ("Ctrl+NumAdd", (MOD_CONTROL, 0x6B)),
        ("Shift+VolumeUp", (MOD_SHIFT, 0xAF)),
    ],
)
def test_parse_combo(combo, expected):
    assert parse_combo(combo) == expected


@pytest.mark.parametrize(
    "combo", ["", "   ", "Ctrl+Alt", "Ctrl+A+B", "Ctrl+Nope", "Ctrl++", "Ctrl+Alt+", "+Up"]
)
def test_parse_combo_rejects(combo):
    with pytest.raises(ValueError):
        parse_combo(combo)


@pytest.mark.parametrize(
    "combo",
    ["Ctrl+Alt+Up", "Ctrl+Shift+F9", "Win+Alt+B", "Ctrl+Alt+PgUp", "Ctrl+Alt+0", "Win+Ctrl+Alt+Shift+Space", "F1"],
)
def test_format_round_trip(combo):
    assert format_combo(*parse_combo(combo)) == combo


def test_format_canonicalises_order_and_aliases():
    assert format_combo(*parse_combo("alt+ctrl+pageup")) == "Ctrl+Alt+PgUp"
    assert format_combo(*parse_combo("Shift+Win+s")) == "Win+Shift+S"


def test_format_ignores_norepeat_and_handles_unknown_vk():
    assert format_combo(MOD_CONTROL | MOD_NOREPEAT, 0x26) == "Ctrl+Up"
    assert format_combo(MOD_ALT, 0x07) == "Alt+VK07"
    assert parse_combo("Alt+VK07") == (MOD_ALT, 0x07)


def test_native_filter_emits_for_known_hotkey_id(qapp):
    """Feeds a synthetic WM_HOTKEY MSG to the filter; nothing is registered with Windows."""
    import ctypes
    from ctypes import wintypes

    from PyQt5 import sip
    from PyQt5.QtCore import QByteArray

    from volumex.platform.hotkeys import WM_HOTKEY, GlobalHotkeys

    hotkeys = GlobalHotkeys()
    hotkeys._names[5] = "boost"  # as if register() had succeeded
    fired: list[str] = []
    hotkeys.activated.connect(fired.append)

    def feed(message: int, wparam: int):
        msg = wintypes.MSG(hWnd=None, message=message, wParam=wparam)
        return hotkeys._filter.nativeEventFilter(QByteArray(b"windows_generic_MSG"), sip.voidptr(ctypes.addressof(msg)))

    assert feed(WM_HOTKEY, 5) == (True, 0)
    assert feed(WM_HOTKEY, 6) == (False, 0)  # not ours
    assert feed(0x0100, 5) == (False, 0)  # WM_KEYDOWN
    assert fired == ["boost"]
    hotkeys._names.clear()  # nothing to unregister
