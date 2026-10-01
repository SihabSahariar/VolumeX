"""Foreground window's process, and exe path lookup by pid."""
from __future__ import annotations

import ctypes
import ntpath
from ctypes import wintypes

import psutil

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_UWP_HOST_EXE = "applicationframehost.exe"

# Private WinDLL instances so setting argtypes doesn't affect other ctypes users.
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = (
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
)
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.CloseHandle.restype = wintypes.BOOL

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetForegroundWindow.argtypes = ()
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_user32.EnumChildWindows.argtypes = (wintypes.HWND, _WNDENUMPROC, wintypes.LPARAM)
_user32.EnumChildWindows.restype = wintypes.BOOL


def _query_image_name(pid: int) -> str | None:
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value or None
        return None
    finally:
        _kernel32.CloseHandle(handle)


def exe_path_for_pid(pid: int) -> str | None:
    """Full exe path of a process, or None (process gone, or no image such as pid 0/4)."""
    if pid <= 0:
        return None
    try:
        exe = psutil.Process(pid).exe()
        if exe:
            return exe
    except psutil.NoSuchProcess:
        return None
    except psutil.Error:
        pass
    return _query_image_name(pid)


def _window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _hosted_uwp_pid(frame_hwnd: int, host_pid: int) -> int | None:
    """ApplicationFrameHost hosts UWP apps in a child window owned by the app's process."""
    found: list[int] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        pid = _window_pid(hwnd)
        if pid and pid != host_pid:
            found.append(pid)
            return False  # stop enumeration
        return True

    _user32.EnumChildWindows(frame_hwnd, _WNDENUMPROC(callback), 0)
    return found[0] if found else None


def foreground_process() -> tuple[int, str] | None:
    """(pid, exe path) of the foreground window's process, resolving UWP apps
    hosted by ApplicationFrameHost.exe to their own process."""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = _window_pid(hwnd)
    exe = exe_path_for_pid(pid)
    if not exe:
        return None
    if ntpath.basename(exe).lower() == _UWP_HOST_EXE:
        hosted = _hosted_uwp_pid(hwnd, pid)
        hosted_exe = exe_path_for_pid(hosted) if hosted else None
        if hosted and hosted_exe:
            return hosted, hosted_exe
    return pid, exe
