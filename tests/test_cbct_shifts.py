"""Tests for the cbct-shifts report scripts.

``cbct-shifts/`` is not a package (the hyphen forbids it); the GUI imports it by
adding the directory to ``sys.path``, and so do these tests.
"""

import sys
from pathlib import Path

_CBCT_SHIFTS_DIR = Path(__file__).resolve().parent.parent / "cbct-shifts"
if str(_CBCT_SHIFTS_DIR) not in sys.path:
    sys.path.insert(0, str(_CBCT_SHIFTS_DIR))

from compare_rps_mosaiq import find_rps_files  # noqa: E402


def _rps(root: Path, fx: str, cbct: str) -> Path:
    p = root / fx / "CBCT" / cbct / "Registration file" / "reg.RPS.dcm"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"\x00")  # content irrelevant: labels come from the path
    return p


class TestFindRpsFiles:
    def test_labels_come_from_the_path(self, tmp_path):
        _rps(tmp_path, "FX11", "CBCT2")

        [rf] = find_rps_files(tmp_path)

        assert rf["fx"] == "FX11"
        assert rf["cbct"] == "CBCT2"

    def test_fx_label_is_found_regardless_of_case(self, tmp_path):
        """Trajectory folders are copied verbatim, so Fx01 and FX11 coexist."""
        _rps(tmp_path, "Fx01", "CBCT1")
        _rps(tmp_path, "FX11", "CBCT1")

        labels = sorted(rf["fx"] for rf in find_rps_files(tmp_path))

        assert labels == ["FX11", "Fx01"]

    def test_fx_label_is_reported_as_named_on_disk(self, tmp_path):
        """The report documents the directory path label, so casing is preserved."""
        _rps(tmp_path, "Fx09", "CBCT3")

        [rf] = find_rps_files(tmp_path)

        assert rf["fx"] == "Fx09"

    def test_cbct_parent_folder_is_not_mistaken_for_a_label(self, tmp_path):
        _rps(tmp_path, "FX02", "CBCT4")

        [rf] = find_rps_files(tmp_path)

        assert rf["cbct"] == "CBCT4"
