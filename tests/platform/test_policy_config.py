from __future__ import annotations

from volumex.platform.policy_config import interface_iid, unwrap_device_id, wrap_device_id

MMDEVICE_ID = "{0.0.0.00000000}.{a42be1e7-2714-4de7-98b7-737b16ae171d}"
WIRE_ID = r"\\?\SWD#MMDEVAPI#" + MMDEVICE_ID + "#{e6327cad-dcec-4949-ae8a-991e976a79d2}"


def test_wrap_device_id():
    assert wrap_device_id(MMDEVICE_ID) == WIRE_ID


def test_unwrap_round_trip():
    assert unwrap_device_id(wrap_device_id(MMDEVICE_ID)) == MMDEVICE_ID


def test_unwrap_is_case_insensitive_on_decoration():
    shouting = r"\\?\swd#mmdevapi#" + MMDEVICE_ID + "#{E6327CAD-DCEC-4949-AE8A-991E976A79D2}"
    assert unwrap_device_id(shouting) == MMDEVICE_ID


def test_unwrap_capture_suffix_and_plain_ids():
    assert unwrap_device_id(r"\\?\SWD#MMDEVAPI#{0.0.1.00000000}.{x}#{2eef81be-33fa-4800-9670-1cd474972c3f}") == (
        "{0.0.1.00000000}.{x}"
    )
    assert unwrap_device_id(MMDEVICE_ID) == MMDEVICE_ID
    assert unwrap_device_id("") == ""


def test_interface_iid_by_build():
    assert interface_iid(19045) == "{2a59116d-6c4f-45e0-a74f-707e3fef9258}"
    assert interface_iid(21389) == "{2a59116d-6c4f-45e0-a74f-707e3fef9258}"
    assert interface_iid(21390) == "{ab3d4648-e242-459f-b02f-541c70306324}"
    assert interface_iid(26200) == "{ab3d4648-e242-459f-b02f-541c70306324}"
