"""Identifies the virtual cable used as the Boost Bus.

Phase 1 uses VB-Audio's VB-CABLE (installed by VolumeX, see platform.vbcable):
apps are routed to its render side ("CABLE Input") and the engine captures its
recording side ("CABLE Output"). When VolumeX ships its own driver, only these
names change.
"""
from __future__ import annotations

BUS_RENDER_MARKERS = ("CABLE Input",)
BUS_CAPTURE_MARKERS = ("CABLE Output",)
BUS_PRODUCT_NAME = "VB-CABLE"


def is_bus_render_name(name: str) -> bool:
    return any(marker.lower() in name.lower() for marker in BUS_RENDER_MARKERS)


def is_bus_capture_name(name: str) -> bool:
    return any(marker.lower() in name.lower() for marker in BUS_CAPTURE_MARKERS)
