"""Tests for learn_upload.fraction_assignment — ground-truth fraction assignment."""

from datetime import date, datetime
from pathlib import Path

from learn_upload.folder_sort import CBCTSession
from learn_upload.fraction_assignment import (
    FractionResult,
    ManualDateTable,
    TrajectoryGroundTruth,
    apply_manual_assignments,
    base_number,
    build_date_to_fraction,
    build_fraction_result,
    discover_trajectory_folders,
    distinct_session_dates,
    format_fraction_label,
    fraction_sort_key,
    has_trajectory_folders,
    parse_trajectory_referenced_uids,
    select_base_label,
)


def test_parse_trajectory_referenced_uids_extracts_img_dirs(tmp_path):
    log = tmp_path / "MarkerLocations_CouchShift_0.txt"
    log.write_text(
        "Frame No, Time, Filename\n"
        r"0, 0.0, X:\patient_262083\IMAGES\img_1.3.46.423632.111.107\00001.1.3.46.423632.111.107.his"
        "\n"
        r"1, 0.4, X:\patient_262083\IMAGES\img_1.3.46.423632.222.113\00002.1.3.46.423632.222.113.his"
        "\n",
        encoding="utf-8",
    )

    uids = parse_trajectory_referenced_uids(log)

    assert uids == {
        "img_1.3.46.423632.111.107",
        "img_1.3.46.423632.222.113",
    }


def test_parse_trajectory_referenced_uids_stops_at_non_backslash_separator(tmp_path):
    # Forward-slash separator must not let the match bleed into the .his filename.
    log = tmp_path / "MarkerLocations.txt"
    log.write_text(
        "Frame, Filename\n"
        "0, /mnt/x/IMAGES/img_1.3.46.107/00001.1.3.46.107.his\n",
        encoding="utf-8",
    )

    assert parse_trajectory_referenced_uids(log) == {"img_1.3.46.107"}


def test_fraction_result_defaults_are_empty():
    r = FractionResult()
    assert r.assignments == {}
    assert r.fraction_labels == []
    assert r.unmatched == []
    assert r.ambiguous == []
    assert r.notes == []


def _make_fx_folder(root, name, with_log=True):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    if with_log:
        (folder / "MarkerLocations_CouchShift_0.txt").write_text("x", encoding="utf-8")
    return folder


def test_discover_trajectory_folders_only_includes_fx_with_logs(tmp_path):
    _make_fx_folder(tmp_path, "FX01")
    _make_fx_folder(tmp_path, "FX13")
    _make_fx_folder(tmp_path, "FX13-1")
    _make_fx_folder(tmp_path, "FX16", with_log=False)   # empty/future
    (tmp_path / "XVI Export").mkdir()                    # not an FX folder

    folders = discover_trajectory_folders(tmp_path)

    assert set(folders) == {"FX01", "FX13", "FX13-1"}


def test_base_number_strips_restart_suffix():
    assert base_number("FX13") == "13"
    assert base_number("FX13-1") == "13"
    assert base_number("bad") == "bad"   # non-matching label returned unchanged


def test_select_base_label_prefers_unsuffixed():
    assert select_base_label(["FX13-1", "FX13"]) == "FX13"
    assert select_base_label(["FX13-2", "FX13-1"]) == "FX13-1"


def test_fraction_sort_key_orders_naturally():
    labels = ["FX13-1", "FX2", "FX13", "FX1"]
    assert sorted(labels, key=fraction_sort_key) == ["FX1", "FX2", "FX13", "FX13-1"]


# ---------------------------------------------------------------------------
# TrajectoryGroundTruth helpers + tests
# ---------------------------------------------------------------------------


def _session(name, session_type, dt):
    return CBCTSession(
        img_dir=Path("X:/src") / name,
        dicom_uid=f"uid_{name}",
        acquisition_preset="preset",
        session_type=session_type,
        treatment_id="Prostate",
        scan_datetime=dt,
    )


def _fx_with_refs(root, name, ref_img_names):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    lines = "Frame, Filename\n" + "".join(
        rf"0, X:\p\IMAGES\{ref}\00001.his" + "\n" for ref in ref_img_names
    )
    (folder / "MarkerLocations_CouchShift_0.txt").write_text(lines, encoding="utf-8")
    return folder


def test_trajectory_assigns_kim_by_uid_and_cbct_by_date(tmp_path):
    _fx_with_refs(tmp_path, "FX01", ["img_1.3.46.1"])
    kim = _session("img_1.3.46.1", "motionview", datetime(2026, 6, 3, 10, 46))
    cbct = _session("img_2.3.46.1", "cbct", datetime(2026, 6, 3, 10, 40))

    result = TrajectoryGroundTruth(tmp_path).assign([kim, cbct])

    assert result.fraction_labels == ["FX01"]
    assert result.assignments["FX01"] == [kim, cbct]
    assert result.unmatched == []
    assert result.ambiguous == []


