"""Tests for the fraction-assignment record written to the patient source folder."""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from learn_upload.folder_sort import CBCTSession, LearnFolderMapper
from learn_upload.fraction_assignment import (
    MissingReference,
    TrajectoryGroundTruth,
    format_assignment_record,
    session_fraction_map,
    summarize_fractions,
)
from tests.test_folder_sort import _make_xvi_session


def _session(name, session_type, dt):
    return CBCTSession(
        img_dir=Path("X:/src") / name,
        dicom_uid=f"uid_{name}",
        acquisition_preset="preset",
        session_type=session_type,
        treatment_id="Prostate",
        scan_datetime=dt,
    )


def _fx_with_refs(root, name, ref_img_names, log_name="MarkerLocations_CouchShift_0.txt"):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    lines = "Frame, Filename\n" + "".join(
        rf"0, X:\p\IMAGES\{ref}\00001.his" + "\n" for ref in ref_img_names
    )
    (folder / log_name).write_text(lines, encoding="utf-8")
    return folder


# ---------------------------------------------------------------------------
# Capturing missing references
# ---------------------------------------------------------------------------

class TestMissingReferences:
    def test_records_uid_fraction_and_log_for_a_missing_session(self, tmp_path):
        _fx_with_refs(tmp_path, "FX01", ["img_1.3.46.1", "img_1.3.46.99"])
        present = _session("img_1.3.46.1", "motionview", datetime(2026, 6, 3, 10, 46))

        result = TrajectoryGroundTruth(tmp_path).assign([present])

        assert result.missing_references == [
            MissingReference(
                uid="img_1.3.46.99",
                fraction_label="FX01",
                log_name="FX01/MarkerLocations_CouchShift_0.txt",
            )
        ]

    def test_empty_when_every_reference_is_present(self, tmp_path):
        _fx_with_refs(tmp_path, "FX01", ["img_1.3.46.1"])
        present = _session("img_1.3.46.1", "motionview", datetime(2026, 6, 3, 10, 46))

        result = TrajectoryGroundTruth(tmp_path).assign([present])

        assert result.missing_references == []

    def test_attributes_each_missing_uid_to_its_own_fraction(self, tmp_path):
        _fx_with_refs(tmp_path, "FX01", ["img_1.3.46.11"])
        _fx_with_refs(tmp_path, "FX02", ["img_1.3.46.22"])

        result = TrajectoryGroundTruth(tmp_path).assign([])

        by_uid = {m.uid: m.fraction_label for m in result.missing_references}
        assert by_uid == {"img_1.3.46.11": "FX01", "img_1.3.46.22": "FX02"}

    def test_notes_are_still_produced_for_the_gui(self, tmp_path):
        """The GUI attention panel reads notes; the record is additive."""
        _fx_with_refs(tmp_path, "FX01", ["img_1.3.46.99"])

        result = TrajectoryGroundTruth(tmp_path).assign([])

        assert any("img_1.3.46.99" in n for n in result.notes)


# ---------------------------------------------------------------------------
# Formatting the record
# ---------------------------------------------------------------------------

class TestFormatAssignmentRecord:
    def test_lists_missing_references_in_a_table(self, tmp_path):
        _fx_with_refs(tmp_path, "FX01", ["img_1.3.46.1", "img_1.3.46.99"])
        present = _session("img_1.3.46.1", "motionview", datetime(2026, 6, 3, 10, 46))
        result = TrajectoryGroundTruth(tmp_path).assign([present])

        text = format_assignment_record(result, anon_id="PAT05", source_name="PAT05")

        assert "img_1.3.46.99" in text
        assert "FX01/MarkerLocations_CouchShift_0.txt" in text
        assert "PAT05" in text

    def test_states_explicitly_when_nothing_is_missing(self, tmp_path):
        _fx_with_refs(tmp_path, "FX01", ["img_1.3.46.1"])
        present = _session("img_1.3.46.1", "motionview", datetime(2026, 6, 3, 10, 46))
        result = TrajectoryGroundTruth(tmp_path).assign([present])

        text = format_assignment_record(result, anon_id="PAT05", source_name="PAT05")

        assert "None" in text

    def test_includes_the_final_assignment_with_type_and_date(self, tmp_path):
        _fx_with_refs(tmp_path, "FX01", ["img_1.3.46.1"])
        present = _session("img_1.3.46.1", "motionview", datetime(2026, 6, 3, 10, 46))
        result = TrajectoryGroundTruth(tmp_path).assign([present])

        text = format_assignment_record(result, anon_id="PAT05", source_name="PAT05")

        assert "img_1.3.46.1" in text
        assert "motionview" in text
        assert "2026-06-03" in text

    def test_reports_unmatched_sessions(self, tmp_path):
        _fx_with_refs(tmp_path, "FX01", ["img_1.3.46.1"])
        orphan = _session("img_9.9.9.9", "motionview", datetime(2026, 6, 4, 9, 0))
        result = TrajectoryGroundTruth(tmp_path).assign([orphan])

        text = format_assignment_record(result, anon_id="PAT05", source_name="PAT05")

        assert "img_9.9.9.9" in text


# ---------------------------------------------------------------------------
# Writing the record into the patient source folder
# ---------------------------------------------------------------------------

