"""Tests for scripts/inventory_crawler.py."""
import sys
from pathlib import Path

import pytest

# Make scripts/ importable for tests
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _write_rtplan(path: Path, num_fractions: int | None) -> None:
    """Build a minimal RTPLAN DICOM. ``num_fractions=None`` skips the sequence."""
    pytest.importorskip("pydicom")
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.481.5"
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.Modality = "RTPLAN"
    if num_fractions is not None:
        fg = Dataset()
        fg.NumberOfFractionsPlanned = num_fractions
        ds.FractionGroupSequence = [fg]
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.save_as(str(path))


def _write_other_modality(path: Path, modality: str) -> None:
    """Build a minimal non-RTPLAN DICOM (used to verify Modality filtering)."""
    pytest.importorskip("pydicom")
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.481.3"
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.Modality = modality
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.save_as(str(path))


def _make_machine(root: Path, name: str, with_flexmap: bool) -> Path:
    machine = root / name
    machine.mkdir(parents=True)
    if with_flexmap:
        flex_dir = machine / "Current Calibration Files" / "Current" / "FlexMap"
        flex_dir.mkdir(parents=True)
        (flex_dir / "panel_a.flexmap").write_bytes(b"")
    return machine


# ---------------------------------------------------------------------------
# find_machines_with_flexmaps
# ---------------------------------------------------------------------------

class TestFindMachinesWithFlexmaps:
    def test_returns_only_flexmap_dirs(self, tmp_path):
        from inventory_crawler import find_machines_with_flexmaps

        yes_a = _make_machine(tmp_path, "20230101_CenterA_M1", with_flexmap=True)
        _make_machine(tmp_path, "20230101_CenterB_M2", with_flexmap=False)
        yes_b = _make_machine(tmp_path, "20230101_CenterC_M3", with_flexmap=True)

        result = find_machines_with_flexmaps(tmp_path)

        assert sorted(result) == sorted([yes_a, yes_b])

    def test_ignores_files_at_root(self, tmp_path):
        """Non-directory entries at the processed root must be ignored."""
        from inventory_crawler import find_machines_with_flexmaps

        (tmp_path / "stray_file.txt").write_text("hello")
        yes = _make_machine(tmp_path, "20230101_CenterA_M1", with_flexmap=True)

        assert find_machines_with_flexmaps(tmp_path) == [yes]

    def test_empty_root_returns_empty(self, tmp_path):
        from inventory_crawler import find_machines_with_flexmaps
        assert find_machines_with_flexmaps(tmp_path) == []

    def test_missing_root_returns_empty(self, tmp_path):
        from inventory_crawler import find_machines_with_flexmaps
        assert find_machines_with_flexmaps(tmp_path / "does_not_exist") == []


# ---------------------------------------------------------------------------
# find_patient_folders
# ---------------------------------------------------------------------------

class TestFindPatientFolders:
    def test_returns_only_patient_prefixed_dirs(self, tmp_path):
        from inventory_crawler import find_patient_folders

        machine = tmp_path / "20230101_CenterA_M1"
        (machine / "patient_00001234").mkdir(parents=True)
        (machine / "patient_00009999").mkdir()
        (machine / "Current Calibration Files").mkdir()
        (machine / "not_a_patient").mkdir()
        (machine / "stray.txt").write_text("x")

        result = find_patient_folders(machine)

        names = sorted(p.name for p in result)
        assert names == ["patient_00001234", "patient_00009999"]

    def test_missing_machine_returns_empty(self, tmp_path):
        from inventory_crawler import find_patient_folders
        assert find_patient_folders(tmp_path / "does_not_exist") == []


# ---------------------------------------------------------------------------
# Helpers for synthetic IMAGES/img_<UID>/ structures
# ---------------------------------------------------------------------------