def test_restart_cbct_goes_to_base_kim_split_by_log(tmp_path):
    _fx_with_refs(tmp_path, "FX13", ["img_13.1"])
    _fx_with_refs(tmp_path, "FX13-1", ["img_13.2"])
    kim_a = _session("img_13.1", "motionview", datetime(2026, 6, 11, 10, 0))
    kim_b = _session("img_13.2", "motionview", datetime(2026, 6, 11, 10, 30))
    cbct = _session("img_13.9", "cbct", datetime(2026, 6, 11, 9, 50))

    result = TrajectoryGroundTruth(tmp_path).assign([kim_a, kim_b, cbct])

    # KIM-KV stays split by its own log; CBCT goes to the base fraction
    assert result.assignments["FX13"] == [kim_a, cbct]
    assert result.assignments["FX13-1"] == [kim_b]
    assert result.ambiguous == []


def test_unmatched_cbct_when_date_has_no_fraction(tmp_path):
    _fx_with_refs(tmp_path, "FX01", ["img_1.1"])
    kim = _session("img_1.1", "motionview", datetime(2026, 6, 3, 10, 0))
    stray_cbct = _session("img_9.9", "cbct", datetime(2026, 7, 1, 9, 0))

    result = TrajectoryGroundTruth(tmp_path).assign([kim, stray_cbct])

    assert result.unmatched == [stray_cbct]


def test_unmatched_kim_when_uid_not_referenced(tmp_path):
    _fx_with_refs(tmp_path, "FX01", ["img_1.1"])
    orphan_kim = _session("img_8.8", "motionview", datetime(2026, 6, 3, 10, 0))

    result = TrajectoryGroundTruth(tmp_path).assign([orphan_kim])

    assert orphan_kim in result.unmatched


def test_future_fraction_label_kept_with_no_sessions(tmp_path):
    _fx_with_refs(tmp_path, "FX01", ["img_1.1"])
    _fx_with_refs(tmp_path, "FX02", ["img_2.2"])   # referenced session absent from export
    kim = _session("img_1.1", "motionview", datetime(2026, 6, 3, 10, 0))

    result = TrajectoryGroundTruth(tmp_path).assign([kim])

    assert result.fraction_labels == ["FX01", "FX02"]
    assert result.assignments["FX02"] == []
    assert any("img_2.2" in n for n in result.notes)


def test_ambiguous_cbct_when_date_maps_to_two_base_fractions(tmp_path):
    # Two genuinely different fractions on the same calendar day (defensive case).
    _fx_with_refs(tmp_path, "FX01", ["img_1.1"])
    _fx_with_refs(tmp_path, "FX02", ["img_2.2"])
    kim1 = _session("img_1.1", "motionview", datetime(2026, 6, 3, 10, 0))
    kim2 = _session("img_2.2", "motionview", datetime(2026, 6, 3, 11, 0))
    cbct = _session("img_9.9", "cbct", datetime(2026, 6, 3, 9, 0))

    result = TrajectoryGroundTruth(tmp_path).assign([kim1, kim2, cbct])

    assert result.assignments["FX01"] == [kim1]
    assert result.assignments["FX02"] == [kim2]
    assert result.unmatched == []
    assert len(result.ambiguous) == 1
    amb_session, cands = result.ambiguous[0]
    assert amb_session is cbct
    assert cands == ["FX01", "FX02"]


def test_cbct_without_datetime_is_unmatched(tmp_path):
    _fx_with_refs(tmp_path, "FX01", ["img_1.1"])
    kim = _session("img_1.1", "motionview", datetime(2026, 6, 3, 10, 0))
    undated_cbct = _session("img_9.9", "cbct", None)

    result = TrajectoryGroundTruth(tmp_path).assign([kim, undated_cbct])

    assert undated_cbct in result.unmatched


def test_manual_date_table_assigns_by_date(tmp_path):
    s1 = _session("img_a", "cbct", datetime(2026, 6, 3, 10, 0))
    s2 = _session("img_b", "cbct", datetime(2026, 6, 5, 10, 0))
    s_blank = _session("img_c", "cbct", datetime(2026, 6, 9, 10, 0))
    s_undated = _session("img_d", "cbct", None)

    mapping = {date(2026, 6, 3): "FX1", date(2026, 6, 5): "FX2"}
    result = ManualDateTable(mapping).assign([s1, s2, s_blank, s_undated])

    assert result.fraction_labels == ["FX1", "FX2"]
    assert result.assignments["FX1"] == [s1]
    assert result.assignments["FX2"] == [s2]
    # date 06-09 not in table; undated session also can't be placed
    assert result.unmatched == [s_blank, s_undated]


# ---------------------------------------------------------------------------
# GUI helper pure functions (Task 6)
# ---------------------------------------------------------------------------


