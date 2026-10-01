"""Per-app output routing through the undocumented IAudioPolicyConfigFactory.

This is the interface Windows Settings ("App volume and device preferences") and
EarTrumpet use. It is a WinRT activation factory reached with
RoGetActivationFactory("Windows.Media.Internal.AudioPolicyConfig"); its IID
changed in build 21390 but the vtable layout did not (see EarTrumpet's
IAudioPolicyConfigFactoryVariantFor21H2.cs / ...ForDownlevel.cs).

Called through raw vtable slots with ctypes, so nothing here depends on comtypes.
The calling thread must have COM initialised.
"""
from __future__ import annotations

import ctypes
import logging
import sys
import uuid
from ctypes import wintypes

log = logging.getLogger(__name__)

_CLASS_ID = "Windows.Media.Internal.AudioPolicyConfig"
_IID_DOWNLEVEL = "{2a59116d-6c4f-45e0-a74f-707e3fef9258}"
_IID_21H2 = "{ab3d4648-e242-459f-b02f-541c70306324}"
_BUILD_21H2 = 21390

# vtable: IUnknown (0-2), IInspectable (3-5), 19 methods we don't use (6-24), then:
_SLOT_RELEASE = 2
_SLOT_SET = 25  # SetPersistedDefaultAudioEndpoint(UINT pid, EDataFlow, ERole, HSTRING deviceId)
_SLOT_GET = 26  # GetPersistedDefaultAudioEndpoint(UINT pid, EDataFlow, ERole, HSTRING* deviceId)
_SLOT_CLEAR = 27  # ClearAllPersistedApplicationDefaultEndpoints()

E_RENDER = 0
E_CONSOLE = 0
E_MULTIMEDIA = 1

# Device interface path around an MMDevice endpoint id, as the policy store wants it.
_MMDEVAPI_TOKEN = "\\\\?\\SWD#MMDEVAPI#"
_DEVINTERFACE_AUDIO_RENDER = "#{e6327cad-dcec-4949-ae8a-991e976a79d2}"
_DEVINTERFACE_AUDIO_CAPTURE = "#{2eef81be-33fa-4800-9670-1cd474972c3f}"

HSTRING = ctypes.c_void_p


def interface_iid(build: int) -> str:
    return _IID_21H2 if build >= _BUILD_21H2 else _IID_DOWNLEVEL


def wrap_device_id(mmdevice_id: str) -> str:
    """'{0.0.0.00000000}.{guid}' -> '\\\\?\\SWD#MMDEVAPI#{0.0.0.00000000}.{guid}#{e6327cad-...}'."""
    return f"{_MMDEVAPI_TOKEN}{mmdevice_id}{_DEVINTERFACE_AUDIO_RENDER}"


def unwrap_device_id(device_id: str) -> str:
    """Inverse of wrap_device_id(); ids without the decoration are returned unchanged."""
    if device_id[: len(_MMDEVAPI_TOKEN)].upper() == _MMDEVAPI_TOKEN.upper():
        device_id = device_id[len(_MMDEVAPI_TOKEN):]
    for suffix in (_DEVINTERFACE_AUDIO_RENDER, _DEVINTERFACE_AUDIO_CAPTURE):
        if device_id.lower().endswith(suffix):
            device_id = device_id[: -len(suffix)]
    return device_id


def _combase() -> ctypes.WinDLL:
    dll = ctypes.WinDLL("combase")
    dll.WindowsCreateString.argtypes = (wintypes.LPCWSTR, wintypes.UINT, ctypes.POINTER(HSTRING))
    dll.WindowsCreateString.restype = ctypes.c_long
    dll.WindowsDeleteString.argtypes = (HSTRING,)
    dll.WindowsDeleteString.restype = ctypes.c_long
    dll.WindowsGetStringRawBuffer.argtypes = (HSTRING, ctypes.POINTER(wintypes.UINT))
    dll.WindowsGetStringRawBuffer.restype = ctypes.c_void_p
    dll.RoGetActivationFactory.argtypes = (HSTRING, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    dll.RoGetActivationFactory.restype = ctypes.c_long
    return dll


def _check(hr: int, what: str) -> None:
    if hr < 0:
        raise OSError(hr & 0xFFFFFFFF, f"{what} failed with HRESULT 0x{hr & 0xFFFFFFFF:08X}")


_SetFn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.UINT, ctypes.c_int, ctypes.c_int, HSTRING)
_GetFn = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_void_p, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.POINTER(HSTRING)
)
_NoArgFn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)


