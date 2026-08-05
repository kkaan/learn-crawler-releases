"""Tests for learn_upload.verify_pii — PII verification tool."""

from pathlib import Path

import pydicom
from pydicom.dataset import FileDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from learn_upload.verify_pii import verify_no_pii

# ---------------------------------------------------------------------------
# Helper: create a minimal synthetic DICOM file
# ---------------------------------------------------------------------------

def _make_test_dicom(
    filepath: Path,
    patient_name: str = "PAT01^Prostate",
    patient_id: str = "PAT01",
) -> Path:
    """Create a minimal DICOM file at *filepath* with the given identity tags."""
    filepath.parent.mkdir(parents=True, exist_ok=True)

    file_meta = pydicom.Dataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(str(filepath), {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.StudyID = "STUDY1"
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.save_as(filepath)
    return filepath


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCleanDirectory:
    def test_no_findings_when_clean(self, tmp_path):
        """A properly anonymised directory returns an empty findings list."""
        _make_test_dicom(tmp_path / "slice.dcm")
        (tmp_path / "notes.txt").write_text("All good", encoding="utf-8")
        (tmp_path / "frames.xml").write_text("<Data>ok</Data>", encoding="utf-8")

        findings = verify_no_pii(tmp_path, ["12345678", "SMITH", "JOHN"])
        assert findings == []

    def test_nonexistent_directory(self, tmp_path):
        findings = verify_no_pii(tmp_path / "nope", ["SMITH"])
        assert findings == []


class TestDicomPii:
    def test_pii_in_patient_name(self, tmp_path):
        """PII in DICOM PatientName tag is detected."""
        _make_test_dicom(
            tmp_path / "bad.dcm",
            patient_name="SMITH^JOHN",
            patient_id="PAT01",
        )
        findings = verify_no_pii(tmp_path, ["SMITH"])
        assert len(findings) >= 1
        dicom_findings = [f for f in findings if "tag" in f["location"]]
        assert any("SMITH" == f["matched"] for f in dicom_findings)

    def test_pii_in_patient_id(self, tmp_path):
        """PII in DICOM PatientID tag is detected."""
        _make_test_dicom(
            tmp_path / "bad.dcm",
            patient_name="PAT01^Prostate",
            patient_id="12345678",
        )
        findings = verify_no_pii(tmp_path, ["12345678"])
        dicom_findings = [f for f in findings if "tag" in f["location"]]
        assert any("12345678" == f["matched"] for f in dicom_findings)


class TestFilenamePii:
    def test_pii_in_filename(self, tmp_path):
        """PII substring in a filename is detected."""
        (tmp_path / "DCMRT_Plan(SMITH JOHN).dcm").write_bytes(b"")
        findings = verify_no_pii(tmp_path, ["SMITH"])
        filename_findings = [f for f in findings if f["location"] == "filename"]
        assert len(filename_findings) == 1
        assert filename_findings[0]["matched"] == "SMITH"


class TestXmlPii:
    def test_pii_in_xml(self, tmp_path):
        """PII in XML file content is detected."""
        xml = "<Patient><ID>12345678</ID><Name>SMITH</Name></Patient>"
        (tmp_path / "frames.xml").write_text(xml, encoding="utf-8")

        findings = verify_no_pii(tmp_path, ["12345678", "SMITH"])
        xml_findings = [f for f in findings if f["location"] == "xml text"]
        assert len(xml_findings) == 2


class TestTxtPii:
    def test_pii_in_txt(self, tmp_path):
        """PII in a plain text file is detected."""
        (tmp_path / "centroid.txt").write_text(
            "Centroid for patient 12345678\n1.0 2.0 3.0",
            encoding="utf-8",
        )
        findings = verify_no_pii(tmp_path, ["12345678"])
        txt_findings = [f for f in findings if f["location"] == "text content"]
        assert len(txt_findings) == 1
        assert txt_findings[0]["matched"] == "12345678"


class TestCaseInsensitivity:
    def test_lowercase_match(self, tmp_path):
        """Search is case-insensitive (lowercase in file, uppercase query)."""
        (tmp_path / "notes.txt").write_text("patient smith", encoding="utf-8")
        findings = verify_no_pii(tmp_path, ["SMITH"])
        assert len(findings) >= 1

    def test_mixed_case_filename(self, tmp_path):
        """Filename matching is case-insensitive."""
        (tmp_path / "Smith_data.txt").write_text("clean", encoding="utf-8")
        findings = verify_no_pii(tmp_path, ["SMITH"])
        filename_findings = [f for f in findings if f["location"] == "filename"]
        assert len(filename_findings) == 1