def _make_img_dir(
    patient_dir: Path,
    img_uid: str,
    treatment_id: str,
    fov: str | None,
    scan_uid: str | None = None,
) -> Path:
    """Create a synthetic IMAGES/img_<UID>/ folder mirroring real XVI layout.

    Real-world layout under ``Reconstruction/`` contains two distinct file types:
      * ``<img_uid>.INI.XVI``       — contains FOV (plus reconstruction params)
      * ``<img_uid>.INI``           — contains ScanUID + FOV (plain INI form)
    Plus timestamp-suffixed siblings that the trawler must NOT pick by accident.
    """
    img_dir = patient_dir / "IMAGES" / f"img_{img_uid}"
    img_dir.mkdir(parents=True)

    # _Frames.xml with Treatment/ID
    frames = img_dir / "_Frames.xml"
    frames.write_text(
        f"""<?xml version="1.0"?>
<Frames>
  <Treatment><ID>{treatment_id}</ID></Treatment>
  <Image>
    <AcquisitionPresetName>SymmetricBody</AcquisitionPresetName>
    <DicomUID>1.2.3.{img_uid}</DicomUID>
    <kV>120</kV>
    <mA>20</mA>
  </Image>
</Frames>
""",
        encoding="utf-8",
    )

    if fov is not None or scan_uid is not None:
        recon = img_dir / "Reconstruction"
        recon.mkdir()
        # FOV in <img_uid>.INI.XVI (per user spec)
        if fov is not None:
            (recon / f"{img_uid}.INI.XVI").write_text(
                f"FOV={fov}\n", encoding="utf-8",
            )
        # ScanUID in plain <img_uid>.INI (per real-world layout)
        if scan_uid is not None:
            (recon / f"{img_uid}.INI").write_text(
                f"ScanUID={scan_uid}\n", encoding="utf-8",
            )

    return img_dir


# ---------------------------------------------------------------------------
# iter_img_records
# ---------------------------------------------------------------------------

class TestIterImgRecords:
    def test_yields_one_record_per_img_dir(self, tmp_path):
        from inventory_crawler import iter_img_records

        patient = tmp_path / "patient_00001234"
        patient.mkdir()
        _make_img_dir(
            patient, "abc1", "WholeBrain-C2Retrt", fov="small",
            scan_uid="1.3.46.423632.1.1.224.2023-03-21165402768",
        )
        _make_img_dir(patient, "abc2", "Lung-LUL", fov="medium")

        records = list(iter_img_records(patient))

        assert len(records) == 2
        by_uid = {r.img_uid: r for r in records}
        assert by_uid["abc1"].treatment_id == "WholeBrain-C2Retrt"
        assert by_uid["abc1"].fov == "small"
        assert by_uid["abc1"].scan_datetime is not None
        assert by_uid["abc2"].treatment_id == "Lung-LUL"
        assert by_uid["abc2"].fov == "medium"
        assert by_uid["abc2"].scan_datetime is None

    def test_handles_missing_frames_xml(self, tmp_path):
        from inventory_crawler import iter_img_records

        patient = tmp_path / "patient_00001234"
        img_dir = patient / "IMAGES" / "img_orphan"
        img_dir.mkdir(parents=True)
        # No _Frames.xml, no Reconstruction
        records = list(iter_img_records(patient))
        assert len(records) == 1
        assert records[0].img_uid == "orphan"
        assert records[0].treatment_id is None
        assert records[0].fov is None

    def test_handles_missing_ini_xvi(self, tmp_path):
        from inventory_crawler import iter_img_records

        patient = tmp_path / "patient_00001234"
        _make_img_dir(patient, "no_recon", "Pelvis-Prostate", fov=None)

        records = list(iter_img_records(patient))
        assert len(records) == 1
        assert records[0].treatment_id == "Pelvis-Prostate"
        assert records[0].fov is None

    def test_no_images_dir_returns_empty(self, tmp_path):
        from inventory_crawler import iter_img_records
        patient = tmp_path / "patient_99"
        patient.mkdir()
        assert list(iter_img_records(patient)) == []

    def test_prefers_bare_uid_ini_xvi_when_timestamp_sibling_present(self, tmp_path):
        """Real XVI layout has both <UID>.INI.XVI and <UID>.<datetime>.INI.XVI.

        The user spec says FOV lives in the BARE-UID file. Sorted alphabetically,
        the timestamped sibling actually comes first ('2' < 'I' in ASCII), so a
        naive ``sorted(...)[0]`` would pick the wrong file. Verify we pick the
        bare-UID file by exact name match.
        """
        from inventory_crawler import iter_img_records

        img_uid = "1.3.46.224"
        patient = tmp_path / "patient_001"
        img_dir = patient / "IMAGES" / f"img_{img_uid}"
        recon = img_dir / "Reconstruction"
        recon.mkdir(parents=True)
        # Frames.xml so iter_img_records doesn't bail
        (img_dir / "_Frames.xml").write_text(
            '<?xml version="1.0"?><Frames>'
            '<Treatment><ID>Brain-Whole</ID></Treatment>'
            '</Frames>',
            encoding="utf-8",
        )
        # Bare-UID file: the authoritative FOV source per spec
        (recon / f"{img_uid}.INI.XVI").write_text("FOV=small\n", encoding="utf-8")
        # Timestamped sibling: distractor (has different/no FOV)
        (recon / f"{img_uid}.2023-03-21165402768.INI.XVI").write_text(
            "ProjectionImageDimension=256\n", encoding="utf-8",
        )

        records = list(iter_img_records(patient))
        assert len(records) == 1
        assert records[0].fov == "small"

    def test_reads_scan_uid_from_plain_ini_not_ini_xvi(self, tmp_path):
        """ScanUID lives in <UID>.INI (per folder_sort.py:219), not <UID>.INI.XVI.

        Verify scan_datetime is populated when ScanUID is in the plain .INI file.
        """
        from inventory_crawler import iter_img_records

        img_uid = "1.3.46.224"
        patient = tmp_path / "patient_001"
        img_dir = patient / "IMAGES" / f"img_{img_uid}"
        recon = img_dir / "Reconstruction"
        recon.mkdir(parents=True)
        (img_dir / "_Frames.xml").write_text(
            '<?xml version="1.0"?><Frames>'
            '<Treatment><ID>Brain-Whole</ID></Treatment>'
            '</Frames>',
            encoding="utf-8",
        )
        # ScanUID only in the plain .INI
        (recon / f"{img_uid}.INI").write_text(
            "ScanUID=1.3.46.224.2023-03-21165402768\n", encoding="utf-8",
        )

        records = list(iter_img_records(patient))
        assert len(records) == 1
        assert records[0].scan_datetime is not None


