"""Tests for learn_upload.anonymise_dicom — DicomAnonymiser."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pydicom
import pytest
from pydicom.dataset import FileDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from learn_upload.anonymise_dicom import (
    DicomAnonymiser,
    anonymise_centroid_file,
    anonymise_dicom_file,
    anonymise_ini_file,
    anonymise_output_folder,
    anonymise_trajectory_log,
    inspect_tps_export,
)

# ---------------------------------------------------------------------------
# Helper: create a minimal synthetic DICOM file
# ---------------------------------------------------------------------------

def _make_test_dicom(
    directory: Path,
    filename: str = "test.DCM",
    patient_name: str = "Doe^John",
    patient_id: str = "12345678",
    patient_birth_date: str = "19800101",
    institution_name: str = "Test Hospital",
    study_id: str = "STUDY1",
    patient_sex: str = "M",
    patient_age: str = "044Y",
    study_description: str = "CT Head",
    modality: str = "CT",
) -> Path:
    """Create a minimal valid DICOM file for testing."""
    directory.mkdir(parents=True, exist_ok=True)
    filepath = directory / filename

    file_meta = pydicom.Dataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"  # CT
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(str(filepath), {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    # Tags that should be REPLACED with anon_id
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.StudyID = study_id

    # Tags that should be CLEARED
    ds.PatientBirthDate = patient_birth_date
    ds.AccessionNumber = "ACC001"
    ds.InstitutionName = institution_name
    ds.InstitutionAddress = "123 Test St"
    ds.ReferringPhysicianName = "Smith^Alice"
    ds.PhysiciansOfRecord = "Jones^Bob"
    ds.OperatorsName = "Operator^One"

    # Tags that should be PRESERVED
    ds.PatientSex = patient_sex
    ds.PatientAge = patient_age
    ds.StudyDescription = study_description
    ds.Modality = modality

    # UIDs that must be preserved
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID

    ds.save_as(filepath)
    return filepath


# ---------------------------------------------------------------------------
# Tests: anonymise_file
# ---------------------------------------------------------------------------

class TestAnonymiseFile:
    def test_replaces_tags(self, tmp_path):
        patient_dir = tmp_path / "patient_00000001"
        dcm_path = _make_test_dicom(patient_dir / "CT_SET", "slice.DCM")
        output_dir = tmp_path / "output"

        anon = DicomAnonymiser(patient_dir, "PAT01", output_dir)
        out = anon.anonymise_file(dcm_path)

        ds = pydicom.dcmread(out)
        assert str(ds.PatientName) == "PAT01^"
        assert ds.PatientID == "PAT01"
        assert ds.StudyID == "PAT01"

    def test_clears_tags(self, tmp_path):
        patient_dir = tmp_path / "patient_00000001"
        dcm_path = _make_test_dicom(patient_dir / "CT_SET", "slice.DCM")
        output_dir = tmp_path / "output"

        anon = DicomAnonymiser(patient_dir, "PAT01", output_dir)
        out = anon.anonymise_file(dcm_path)

        ds = pydicom.dcmread(out)
        assert ds.PatientBirthDate == ""
        assert ds.AccessionNumber == ""
        assert ds.InstitutionName == ""
        assert ds.InstitutionAddress == ""
        assert str(ds.ReferringPhysicianName) == ""
        assert str(ds.PhysiciansOfRecord) == ""
        assert str(ds.OperatorsName) == ""

    def test_preserves_uids(self, tmp_path):
        patient_dir = tmp_path / "patient_00000001"
        dcm_path = _make_test_dicom(patient_dir / "CT_SET", "slice.DCM")
        output_dir = tmp_path / "output"

        original = pydicom.dcmread(dcm_path)
        orig_study_uid = original.StudyInstanceUID
        orig_series_uid = original.SeriesInstanceUID
        orig_sop_uid = original.SOPInstanceUID

        anon = DicomAnonymiser(patient_dir, "PAT01", output_dir)
        out = anon.anonymise_file(dcm_path)

        ds = pydicom.dcmread(out)
        assert ds.StudyInstanceUID == orig_study_uid
        assert ds.SeriesInstanceUID == orig_series_uid
        assert ds.SOPInstanceUID == orig_sop_uid

    def test_preserves_research_tags(self, tmp_path):
        patient_dir = tmp_path / "patient_00000001"
        dcm_path = _make_test_dicom(
            patient_dir / "CT_SET", "slice.DCM",
            patient_sex="F", patient_age="055Y", study_description="Pelvis RT",
        )
        output_dir = tmp_path / "output"

        anon = DicomAnonymiser(patient_dir, "PAT02", output_dir)
        out = anon.anonymise_file(dcm_path)

        ds = pydicom.dcmread(out)
        assert ds.PatientSex == "F"
        assert ds.PatientAge == "055Y"
        assert ds.StudyDescription == "Pelvis RT"

    def test_missing_optional_tag(self, tmp_path):
        """File without InstitutionName in DICOM_TAGS_CLEAR doesn't crash."""
        patient_dir = tmp_path / "patient_00000001"
        dcm_path = _make_test_dicom(patient_dir / "CT_SET", "slice.DCM")

        # Remove InstitutionName from the file before anonymising
        ds = pydicom.dcmread(dcm_path)
        del ds.InstitutionName
        ds.save_as(dcm_path)

        output_dir = tmp_path / "output"
        anon = DicomAnonymiser(patient_dir, "PAT01", output_dir)
        out = anon.anonymise_file(dcm_path)

        result = pydicom.dcmread(out)
        assert str(result.PatientName) == "PAT01^"
        # InstitutionName should still be absent (not created)
        assert (0x0008, 0x0080) not in result