def test_has_trajectory_folders_detects_prime(tmp_path):
    assert has_trajectory_folders(tmp_path) is False
    _fx_with_refs(tmp_path, "FX01", ["img_1.1"])
    assert has_trajectory_folders(tmp_path) is True


def test_format_fraction_label():
    assert format_fraction_label("5") == "FX5"
    assert format_fraction_label(7) == "FX7"


def test_distinct_session_dates_sorted_unique():
    s1 = _session("a", "cbct", datetime(2026, 6, 5, 10, 0))
    s2 = _session("b", "cbct", datetime(2026, 6, 3, 9, 0))
    s3 = _session("c", "cbct", datetime(2026, 6, 5, 14, 0))
    assert distinct_session_dates([s1, s2, s3]) == [date(2026, 6, 3), date(2026, 6, 5)]


def test_build_date_to_fraction_skips_blank_and_validates():
    rows = {date(2026, 6, 3): "1", date(2026, 6, 5): "", date(2026, 6, 9): "2"}
    mapping, errors = build_date_to_fraction(rows)
    assert mapping == {date(2026, 6, 3): "FX1", date(2026, 6, 9): "FX2"}
    assert errors == []


def test_build_date_to_fraction_reports_bad_numbers():
    rows = {date(2026, 6, 3): "abc"}
    mapping, errors = build_date_to_fraction(rows)
    assert mapping == {}
    assert len(errors) == 1


def test_build_fraction_result_dispatches_by_mode(tmp_path):
    _fx_with_refs(tmp_path, "FX01", ["img_1.1"])
    kim = _session("img_1.1", "motionview", datetime(2026, 6, 3, 10, 0))
    cbct = _session("img_9.9", "cbct", datetime(2026, 6, 3, 9, 0))

    # trajectory (PRIME) mode uses TrajectoryGroundTruth
    fr = build_fraction_result([kim, cbct], source_root=tmp_path, mode="trajectory")
    assert fr.assignments["FX01"] == [kim, cbct]

    # manual mode uses ManualDateTable with the supplied date map
    fr2 = build_fraction_result(
        [cbct],
        source_root=tmp_path,
        mode="manual",
        date_to_fraction={date(2026, 6, 3): "FX5"},
    )
    assert fr2.assignments["FX5"] == [cbct]


def test_referenced_kim_learning_anchors_date_for_unreferenced_cbct(tmp_path):
    # The trajectory log references a (dated) KIM-Learning session, which anchors
    # the fraction's date; an unreferenced setup CBCT on the same day attaches.
    # The MotionView session is undated and need not provide a date.
    _fx_with_refs(tmp_path, "FX05", ["img_5.1", "img_5.2"])
    kim_learning = _session("img_5.1", "kim_learning", datetime(2026, 6, 7, 9, 0))
    motionview = _session("img_5.2", "motionview", None)   # undated KIM-KV
    setup_cbct = _session("img_9.9", "cbct", datetime(2026, 6, 7, 8, 30))  # unreferenced

    result = TrajectoryGroundTruth(tmp_path).assign(
        [kim_learning, motionview, setup_cbct]
    )

    assert result.assignments["FX05"] == [kim_learning, motionview, setup_cbct]
    assert result.unmatched == []
    assert result.ambiguous == []


def test_apply_manual_assignments_moves_unmatched(tmp_path):
    s1 = _session("img_a", "cbct", datetime(2026, 6, 3, 10, 0))
    s2 = _session("img_b", "cbct", datetime(2026, 6, 4, 10, 0))
    result = FractionResult(
        assignments={"FX01": [s1], "FX02": []},
        fraction_labels=["FX01", "FX02"],
        unmatched=[s2],
    )

    apply_manual_assignments(result, [s1, s2], {"img_b": "FX02"})

    assert result.assignments["FX02"] == [s2]
    assert result.unmatched == []


def test_apply_manual_assignments_resolves_ambiguous_and_creates_label(tmp_path):
    s1 = _session("img_a", "cbct", datetime(2026, 6, 3, 10, 0))
    result = FractionResult(
        assignments={"FX01": []},
        fraction_labels=["FX01"],
        ambiguous=[(s1, ["FX01", "FX02"])],
    )

    apply_manual_assignments(result, [s1], {"img_a": "FX09"})

    assert result.assignments["FX09"] == [s1]
    assert "FX09" in result.fraction_labels
    assert result.ambiguous == []


def test_apply_manual_assignments_ignores_unknown_and_blank(tmp_path):
    s1 = _session("img_a", "cbct", datetime(2026, 6, 3, 10, 0))
    result = FractionResult(assignments={"FX01": []}, fraction_labels=["FX01"], unmatched=[s1])

    apply_manual_assignments(result, [s1], {"img_a": "", "img_x": "FX01"})

    assert result.unmatched == [s1]   # blank label and unknown name both ignored
    assert result.assignments["FX01"] == []
