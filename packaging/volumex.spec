# PyInstaller spec: builds dist/VolumeX/ with two executables sharing one runtime:
#   VolumeX.exe        windowed UI + controller
#   VolumeXEngine.exe  audio engine (console subsystem; VolumeX starts it without a window)
# build.ps1 then copies VB-Audio's VB-CABLE package into dist/VolumeX/vbcable/.
# Build with packaging/build.ps1.
from pathlib import Path

ROOT = Path(SPECPATH).parent
ICON = str(ROOT / "assets" / "volumex.ico")
HIDDEN = ["comtypes", "comtypes.stream", "pycaw.pycaw", "samplerate", "_sounddevice_data"]
EXCLUDES = ["tkinter", "matplotlib", "IPython", "pytest", "hypothesis"]

app_a = Analysis([str(ROOT / "packaging" / "entry_app.py")], pathex=[str(ROOT)], hiddenimports=HIDDEN,
                 excludes=EXCLUDES, datas=[(str(ROOT / "volumex" / "resources"), "volumex/resources")])
eng_a = Analysis([str(ROOT / "packaging" / "entry_engine.py")], pathex=[str(ROOT)], hiddenimports=HIDDEN,
                 excludes=EXCLUDES + ["PyQt5"])

app_pyz = PYZ(app_a.pure)
eng_pyz = PYZ(eng_a.pure)

app_exe = EXE(app_pyz, app_a.scripts, [], exclude_binaries=True, name="VolumeX", icon=ICON, console=False,
              upx=False)
eng_exe = EXE(eng_pyz, eng_a.scripts, [], exclude_binaries=True, name="VolumeXEngine", icon=ICON, console=True,
              upx=False)

coll = COLLECT(app_exe, app_a.binaries, app_a.datas, eng_exe, eng_a.binaries, eng_a.datas, upx=False,
               name="VolumeX")