class TestAnonymiseSingleDicomFile:
    def test_anonymises_one_dose_file_without_patient_directory(self, tmp_path):
        source_dir = tmp_path / "incoming"
        dose_path = _make_test_dicom(
            source_dir,
            "RTDose(SMITH JOHN).dcm",
            patient_name="SMITH^JOHN",
            patient_id="12345678",
            study_description="Dose for 12345678",
        )
        output_path = tmp_path / "resend" / "RTDose_anon.dcm"

        result = anonymise_dicom_file(
            input_path=dose_path,
            output_path=output_path,
            anon_id="PAT42",
            site_name="Prostate",
        )

        assert result == output_path
        anon_ds = pydicom.dcmread(output_path)
        assert str(anon_ds.PatientName) == "PAT42^Prostate"
        assert anon_ds.PatientID == "PAT42"
        assert anon_ds.StudyID == "PAT42"
        assert anon_ds.PatientBirthDate == ""
        assert anon_ds.InstitutionName == ""
        assert anon_ds.StudyDescription == "Dose for PAT42"

        original_ds = pydicom.dcmread(dose_path)
        assert original_ds.PatientID == "12345678"
        assert "12345678" in original_ds.StudyDescription

    def test_single_file_preserves_uids(self, tmp_path):
        dose_path = _make_test_dicom(tmp_path / "incoming", "dose.dcm")
        original = pydicom.dcmread(dose_path)

        output_path = tmp_path / "out" / "dose.dcm"
        anonymise_dicom_file(dose_path, output_path, "PAT01")

        result = pydicom.dcmread(output_path)
        assert result.StudyInstanceUID == original.StudyInstanceUID
        assert result.SeriesInstanceUID == original.SeriesInstanceUID
        assert result.SOPInstanceUID == original.SOPInstanceUID