# ---------------------------------------------------------------------------
# find_planned_fractions_for_patient
# ---------------------------------------------------------------------------

class TestFindPlannedFractionsForPatient:
    def test_reads_dicom_plan_dir(self, tmp_path):
        from inventory_crawler import find_planned_fractions_for_patient

        patient = tmp_path / "patient_00001234"
        plan_dir = patient / "DICOM_PLAN"
        plan_dir.mkdir(parents=True)

        _write_rtplan(plan_dir / "RP.001.dcm", num_fractions=30)
        # Add a non-RTPLAN file to ensure the function filters by Modality
        _write_other_modality(plan_dir / "RS.dcm", modality="RTSTRUCT")

        assert find_planned_fractions_for_patient(patient) == 30

    def test_no_dicom_returns_none(self, tmp_path):
        from inventory_crawler import find_planned_fractions_for_patient
        patient = tmp_path / "patient_00001234"
        patient.mkdir()
        assert find_planned_fractions_for_patient(patient) is None

    def test_falls_back_to_recursive_search(self, tmp_path):
        """If DICOM_PLAN doesn't contain an RTPLAN, search elsewhere under patient."""
        from inventory_crawler import find_planned_fractions_for_patient

        patient = tmp_path / "patient_00001234"
        odd_dir = patient / "MISC" / "PLANS"
        odd_dir.mkdir(parents=True)
        _write_rtplan(odd_dir / "weird_name.dcm", num_fractions=5)

        assert find_planned_fractions_for_patient(patient) == 5

    def test_dicom_plan_dir_with_only_non_rtplan_falls_back(self, tmp_path):
        """DICOM_PLAN exists but holds only RTSTRUCT — fallback should find RTPLAN elsewhere."""
        from inventory_crawler import find_planned_fractions_for_patient

        patient = tmp_path / "patient_99"
        plan_dir = patient / "DICOM_PLAN"
        plan_dir.mkdir(parents=True)
        _write_other_modality(plan_dir / "RS.dcm", modality="RTSTRUCT")

        elsewhere = patient / "elsewhere"
        elsewhere.mkdir()
        _write_rtplan(elsewhere / "plan.dcm", num_fractions=15)

        assert find_planned_fractions_for_patient(patient) == 15


# ---------------------------------------------------------------------------
# trawl_machine, trawl_root
# ---------------------------------------------------------------------------

class TestTrawlMachine:
    def test_combines_patient_and_image_data(self, tmp_path):
        from inventory_crawler import trawl_machine

        machine = tmp_path / "20230101_CenterA_M1"
        flex = machine / "Current Calibration Files" / "Current" / "FlexMap"
        flex.mkdir(parents=True)
        (flex / "x.flexmap").write_bytes(b"")

        patient = machine / "patient_00001234"
        patient.mkdir()
        _make_img_dir(patient, "img1", "Brain-Whole", fov="small")
        _make_img_dir(patient, "img2", "Brain-Whole", fov="medium")

        # No DICOM_PLAN -> planned_fractions=None
        records = trawl_machine(machine)

        assert len(records) == 2
        assert all(r.machine == "20230101_CenterA_M1" for r in records)
        assert all(r.patient_folder == "patient_00001234" for r in records)
        assert all(r.planned_fractions is None for r in records)
        fovs = sorted(r.fov for r in records)
        assert fovs == ["medium", "small"]

    def test_fills_planned_fractions_per_patient(self, tmp_path):
        """Each patient's RTPLAN fraction count should propagate to all their images."""
        from inventory_crawler import trawl_machine

        machine = tmp_path / "20230101_CenterA_M1"
        machine.mkdir()
        patient = machine / "patient_00001234"
        plan_dir = patient / "DICOM_PLAN"
        plan_dir.mkdir(parents=True)
        _write_rtplan(plan_dir / "plan.dcm", num_fractions=20)
        _make_img_dir(patient, "f1", "Lung-RUL", fov="small")
        _make_img_dir(patient, "f2", "Lung-RUL", fov="small")

        records = trawl_machine(machine)
        assert len(records) == 2
        assert all(r.planned_fractions == 20 for r in records)


