"""PyInstaller entry point for VolumeXEngine.exe (console subsystem, started hidden by VolumeX.exe)."""
import sys

from volumex.engine.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