class TestInspectTpsExport:
    def test_reports_expected_tps_categories_and_counts(self, tmp_path):
        tps = tmp_path / "TPS Export"
        _make_test_dicom(tps / "DICOM CT Images", "ct1.dcm", modality="CT")
        _make_test_dicom(tps / "DICOM CT Images", "ct2.DCM", modality="CT")
        _make_test_dicom(tps / "DICOM RT Plan", "plan.dcm", modality="RTPLAN")
        _make_test_dicom(tps / "DICOM RT Dose", "dose.dcm", modality="RTDOSE")

        report = inspect_tps_export(tps)

        assert report["provided"] is True
        assert report["exists"] is True
        assert report["total_count"] == 4
        assert report["categories"]["ct"]["count"] == 2
        assert report["categories"]["plan"]["count"] == 1
        assert report["categories"]["structures"]["count"] == 0
        assert report["categories"]["dose"]["count"] == 1
        assert "structures" in report["missing"]
        assert report["warnings"] == ["Missing TPS DICOM categories: structures"]

    def test_missing_tps_path_is_non_blocking_warning(self, tmp_path):
        report = inspect_tps_export(tmp_path / "does-not-exist")

        assert report["provided"] is True
        assert report["exists"] is False
        assert report["total_count"] == 0
        assert report["missing"] == ["ct", "plan", "structures", "dose"]
        assert report["warnings"] == ["TPS export path not found"]

    def test_blank_tps_path_has_no_warning(self):
        report = inspect_tps_export(None)

        assert report["provided"] is False
        assert report["exists"] is False
        assert report["warnings"] == []


class TestTpsDiscoveryByModality:
    """TPS DICOM files are classified by their DICOM Modality tag, not by the
    name of the folder they happen to sit in (real exports put the calculated
    dose in folders like 'TPS Calculated', not 'DICOM RT Dose')."""

    def test_finds_dose_in_nonstandard_folder(self, tmp_path):
        tps = tmp_path / "TPS Export"
        _make_test_dicom(tps / "DICOM CT Images", "ct1.dcm", modality="CT")
        _make_test_dicom(tps / "DICOM RT Plan", "plan.dcm", modality="RTPLAN")
        _make_test_dicom(
            tps / "DICOM RT Structures", "ss.dcm", modality="RTSTRUCT"
        )
        # Dose lives in a non-standard folder name
        _make_test_dicom(tps / "TPS Calculated", "calc.dcm", modality="RTDOSE")

        report = inspect_tps_export(tps)

        assert report["categories"]["ct"]["count"] == 1
        assert report["categories"]["plan"]["count"] == 1
        assert report["categories"]["structures"]["count"] == 1
        assert report["categories"]["dose"]["count"] == 1
        assert report["missing"] == []
        assert report["total_count"] == 4

    def test_ignores_non_target_modalities(self, tmp_path):
        tps = tmp_path / "TPS Export"
        _make_test_dicom(tps / "DICOM RT Images", "epid.dcm", modality="RTIMAGE")

        report = inspect_tps_export(tps)

        assert report["total_count"] == 0
        assert set(report["missing"]) == {"ct", "plan", "structures", "dose"}

    def test_imports_dose_from_nonstandard_folder(self, tmp_path):
        output_dir, patient_dir, site_name = _build_output_tree(tmp_path)

        tps = tmp_path / "tps_export"
        _make_test_dicom(tps / "TPS Calculated", "calc_dose.dcm", modality="RTDOSE")

        counts = anonymise_output_folder(
            output_dir=output_dir,
            anon_id="PAT01",
            site_name=site_name,
            patient_dir=patient_dir,
            tps_path=tps,
        )

        assert counts["tps_imported"] == 1
        dose_dir = output_dir / site_name / "Patient Plans" / "PAT01" / "Dose"
        # Dedupe by resolved path: globbing is case-insensitive on Windows.
        dcm_files = {
            p.resolve() for p in dose_dir.rglob("*") if p.suffix.lower() == ".dcm"
        }
        assert len(dcm_files) == 1
        ds = pydicom.dcmread(next(iter(dcm_files)))
        assert ds.PatientID == "PAT01"
        assert ds.Modality == "RTDOSE"


# ---------------------------------------------------------------------------
# Tests: anonymise_ct_set / anonymise_plan
# ---------------------------------------------------------------------------