class TestTrawlRoot:
    def test_skips_machines_without_flexmaps(self, tmp_path):
        from inventory_crawler import trawl_root

        # Machine A has flexmap and one patient/img
        a = _make_machine(tmp_path, "20230101_CenterA_M1", with_flexmap=True)
        a_pat = a / "patient_00001"
        a_pat.mkdir()
        _make_img_dir(a_pat, "abc", "Lung-RUL", fov="small")

        # Machine B has NO flexmap but has data — must be skipped entirely
        b = _make_machine(tmp_path, "20230101_CenterB_M2", with_flexmap=False)
        b_pat = b / "patient_99999"
        b_pat.mkdir()
        _make_img_dir(b_pat, "xyz", "Lung-LUL", fov="small")

        records = trawl_root(tmp_path)
        assert len(records) == 1
        assert records[0].machine == "20230101_CenterA_M1"
        assert records[0].treatment_id == "Lung-RUL"

    def test_empty_root_returns_empty(self, tmp_path):
        from inventory_crawler import trawl_root
        assert trawl_root(tmp_path) == []


# ---------------------------------------------------------------------------
# write_inventory_csv
# ---------------------------------------------------------------------------

class TestWriteInventoryCsv:
    def test_writes_headers_and_rows(self, tmp_path):
        import csv
        from datetime import datetime

        from inventory_crawler import ImgRecord, write_inventory_csv

        records = [
            ImgRecord(
                machine="20230101_CenterA_M1",
                patient_folder="patient_00001234",
                img_uid="abc",
                treatment_id="Brain-Whole",
                fov="small",
                scan_datetime=datetime(2023, 3, 21, 16, 54, 2),
                planned_fractions=30,
                img_dir=tmp_path / "fake",
            ),
            ImgRecord(
                machine="20230101_CenterA_M1",
                patient_folder="patient_00009999",
                img_uid="def",
                treatment_id=None,
                fov=None,
                scan_datetime=None,
                planned_fractions=None,
                img_dir=tmp_path / "fake2",
            ),
        ]
        out = tmp_path / "out.csv"
        write_inventory_csv(records, out)

        rows = list(csv.DictReader(out.open(encoding="utf-8")))
        assert len(rows) == 2
        assert rows[0]["machine"] == "20230101_CenterA_M1"
        assert rows[0]["patient_folder"] == "patient_00001234"
        assert rows[0]["img_uid"] == "abc"
        assert rows[0]["treatment_id"] == "Brain-Whole"
        assert rows[0]["fov"] == "small"
        assert rows[0]["planned_fractions"] == "30"
        assert rows[0]["scan_datetime"] == "2023-03-21T16:54:02"
        # Missing fields render as empty strings, not "None"
        assert rows[1]["treatment_id"] == ""
        assert rows[1]["fov"] == ""
        assert rows[1]["planned_fractions"] == ""
        assert rows[1]["scan_datetime"] == ""

    def test_creates_parent_dir(self, tmp_path):
        from inventory_crawler import write_inventory_csv
        out = tmp_path / "nested" / "dirs" / "inv.csv"
        write_inventory_csv([], out)
        assert out.exists()
        # Header-only file
        assert out.read_text(encoding="utf-8").strip().startswith("machine,patient_folder")


# ---------------------------------------------------------------------------
# main() CLI
# ---------------------------------------------------------------------------

class TestMain:
    def test_end_to_end_with_synthetic_root(self, tmp_path, capsys):
        """Run main() with --root and --output against a synthetic tree."""
        from inventory_crawler import main

        # Build a minimal world: one machine, one patient, one img
        machine = _make_machine(tmp_path, "20230101_CenterA_M1", with_flexmap=True)
        patient = machine / "patient_00001234"
        patient.mkdir()
        _make_img_dir(patient, "abc", "Brain-Whole", fov="small")

        output = tmp_path / "out.csv"
        rc = main([
            "--root", str(tmp_path),
            "--output", str(output),
            "--log-level", "WARNING",
        ])
        assert rc == 0
        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert "Brain-Whole" in content
        assert "small" in content
        assert "20230101_CenterA_M1" in content
