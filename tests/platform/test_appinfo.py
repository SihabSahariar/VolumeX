from __future__ import annotations

import os
import sys

from volumex.platform.appinfo import display_name


def test_missing_file_falls_back_to_exe_name():
    assert display_name(r"C:\definitely\not\here\my_cool-app.exe") == "My Cool App"


def test_empty_path():
    assert display_name("") == "Unknown app"


def test_reads_file_description():
    notepad = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "notepad.exe")
    name = display_name(notepad)
    assert name and not name.lower().endswith(".exe")


def test_python_has_a_name():
    assert display_name(sys.executable)