class TestAnonymiseCtSet:
    def test_anonymises_all_files(self, tmp_path):
        patient_dir = tmp_path / "patient_00000001"
        _make_test_dicom(patient_dir / "CT_SET", "slice1.DCM")
        _make_test_dicom(patient_dir / "CT_SET", "slice2.dcm")  # lowercase ext
        output_dir = tmp_path / "output"

        anon = DicomAnonymiser(patient_dir, "PAT01", output_dir)
        results = anon.anonymise_ct_set()

        assert len(results) == 2
        for p in results:
            ds = pydicom.dcmread(p)
            assert ds.PatientID == "PAT01"


class TestAnonymisePlan:
    def test_anonymises_all_files(self, tmp_path):
        patient_dir = tmp_path / "patient_00000001"
        _make_test_dicom(patient_dir / "DICOM_PLAN", "plan.DCM")
        output_dir = tmp_path / "output"

        anon = DicomAnonymiser(patient_dir, "PAT01", output_dir)
        results = anon.anonymise_plan()

        assert len(results) == 1
        ds = pydicom.dcmread(results[0])
        assert ds.PatientID == "PAT01"


# ---------------------------------------------------------------------------
# Tests: anonymise_all
# ---------------------------------------------------------------------------

class TestAnonymiseAll:
    def test_summary_counts(self, tmp_path):
        patient_dir = tmp_path / "patient_00000001"
        _make_test_dicom(patient_dir / "CT_SET", "s1.DCM")
        _make_test_dicom(patient_dir / "CT_SET", "s2.DCM")
        _make_test_dicom(patient_dir / "DICOM_PLAN", "plan.DCM")
        output_dir = tmp_path / "output"

        anon = DicomAnonymiser(patient_dir, "PAT03", output_dir)
        summary = anon.anonymise_all()

        assert summary == {"ct_count": 2, "plan_count": 1, "anon_id": "PAT03"}


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------

class TestPatientNameFormat:
    def test_patient_name_with_site(self, tmp_path):
        """PatientName set to AnonID^SiteName when site_name provided."""
        patient_dir = tmp_path / "patient_00000001"
        dcm_path = _make_test_dicom(patient_dir / "CT_SET", "slice.DCM")
        output_dir = tmp_path / "output"

        anon = DicomAnonymiser(patient_dir, "PAT01", output_dir, site_name="Prostate")
        out = anon.anonymise_file(dcm_path)

        ds = pydicom.dcmread(out)
        assert str(ds.PatientName) == "PAT01^Prostate"

    def test_patient_name_without_site(self, tmp_path):
        """PatientName set to AnonID^ when site_name is empty."""
        patient_dir = tmp_path / "patient_00000001"
        dcm_path = _make_test_dicom(patient_dir / "CT_SET", "slice.DCM")
        output_dir = tmp_path / "output"

        anon = DicomAnonymiser(patient_dir, "PAT01", output_dir)
        out = anon.anonymise_file(dcm_path)

        ds = pydicom.dcmread(out)
        assert str(ds.PatientName) == "PAT01^"


class TestAnonymiseAllDcm:
    def test_recursive_discovery(self, tmp_path):
        """anonymise_all_dcm finds .dcm files in nested directories."""
        patient_dir = tmp_path / "patient_00000001"
        patient_dir.mkdir()
        source = tmp_path / "tps_export"
        # Create files in various nested dirs
        _make_test_dicom(source / "CT_SET", "slice1.DCM")
        _make_test_dicom(source / "DICOM_PLAN", "plan.dcm")
        _make_test_dicom(source / "deep" / "nested", "struct.dcm")
        output_dir = tmp_path / "output"

        anon = DicomAnonymiser(patient_dir, "PAT01", output_dir, site_name="Brain")
        results = anon.anonymise_all_dcm(source)

        assert len(results) == 3
        for p in results:
            ds = pydicom.dcmread(p)
            assert str(ds.PatientName) == "PAT01^Brain"
            assert ds.PatientID == "PAT01"

    def test_empty_source_dir(self, tmp_path):
        patient_dir = tmp_path / "patient_00000001"
        patient_dir.mkdir()
        source = tmp_path / "empty_source"
        source.mkdir()
        output_dir = tmp_path / "output"

        anon = DicomAnonymiser(patient_dir, "PAT01", output_dir)
        results = anon.anonymise_all_dcm(source)
        assert results == []

    def test_nonexistent_source_dir(self, tmp_path):
        patient_dir = tmp_path / "patient_00000001"
        patient_dir.mkdir()

        anon = DicomAnonymiser(patient_dir, "PAT01", tmp_path / "output")
        results = anon.anonymise_all_dcm(tmp_path / "does_not_exist")
        assert results == []