class AudioPolicyConfig:
    """Persisted per-process default render endpoint. Check `available` before use:
    it is False when activation fails (unsupported build), and callers should then
    disable per-app routing instead of failing."""

    def __init__(self) -> None:
        self.available = False
        self._factory = ctypes.c_void_p()
        try:
            self._dll = _combase()
            self._activate()
            self.available = True
        except (OSError, AttributeError) as exc:
            log.warning("Per-app routing unavailable: %s", exc)

    def _activate(self) -> None:
        iid_bytes = uuid.UUID(interface_iid(sys.getwindowsversion().build)).bytes_le
        iid = (ctypes.c_ubyte * 16).from_buffer_copy(iid_bytes)  # GUID struct layout
        name = self._create_string(_CLASS_ID)
        try:
            hr = self._dll.RoGetActivationFactory(name, ctypes.byref(iid), ctypes.byref(self._factory))
            _check(hr, "RoGetActivationFactory(AudioPolicyConfig)")
        finally:
            self._dll.WindowsDeleteString(name)
        if not self._factory:
            raise OSError("RoGetActivationFactory returned no factory")

    def _method(self, slot: int, prototype):
        vtable = ctypes.cast(self._factory, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return prototype(vtable[slot])

    def _create_string(self, text: str) -> HSTRING:
        out = HSTRING()
        length = len(text.encode("utf-16-le")) // 2
        _check(self._dll.WindowsCreateString(text, length, ctypes.byref(out)), "WindowsCreateString")
        return out

    def _require(self) -> None:
        if not self.available or not self._factory:
            raise OSError("IAudioPolicyConfigFactory is not available")

    def set_app_endpoint(self, pid: int, mmdevice_id: str | None) -> None:
        """Route `pid` to an endpoint (eConsole + eMultimedia render roles).
        None resets the app to follow the Windows default."""
        self._require()
        hstring = self._create_string(wrap_device_id(mmdevice_id)) if mmdevice_id else HSTRING()
        try:
            set_fn = self._method(_SLOT_SET, _SetFn)
            for role in (E_MULTIMEDIA, E_CONSOLE):
                _check(set_fn(self._factory, pid, E_RENDER, role, hstring), "SetPersistedDefaultAudioEndpoint")
        finally:
            if hstring:
                self._dll.WindowsDeleteString(hstring)

    def get_app_endpoint(self, pid: int) -> str | None:
        """The MMDevice id `pid` is routed to, or None if it follows the Windows default."""
        self._require()
        out = HSTRING()
        hr = self._method(_SLOT_GET, _GetFn)(self._factory, pid, E_RENDER, E_MULTIMEDIA, ctypes.byref(out))
        _check(hr, "GetPersistedDefaultAudioEndpoint")
        if not out:
            return None
        try:
            length = wintypes.UINT()
            buffer = self._dll.WindowsGetStringRawBuffer(out, ctypes.byref(length))
            text = ctypes.wstring_at(buffer, length.value) if buffer else ""
        finally:
            self._dll.WindowsDeleteString(out)
        return unwrap_device_id(text) or None

    def clear_all(self) -> None:
        """Reset the persisted endpoint of every app."""
        self._require()
        _check(self._method(_SLOT_CLEAR, _NoArgFn)(self._factory), "ClearAllPersistedApplicationDefaultEndpoints")

    def close(self) -> None:
        if self._factory:
            self._method(_SLOT_RELEASE, _NoArgFn)(self._factory)
            self._factory = ctypes.c_void_p()
        self.available = False
