"""VB-CABLE, the free virtual audio cable by VB-Audio that VolumeX uses as its Boost Bus.

VB-Audio lets applications ship the unmodified VB-CABLE package and install it silently, as long as users
can see it is VB-Audio's product and are able to donate (https://vb-audio.com/Services/licensing.htm).
VolumeX therefore:
  * ships the official package next to VolumeX.exe (fetched at build time by packaging/fetch_vbcable.py),
    or downloads it from vb-audio.com when the user asks to install and it isn't there;
  * checks VB-Audio's code signature before running anything;
  * always names VB-Audio and links to their donation page wherever VB-CABLE is mentioned.
"""
from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

PACKAGE_URL = "https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip"
PACKAGE_SHA256 = "b950e39f01af1d04ea623c8f6d8eb9b6ea5c477c637295fabf20631c85116bfb"
SETUP_EXE = "VBCABLE_Setup_x64.exe"
SIGNER_MARKER = "BUREL VINCENT"  # VB-Audio's author; the EV code-signing subject of the setup program
HOME_URL = "https://vb-audio.com/Cable/"
DONATE_URL = "https://shop.vb-audio.com/en/win-apps/11-vb-cable.html"
LICENSE_URL = "https://vb-audio.com/Services/licensing.htm"
INSTALL_ARGS = "-i -h"  # install, no dialogs
UNINSTALL_ARGS = "-u -h"

ERROR_CANCELLED = 1223  # the user said no to the UAC prompt


class VbCableError(RuntimeError):
    pass


@dataclass(frozen=True)
class SetupResult:
    ok: bool
    cancelled: bool = False
    exit_code: int | None = None
    message: str = ""


# -- where the package lives ----------------------------------------------------------------------
def bundled_dir() -> Path | None:
    """The package shipped with VolumeX: <exe dir>/vbcable when frozen, third_party/vbcable from source."""
    if getattr(sys, "frozen", False):
        candidate = Path(sys.executable).parent / "vbcable"
    else:
        candidate = Path(__file__).resolve().parents[2] / "third_party" / "vbcable"
    return candidate if (candidate / SETUP_EXE).exists() else None


def _cache_dir() -> Path:
    from volumex.storage.paths import cache_dir

    return cache_dir("vbcable")


def is_installed() -> bool:
    """Fast check for the driver file. The controller's device list is the authority on whether it works."""
    drivers = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers"
    return any(drivers.glob("vbaudio_cable64*.sys"))


def find_package(download: bool = True, progress: Callable[[int, int], None] | None = None) -> Path:
    """Folder containing SETUP_EXE: bundled, previously downloaded, or freshly downloaded."""
    bundled = bundled_dir()
    if bundled:
        return bundled
    cached = _cache_dir()
    if (cached / SETUP_EXE).exists():
        return cached
    if not download:
        raise VbCableError("The VB-CABLE package isn't available.")
    return download_package(cached, progress)


def download_package(dest: Path, progress: Callable[[int, int], None] | None = None,
                     strict_hash: bool = False) -> Path:
    """Download the official package from vb-audio.com and unpack it into dest.

    The zip must match the pinned SHA-256, or (unless strict_hash) VB-Audio may have refreshed it - then the
    setup program's code signature alone decides.
    """
    log.info("downloading %s", PACKAGE_URL)
    digest = hashlib.sha256()
    with tempfile.TemporaryDirectory(prefix="volumex-vbcable-") as tmp:
        archive = Path(tmp) / "vbcable.zip"
        try:
            with urllib.request.urlopen(PACKAGE_URL, timeout=30) as response, archive.open("wb") as out:
                total = int(response.headers.get("Content-Length") or 0)
                got = 0
                while chunk := response.read(64 * 1024):
                    out.write(chunk)
                    digest.update(chunk)
                    got += len(chunk)
                    if progress:
                        progress(got, total)
        except OSError as exc:
            raise VbCableError(f"Couldn't download VB-CABLE from vb-audio.com ({exc}).") from exc
        if digest.hexdigest() != PACKAGE_SHA256:
            if strict_hash:
                raise VbCableError(f"The downloaded package changed (sha256 {digest.hexdigest()}); "
                                   "check it and update PACKAGE_SHA256.")
            log.warning("VB-CABLE package hash differs from the pinned one; relying on the code signature")
        staging = Path(tmp) / "pack"
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(staging)
        if not verify_signature(staging / SETUP_EXE):
            raise VbCableError("The downloaded VB-CABLE setup isn't signed by VB-Audio, so it wasn't used.")
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(staging, dest)
    return dest


# -- trust ----------------------------------------------------------------------------------------
def verify_signature(exe: Path) -> bool:
    """True if Windows reports a valid Authenticode signature from VB-Audio's author on exe."""
    if not exe.exists():
        return False
    path = str(exe).replace("'", "''")
    script = (f"$s = Get-AuthenticodeSignature -LiteralPath '{path}'; "
              "Write-Output ($s.Status.ToString() + '|' + $s.SignerCertificate.Subject)")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("signature check failed to run: %s", exc)
        return False
    status, _, subject = out.partition("|")
    ok = status == "Valid" and SIGNER_MARKER in subject.upper()
    log.info("signature of %s: %s (%s)", exe.name, status, subject[:60])
    return ok


# -- running VB-Audio's setup -----------------------------------------------------------------------
class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_NOASYNC = 0x00000100
SW_SHOWNORMAL = 1
WAIT_OBJECT_0 = 0


def run_elevated(exe: Path, args: str, timeout_s: float = 300.0) -> SetupResult:
    """Start exe as administrator (one UAC prompt) and wait for it to finish."""
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    info.lpVerb = "runas"
    info.lpFile = str(exe)
    info.lpParameters = args
    info.lpDirectory = str(exe.parent)
    info.nShow = SW_SHOWNORMAL
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        err = ctypes.get_last_error()
        if err == ERROR_CANCELLED:
            return SetupResult(False, cancelled=True, message="Windows permission was declined.")
        return SetupResult(False, message=f"Couldn't start the setup (Windows error {err}).")
    if not info.hProcess:
        return SetupResult(True, message="Setup started.")
    try:
        if kernel32.WaitForSingleObject(info.hProcess, int(timeout_s * 1000)) != WAIT_OBJECT_0:
            return SetupResult(False, message="The setup is taking unusually long.")
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return SetupResult(True, exit_code=int(code.value))
    finally:
        kernel32.CloseHandle(info.hProcess)


def install(package: Path, silent: bool = True) -> SetupResult:
    setup = package / SETUP_EXE
    if not verify_signature(setup):
        raise VbCableError("The VB-CABLE setup isn't signed by VB-Audio, so VolumeX won't run it.")
    log.info("running %s %s", setup, INSTALL_ARGS if silent else "(interactive)")
    return run_elevated(setup, INSTALL_ARGS if silent else "")


def uninstall(package: Path) -> SetupResult:
    setup = package / SETUP_EXE
    if not verify_signature(setup):
        raise VbCableError("The VB-CABLE setup isn't signed by VB-Audio, so VolumeX won't run it.")
    return run_elevated(setup, UNINSTALL_ARGS)