class TestFilenameAnonymised:
    def test_parenthesised_name_replaced(self, tmp_path):
        """Parenthesised patient name in filename replaced with anon_id."""
        patient_dir = tmp_path / "patient_00000001"
        dcm_path = _make_test_dicom(
            patient_dir / "DICOM_PLAN",
            "DCMRT_Plan(SMITH JOHN).dcm",
            patient_name="SMITH JOHN",
        )
        output_dir = tmp_path / "output"

        anon = DicomAnonymiser(patient_dir, "PAT01", output_dir)
        out = anon.anonymise_file(dcm_path)

        assert out.name == "DCMRT_Plan(PAT01).dcm"
        assert "SMITH" not in out.name

    def test_no_parens_unchanged(self, tmp_path):
        """Filenames without parentheses are unchanged."""
        patient_dir = tmp_path / "patient_00000001"
        dcm_path = _make_test_dicom(patient_dir / "CT_SET", "slice001.DCM")
        output_dir = tmp_path / "output"

        anon = DicomAnonymiser(patient_dir, "PAT01", output_dir)
        out = anon.anonymise_file(dcm_path)

        assert out.name == "slice001.DCM"


class TestAnonymiseFileCustomSourceBase:
    def test_relative_path_from_custom_base(self, tmp_path):
        """source_base parameter controls relative path computation."""
        patient_dir = tmp_path / "patient_00000001"
        patient_dir.mkdir()
        # Source is outside the patient dir
        tps_root = tmp_path / "tps_export"
        dcm_path = _make_test_dicom(tps_root / "sub" / "CT", "slice.DCM")
        output_dir = tmp_path / "output"

        anon = DicomAnonymiser(patient_dir, "PAT01", output_dir)
        out = anon.anonymise_file(dcm_path, source_base=tps_root)

        # Output should mirror the relative path from tps_root
        assert out == output_dir / "sub" / "CT" / "slice.DCM"
        assert out.exists()


class TestAnonymiseFramesXml:
    _SAMPLE_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<FrameData>
    <Patient>
        <FirstName>JOHN</FirstName>
        <LastName>SMITH</LastName>
        <ID>12345678</ID>
    </Patient>
    <Treatment>
        <ID>Prostate</ID>
        <Description>Plan for 12345678 prostate treatment</Description>
    </Treatment>
    <Image>
        <AcquisitionPresetName>4ee Pelvis Soft S20</AcquisitionPresetName>
        <DicomUID>1.3.46.001</DicomUID>
    </Image>
</FrameData>
"""

    def test_anonymise_frames_xml(self, tmp_path):
        """Patient name, ID replaced; MRN scrubbed from description."""
        patient_dir = tmp_path / "patient_12345678"
        patient_dir.mkdir()
        xml_file = patient_dir / "_Frames.xml"
        xml_file.write_text(self._SAMPLE_XML, encoding="utf-8")

        output_path = tmp_path / "out" / "_Frames.xml"
        anon = DicomAnonymiser(patient_dir, "PRIME001", tmp_path / "staging")
        result = anon.anonymise_frames_xml(xml_file, output_path)

        assert result == output_path
        assert output_path.exists()

        tree = ET.parse(output_path)
        root = tree.getroot()

        patient = root.find("Patient")
        assert patient.find("FirstName").text == "" or patient.find("FirstName").text is None
        assert patient.find("LastName").text == "PRIME001"
        assert patient.find("ID").text == "PRIME001"

        desc = root.find("Treatment").find("Description").text
        assert "12345678" not in desc
        assert "PRIME001" in desc

        # Non-PII tags unchanged
        assert root.find("Treatment").find("ID").text == "Prostate"
        assert root.find("Image").find("DicomUID").text == "1.3.46.001"

    def test_anonymise_frames_xml_missing_tags(self, tmp_path):
        """Gracefully handles XML without Patient element."""
        patient_dir = tmp_path / "patient_00000001"
        patient_dir.mkdir()
        minimal_xml = """\
