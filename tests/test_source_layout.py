"""Tests for learn_upload.source_layout — auto-detecting the source tree layout."""

from pathlib import Path

from learn_upload.source_layout import (
    detect_centroid_file,
    detect_images_subdir,
    detect_source_layout,
    detect_tps_export,
    detect_trajectory_dir,
)


def _img(root: Path, subdir: str, name: str) -> Path:
    d = root / subdir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "_Frames.xml").write_text("<FrameData/>", encoding="utf-8")
    (d / "00001.his").write_bytes(b"\x00")
    return d


def _fx(root: Path, name: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "MarkerLocations_CouchShift_0.txt").write_text("x", encoding="utf-8")
    return d


def _dcm(root: Path, rel: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x00")  # content irrelevant — detection keys on the .dcm suffix
    return p


def test_detect_images_subdir_named_folder(tmp_path):
    _img(tmp_path, "XVI Export", "img_1.1")
    _img(tmp_path, "XVI Export", "img_1.2")
    assert detect_images_subdir(tmp_path) == "XVI Export"


def test_detect_images_subdir_at_root(tmp_path):
    _img(tmp_path, ".", "img_1.1")
    assert detect_images_subdir(tmp_path) == "."


def test_detect_images_subdir_none_when_absent(tmp_path):
    (tmp_path / "random").mkdir()
    assert detect_images_subdir(tmp_path) is None


def test_detect_trajectory_dir(tmp_path):
    _fx(tmp_path, "FX01")
    _fx(tmp_path, "FX13-1")
    assert detect_trajectory_dir(tmp_path) == tmp_path


def test_detect_trajectory_dir_none_without_markerlocations(tmp_path):
    (tmp_path / "FX01").mkdir()  # FX folder but no trajectory files
    assert detect_trajectory_dir(tmp_path) is None


def test_detect_tps_export_excludes_images_tree(tmp_path):
    _img(tmp_path, "XVI Export", "img_1.1")
    _dcm(tmp_path / "XVI Export" / "img_1.1" / "Reconstruction", "reg.dcm")  # RPS noise
    _dcm(tmp_path, "TPS Calculated/dose.dcm")
    tps = detect_tps_export(tmp_path, images_subdir="XVI Export")
    assert tps == tmp_path / "TPS Calculated"


def test_detect_tps_export_none_when_only_images_dcm(tmp_path):
    _img(tmp_path, "XVI Export", "img_1.1")
    _dcm(tmp_path / "XVI Export" / "img_1.1" / "Reconstruction", "reg.dcm")
    assert detect_tps_export(tmp_path, images_subdir="XVI Export") is None


def test_detect_centroid_file(tmp_path):
    (tmp_path / "extras").mkdir()
    target = tmp_path / "extras" / "Centroid_12345_BeamID_1.1.txt"
    target.write_text("x", encoding="utf-8")
    assert detect_centroid_file(tmp_path) == target


def test_detect_centroid_file_none(tmp_path):
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    assert detect_centroid_file(tmp_path) is None


def test_detect_source_layout_combined(tmp_path):
    _img(tmp_path, "XVI Export", "img_1.1")
    _fx(tmp_path, "FX01")
    _dcm(tmp_path, "TPS/dose.dcm")
    (tmp_path / "Centroid_9_BeamID_1.txt").write_text("x", encoding="utf-8")

    layout = detect_source_layout(tmp_path)

    assert layout["images_subdir"] == "XVI Export"
    assert layout["trajectory_dir"] == str(tmp_path)
    assert layout["tps_path"] == str(tmp_path / "TPS")
    assert layout["centroid_path"] == str(tmp_path / "Centroid_9_BeamID_1.txt")