class TestWriteAssignmentRecord:
    def test_execute_writes_the_record_into_the_source_folder(self, tmp_path):
        patient_dir = _make_xvi_session(tmp_path, "img_001")
        out = tmp_path / "out"

        mapper = LearnFolderMapper(patient_dir, "PAT01", "Prostate", out)
        summary = mapper.execute(dry_run=False)

        record = patient_dir / "fraction_assignment_record_PAT01.md"
        assert record.is_file()
        assert summary["assignment_record"] == str(record)
        text = record.read_text(encoding="utf-8")
        assert "# Fraction assignment record - PAT01" in text
        assert "img_001" in text

    def test_written_even_when_nothing_is_missing(self, tmp_path):
        patient_dir = _make_xvi_session(tmp_path, "img_001")
        out = tmp_path / "out"

        LearnFolderMapper(patient_dir, "PAT01", "Prostate", out).execute(dry_run=False)

        text = (patient_dir / "fraction_assignment_record_PAT01.md").read_text(
            encoding="utf-8"
        )
        assert "None - every referenced session is present" in text

    def test_dry_run_writes_nothing(self, tmp_path):
        patient_dir = _make_xvi_session(tmp_path, "img_001")
        out = tmp_path / "out"

        summary = LearnFolderMapper(
            patient_dir, "PAT01", "Prostate", out
        ).execute(dry_run=True)

        assert not (patient_dir / "fraction_assignment_record_PAT01.md").exists()
        assert summary["assignment_record"] is None

    def test_rerun_overwrites_rather_than_accumulating(self, tmp_path):
        patient_dir = _make_xvi_session(tmp_path, "img_001")
        out = tmp_path / "out"

        mapper = LearnFolderMapper(patient_dir, "PAT01", "Prostate", out)
        mapper.execute(dry_run=False)
        mapper.execute(dry_run=False)

        assert len(list(patient_dir.glob("fraction_assignment_record_*.md"))) == 1

    def test_unwritable_source_warns_but_does_not_fail_the_sort(self, tmp_path):
        """A read-only network source must not abort a completed transfer."""
        patient_dir = _make_xvi_session(tmp_path, "img_001")
        out = tmp_path / "out"
        mapper = LearnFolderMapper(patient_dir, "PAT01", "Prostate", out)

        with patch(
            "learn_upload.folder_sort.Path.write_text",
            side_effect=OSError("read-only file system"),
        ):
            summary = mapper.execute(dry_run=False)

        assert summary["assignment_record"] is None
        assert summary["sessions"] == 1


# ---------------------------------------------------------------------------
# Preview helpers: per-session map and per-fraction summary
# ---------------------------------------------------------------------------

class TestSessionFractionMap:
    def test_maps_each_assigned_session_to_its_label(self, tmp_path):
        _fx_with_refs(tmp_path, "FX01", ["img_1.3.46.1"])
        kim = _session("img_1.3.46.1", "motionview", datetime(2026, 6, 3, 10, 46))
        cbct = _session("img_2.3.46.1", "cbct", datetime(2026, 6, 3, 10, 40))
        result = TrajectoryGroundTruth(tmp_path).assign([kim, cbct])

        assert session_fraction_map(result) == {
            "img_1.3.46.1": "FX01",
            "img_2.3.46.1": "FX01",
        }

    def test_unplaced_sessions_are_absent(self, tmp_path):
        _fx_with_refs(tmp_path, "FX01", ["img_1.3.46.1"])
        orphan = _session("img_9.9.9.9", "motionview", datetime(2026, 6, 4, 9, 0))
        result = TrajectoryGroundTruth(tmp_path).assign([orphan])

        assert "img_9.9.9.9" not in session_fraction_map(result)


class TestSummarizeFractions:
    def test_one_row_per_fraction_with_date_and_counts(self, tmp_path):
        _fx_with_refs(tmp_path, "FX01", ["img_1.3.46.1", "img_1.3.46.2"])
        kim = _session("img_1.3.46.1", "motionview", None)
        kl = _session("img_1.3.46.2", "kim_learning", datetime(2026, 6, 3, 10, 46))
        cbct = _session("img_2.3.46.1", "cbct", datetime(2026, 6, 3, 10, 40))
        result = TrajectoryGroundTruth(tmp_path).assign([kim, kl, cbct])

        [row] = summarize_fractions(result)

        assert row == {
            "label": "FX01",
            "date": "2026-06-03",
            "cbct": 2,       # cbct + kim_learning are both CBCT-like
            "kim_kv": 1,
            "missing": 0,
        }

    def test_fraction_with_only_missing_references_has_no_date(self, tmp_path):
        _fx_with_refs(tmp_path, "FX03", ["img_1.3.46.31", "img_1.3.46.32"])

        [row] = summarize_fractions(result := TrajectoryGroundTruth(tmp_path).assign([]))

        assert row["label"] == "FX03"
        assert row["date"] == ""
        assert row["cbct"] == 0 and row["kim_kv"] == 0
        assert row["missing"] == 2
        assert result.missing_references  # sanity: that is where the count came from

    def test_rows_follow_natural_fraction_order(self, tmp_path):
        for name in ("FX10", "FX2", "FX13-1", "FX13"):
            _fx_with_refs(tmp_path, name, [f"img_{name.lower()}"])

        labels = [r["label"] for r in summarize_fractions(TrajectoryGroundTruth(tmp_path).assign([]))]

        assert labels == ["FX2", "FX10", "FX13", "FX13-1"]