<?xml version="1.0" encoding="utf-8"?>
<FrameData>
    <Treatment><ID>Brain</ID></Treatment>
    <Image><AcquisitionPresetName>preset</AcquisitionPresetName></Image>
</FrameData>
"""
        xml_file = patient_dir / "_Frames.xml"
        xml_file.write_text(minimal_xml, encoding="utf-8")

        output_path = tmp_path / "out" / "_Frames.xml"
        anon = DicomAnonymiser(patient_dir, "PAT01", tmp_path / "staging")
        result = anon.anonymise_frames_xml(xml_file, output_path)

        assert result == output_path
        assert output_path.exists()

        tree = ET.parse(output_path)
        root = tree.getroot()
        # Patient element absent — should not crash
        assert root.find("Patient") is None
        assert root.find("Treatment").find("ID").text == "Brain"


class TestEdgeCases:
    def test_missing_ct_set_dir(self, tmp_path):
        patient_dir = tmp_path / "patient_00000001"
        patient_dir.mkdir()
        output_dir = tmp_path / "output"

        anon = DicomAnonymiser(patient_dir, "PAT01", output_dir)
        assert anon.anonymise_ct_set() == []

    def test_missing_patient_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            DicomAnonymiser(tmp_path / "nonexistent", "PAT01", tmp_path / "out")

    def test_output_dir_created(self, tmp_path):
        patient_dir = tmp_path / "patient_00000001"
        _make_test_dicom(patient_dir / "CT_SET", "s1.DCM")
        output_dir = tmp_path / "deeply" / "nested" / "output"

        assert not output_dir.exists()

        anon = DicomAnonymiser(patient_dir, "PAT01", output_dir)
        anon.anonymise_ct_set()

        assert output_dir.exists()
        assert (output_dir / "CT_SET" / "s1.DCM").exists()


# ---------------------------------------------------------------------------
# Tests: anonymise_ini_file
# ---------------------------------------------------------------------------

class TestAnonymiseIniFile:
    def test_replaces_pii_fields(self, tmp_path):
        ini = tmp_path / "recon.INI"
        ini.write_text(
            "PatientID=12345678\n"
            "FirstName=JOHN\n"
            "LastName=SMITH\n"
            "VoxelSize=1.0\n"
            "SliceThickness=2.5\n",
            encoding="utf-8",
        )

        anonymise_ini_file(ini, "PAT01")

        text = ini.read_text(encoding="utf-8")
        assert "PatientID=PAT01" in text
        assert "FirstName=" in text and "FirstName=JOHN" not in text
        assert "LastName=PAT01" in text
        # Non-PII lines unchanged
        assert "VoxelSize=1.0" in text
        assert "SliceThickness=2.5" in text

    def test_ini_xvi_extension(self, tmp_path):
        ini = tmp_path / "recon.INI.XVI"
        ini.write_text(
            "PatientID=87654321\n"
            "FirstName=JANE\n"
            "LastName=DOE\n"
            "Rows=512\n",
            encoding="utf-8",
        )

        anonymise_ini_file(ini, "PAT02")

        text = ini.read_text(encoding="utf-8")
        assert "PatientID=PAT02" in text
        assert "FirstName=JANE" not in text
        assert "LastName=PAT02" in text
        assert "Rows=512" in text


# ---------------------------------------------------------------------------
# Tests: anonymise_centroid_file
# ---------------------------------------------------------------------------

class TestAnonymiseCentroidFile:
    def test_replaces_first_two_lines(self, tmp_path):
        f = tmp_path / "centroid.txt"
        f.write_text("12345678\nSMITH JOHN\ndata line\n", encoding="utf-8")

        result = anonymise_centroid_file(f, "PAT01")

        lines = result.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "PAT01"
        assert lines[1] == "PAT01"
        assert lines[2] == "data line"

    def test_renames_file_with_mrn(self, tmp_path):
        f = tmp_path / "Centroid_12345678.txt"
        f.write_text("12345678\nSMITH JOHN\ncoords\n", encoding="utf-8")

        result = anonymise_centroid_file(f, "PAT01")

        assert result.name == "Centroid_PAT01.txt"
        assert result.exists()
        assert not f.exists()

    def test_no_rename_without_mrn(self, tmp_path):
        f = tmp_path / "centroid.txt"
        f.write_text("12345678\nSMITH JOHN\ncoords\n", encoding="utf-8")

        result = anonymise_centroid_file(f, "PAT01")

        assert result == f
        assert result.exists()


# ---------------------------------------------------------------------------
# Tests: anonymise_trajectory_log
# ---------------------------------------------------------------------------

class TestAnonymiseTrajectoryLog:
    def test_replaces_patient_id(self, tmp_path):
        f = tmp_path / "MarkerLocations01.txt"
        f.write_text(
            "path=patient_12345678/data\n"
            "ref=patient_12345678\n"
            "other line\n",
            encoding="utf-8",
        )

        anonymise_trajectory_log(f, "12345678", "PAT01")

        text = f.read_text(encoding="utf-8")
        assert "patient_PAT01" in text
        assert "patient_12345678" not in text
        assert "other line" in text

    def test_empty_original_id_no_change(self, tmp_path):
        f = tmp_path / "MarkerLocations01.txt"
        original = "path=patient_12345678/data\nother\n"
        f.write_text(original, encoding="utf-8")

        anonymise_trajectory_log(f, "", "PAT01")

        assert f.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# Tests: anonymise_output_folder
# ---------------------------------------------------------------------------

_FRAMES_XML_PII = """\
<?xml version="1.0" encoding="utf-8"?>
<FrameData>
    <Patient>
        <FirstName>JOHN</FirstName>
        <LastName>SMITH</LastName>
        <ID>12345678</ID>
    </Patient>
    <Treatment><ID>Prostate</ID></Treatment>
