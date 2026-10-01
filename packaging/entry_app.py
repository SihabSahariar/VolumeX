"""PyInstaller entry point for VolumeX.exe (windowed)."""
import sys

from volumex.app import main

if __name__ == "__main__":
    sys.exit(main())