</FrameData>
"""


def _build_output_tree(tmp_path):
    """Build a realistic output folder structure for anonymise_output_folder tests.

    Returns (output_dir, patient_dir, site_name).
    """
    site_name = "Prostate"
    output_dir = tmp_path / "output"
    site_root = output_dir / site_name

    # Patient Images — CBCT with _Frames.xml, INI, .his
    cbct = site_root / "Patient Images" / "PAT01" / "FX1" / "CBCT" / "CBCT1"
    cbct.mkdir(parents=True)
    (cbct / "_Frames.xml").write_text(_FRAMES_XML_PII, encoding="utf-8")

    recon = cbct / "Reconstructed CBCT"
    recon.mkdir()
    (recon / "recon.INI").write_text(
        "PatientID=12345678\nFirstName=JOHN\nLastName=SMITH\nRows=512\n",
        encoding="utf-8",
    )

    proj = cbct / "CBCT Projections" / "IPS"
    proj.mkdir(parents=True)
    (proj / "00001.his").write_bytes(b"\x00\x01\x02\x03")

    # Patient Files — centroid
    pf = site_root / "Patient Files" / "PAT01"
    pf.mkdir(parents=True)
    (pf / "Centroid_12345678.txt").write_text(
        "12345678\nSMITH JOHN\ncoords\n", encoding="utf-8"
    )

    # KIM-KV — trajectory log
    kim = site_root / "KIM-KV" / "img_session"
    kim.mkdir(parents=True)
    (kim / "MarkerLocations01.txt").write_text(
        "path=patient_12345678/data\n", encoding="utf-8"
    )

    # Source patient dir (must exist for DicomAnonymiser)
    patient_dir = tmp_path / "patient_12345678"
    patient_dir.mkdir()

    return output_dir, patient_dir, site_name


class TestAnonymiseOutputFolder:
    def test_anonymises_all_file_types(self, tmp_path):
        output_dir, patient_dir, site_name = _build_output_tree(tmp_path)

        counts = anonymise_output_folder(
            output_dir=output_dir,
            anon_id="PAT01",
            site_name=site_name,
            patient_dir=patient_dir,
        )

        assert counts["xml"] == 1
        assert counts["ini"] == 1
        assert counts["centroid"] == 1
        assert counts["trajectory"] == 1
        assert counts["errors"] == 0

        site_root = output_dir / site_name

        # _Frames.xml anonymised
        xml_path = (
            site_root / "Patient Images" / "PAT01" / "FX1" / "CBCT" / "CBCT1"
            / "_Frames.xml"
        )
        xml_text = xml_path.read_text(encoding="utf-8")
        assert "12345678" not in xml_text
        assert "JOHN" not in xml_text

        # INI anonymised
        ini_path = (
            site_root / "Patient Images" / "PAT01" / "FX1" / "CBCT" / "CBCT1"
            / "Reconstructed CBCT" / "recon.INI"
        )
        ini_text = ini_path.read_text(encoding="utf-8")
        assert "PatientID=PAT01" in ini_text
        assert "12345678" not in ini_text

        # Centroid anonymised and renamed
        centroid_dir = site_root / "Patient Files" / "PAT01"
        centroid_files = list(centroid_dir.glob("Centroid_*.txt"))
        assert len(centroid_files) == 1
        assert "PAT01" in centroid_files[0].name
        centroid_text = centroid_files[0].read_text(encoding="utf-8")
        assert centroid_text.splitlines()[0] == "PAT01"

        # Trajectory log anonymised
        traj_path = (
            site_root / "KIM-KV" / "img_session" / "MarkerLocations01.txt"
        )
        traj_text = traj_path.read_text(encoding="utf-8")
        assert "patient_PAT01" in traj_text
        assert "patient_12345678" not in traj_text

        # .his file untouched
        his_path = (
            site_root / "Patient Images" / "PAT01" / "FX1" / "CBCT" / "CBCT1"
            / "CBCT Projections" / "IPS" / "00001.his"
        )
        assert his_path.read_bytes() == b"\x00\x01\x02\x03"

    def test_tps_import(self, tmp_path):
        output_dir, patient_dir, site_name = _build_output_tree(tmp_path)

        # Create a TPS export with a DICOM CT file
        tps = tmp_path / "tps_export"
        _make_test_dicom(tps / "DICOM CT Images", "ct_slice.dcm")

        counts = anonymise_output_folder(
            output_dir=output_dir,
            anon_id="PAT01",
            site_name=site_name,
            patient_dir=patient_dir,
            tps_path=tps,
        )

        assert counts["tps_imported"] == 1

        ct_dir = output_dir / site_name / "Patient Plans" / "PAT01" / "CT"
        dcm_files = list(ct_dir.rglob("*.dcm")) + list(ct_dir.rglob("*.DCM"))
        assert len(dcm_files) >= 1
        ds = pydicom.dcmread(dcm_files[0])
        assert ds.PatientID == "PAT01"

    def test_progress_callback(self, tmp_path):
        output_dir, patient_dir, site_name = _build_output_tree(tmp_path)

        calls = []

        def on_progress(current, total, filename):
            calls.append((current, total, filename))

        anonymise_output_folder(
            output_dir=output_dir,
            anon_id="PAT01",
            site_name=site_name,
            patient_dir=patient_dir,
            progress_callback=on_progress,
        )

        assert len(calls) > 0
        # Final call should have current == total
        assert calls[-1][0] == calls[-1][1]
