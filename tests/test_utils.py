"""Tests for learn_upload.utils — INI parsing, XML parsing, ScanUID datetime."""

import textwrap
from datetime import datetime
from pathlib import Path

import pytest

from learn_upload.utils import (
    parse_couch_shifts,
    parse_frames_xml,
    parse_scan_datetime,
    parse_xvi_ini,
)


def _make_rtplan_with_fractions(path: Path, num_fractions: int) -> None:
    """Write a minimal RTPLAN DICOM file with NumberOfFractionsPlanned set."""
    pytest.importorskip("pydicom")
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.481.5"  # RT Plan Storage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.Modality = "RTPLAN"
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID

    fg = Dataset()
    fg.FractionGroupNumber = 1
    fg.NumberOfFractionsPlanned = num_fractions
    ds.FractionGroupSequence = [fg]

    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.save_as(str(path))

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_INI = textwrap.dedent("""\
    [XVI]
    SomeUnrelatedKey=ignored
    Visibility=1

    [IDENTIFICATION]
    PatientID=15002197
    TreatmentID=WholeBrain-C2Retrt
    TreatmentUID=1.3.46.423632.33783920233217242713.224
    ReferenceUID=1.2.840.113854.59112832676204369253232190232540417741
    FirstName=Anonymized
    LastName=Anonymized

    [RECONSTRUCTION]
    ScanUID=1.3.46.423632.33783920233217242713.224.2023-03-21165402768
    TubeKV=100.0000
    TubeMA=10.0000
    CollimatorName=S20
""")

SAMPLE_FRAMES_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <FrameData>
        <Treatment>
            <ID>WholeBrain-C2Retrt</ID>
        </Treatment>
        <Frames>
            <Frame Number="1" />
        </Frames>
    </FrameData>
""")

FULL_FRAMES_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <FrameData>
        <Treatment>
            <ID>Prostate</ID>
        </Treatment>
        <Image>
            <AcquisitionPresetName>4ee Pelvis Soft S20 179-181</AcquisitionPresetName>
            <DicomUID>1.3.46.423632.33783920233217242713.500</DicomUID>
            <kV>120.0</kV>
            <mA>25.5</mA>
        </Image>
        <Frames>
            <Frame Number="1" />
        </Frames>
    </FrameData>
""")


# ---------------------------------------------------------------------------
# parse_xvi_ini
# ---------------------------------------------------------------------------

class TestParseXviIni:
    def test_all_fields_extracted(self):
        result = parse_xvi_ini(SAMPLE_INI)
        assert result["PatientID"] == "15002197"
        assert result["TreatmentID"] == "WholeBrain-C2Retrt"
        assert result["TreatmentUID"] == "1.3.46.423632.33783920233217242713.224"
        assert result["ReferenceUID"] == "1.2.840.113854.59112832676204369253232190232540417741"
        assert result["FirstName"] == "Anonymized"
        assert result["LastName"] == "Anonymized"
        assert result["ScanUID"] == "1.3.46.423632.33783920233217242713.224.2023-03-21165402768"
        assert result["TubeKV"] == "100.0000"
        assert result["TubeMA"] == "10.0000"
        assert result["CollimatorName"] == "S20"

    def test_missing_fields_omitted(self):
        partial_ini = "[IDENTIFICATION]\nPatientID=12345\n"
        result = parse_xvi_ini(partial_ini)
        assert result["PatientID"] == "12345"
        assert "TubeKV" not in result
        assert "ScanUID" not in result

    def test_empty_input(self):
        assert parse_xvi_ini("") == {}

    def test_whitespace_stripped(self):
        ini = "TubeKV=100.0000  \nTubeMA=  10.0000  \n"
        result = parse_xvi_ini(ini)
        assert result["TubeKV"] == "100.0000"
        assert result["TubeMA"] == "10.0000"

    def test_extracts_fov_small(self):
        """parse_xvi_ini should return the FOV field from .INI.XVI text."""
        ini_text = "ScanUID=1.2.3.4\nTubeKV=120\nFOV=small\nCollimatorName=S20\n"
        result = parse_xvi_ini(ini_text)
        assert result.get("FOV") == "small"

    def test_extracts_fov_medium_and_large(self):
        assert parse_xvi_ini("FOV=medium\n").get("FOV") == "medium"
        assert parse_xvi_ini("FOV=large\n").get("FOV") == "large"

    def test_missing_fov_returns_no_key(self):
        result = parse_xvi_ini("ScanUID=1.2.3.4\n")
        assert "FOV" not in result


# ---------------------------------------------------------------------------
# parse_scan_datetime
# ---------------------------------------------------------------------------

class TestParseScanDatetime:
    def test_valid_scan_uid(self):
        uid = "1.3.46.423632.33783920233217242713.224.2023-03-21165402768"
        dt = parse_scan_datetime(uid)
        assert dt == datetime(2023, 3, 21, 16, 54, 2, 768000)

    def test_different_date(self):
        uid = "1.3.46.423632.12345.2024-12-01093015500"
        dt = parse_scan_datetime(uid)
        assert dt == datetime(2024, 12, 1, 9, 30, 15, 500000)

    def test_scan_uid_with_stripped_leading_zero_hour(self):
        # Real Elekta exports drop the leading zero of an early-hour timestamp:
        # 09:38:51.230 is stored as "93851230" (8 digits) not "093851230".
        uid = "1.3.46.423632.33848620266323385190.60.2026-06-0493851230"
        dt = parse_scan_datetime(uid)
        assert dt == datetime(2026, 6, 4, 9, 38, 51, 230000)

    def test_no_datetime_returns_none(self):
        assert parse_scan_datetime("1.3.46.423632.12345") is None

    def test_invalid_date_returns_none(self):
        # Month 13 is invalid
        assert parse_scan_datetime("1.3.46.12345.2023-13-01120000000") is None

    def test_empty_string(self):
        assert parse_scan_datetime("") is None


# ---------------------------------------------------------------------------
# parse_frames_xml
# ---------------------------------------------------------------------------

class TestParseFramesXml:
    def test_valid_xml(self, tmp_path):
        xml_file = tmp_path / "_Frames.xml"
        xml_file.write_text(SAMPLE_FRAMES_XML, encoding="utf-8")
        result = parse_frames_xml(xml_file)
        assert result["treatment_id"] == "WholeBrain-C2Retrt"

    def test_missing_treatment_element(self, tmp_path):
        xml_file = tmp_path / "_Frames.xml"
        xml_file.write_text('<?xml version="1.0"?><FrameData></FrameData>', encoding="utf-8")
        result = parse_frames_xml(xml_file)
        assert result["treatment_id"] is None

    def test_missing_id_element(self, tmp_path):
        xml_file = tmp_path / "_Frames.xml"
        xml_content = '<?xml version="1.0"?><FrameData><Treatment></Treatment></FrameData>'
        xml_file.write_text(xml_content, encoding="utf-8")
        result = parse_frames_xml(xml_file)
        assert result["treatment_id"] is None

    def test_nonexistent_file(self, tmp_path):
        result = parse_frames_xml(tmp_path / "does_not_exist.xml")
        assert result["treatment_id"] is None

    def test_malformed_xml(self, tmp_path):
        xml_file = tmp_path / "_Frames.xml"
        xml_file.write_text("<broken><xml", encoding="utf-8")
        result = parse_frames_xml(xml_file)
        assert result["treatment_id"] is None

    def test_full_xml_with_image_fields(self, tmp_path):
        xml_file = tmp_path / "_Frames.xml"
        xml_file.write_text(FULL_FRAMES_XML, encoding="utf-8")
        result = parse_frames_xml(xml_file)
        assert result["treatment_id"] == "Prostate"
        assert result["acquisition_preset"] == "4ee Pelvis Soft S20 179-181"
        assert result["dicom_uid"] == "1.3.46.423632.33783920233217242713.500"
        assert result["kv"] == 120.0
        assert result["ma"] == 25.5

    def test_minimal_xml_returns_none_for_new_fields(self, tmp_path):
        xml_file = tmp_path / "_Frames.xml"
        xml_file.write_text(SAMPLE_FRAMES_XML, encoding="utf-8")
        result = parse_frames_xml(xml_file)
        assert result["treatment_id"] == "WholeBrain-C2Retrt"
        assert result["acquisition_preset"] is None
        assert result["dicom_uid"] is None
        assert result["kv"] is None
        assert result["ma"] is None


# ---------------------------------------------------------------------------
# parse_couch_shifts
# ---------------------------------------------------------------------------

class TestParseCouchShifts:
    def test_valid_shifts(self):
        ini = textwrap.dedent("""\
            CouchShiftLat=1.23
            CouchShiftLong=-4.56
            CouchShiftHeight=0.78
        """)
        result = parse_couch_shifts(ini)
        assert result == {
            "lateral": 1.23,
            "longitudinal": -4.56,
            "vertical": 0.78,
        }

    def test_missing_shift_returns_none(self):
        ini = "CouchShiftLat=1.0\nCouchShiftLong=2.0\n"
        assert parse_couch_shifts(ini) is None

    def test_zero_shifts(self):
        ini = textwrap.dedent("""\
            CouchShiftLat=0.0000
            CouchShiftLong=0.0000
            CouchShiftHeight=0.0000
        """)
        result = parse_couch_shifts(ini)
        assert result == {
            "lateral": 0.0,
            "longitudinal": 0.0,
            "vertical": 0.0,
        }


# ---------------------------------------------------------------------------
# extract_planned_fractions
# ---------------------------------------------------------------------------

class TestExtractPlannedFractions:
    def test_returns_integer_for_valid_rtplan(self, tmp_path):
        from learn_upload.utils import extract_planned_fractions
        rtplan = tmp_path / "plan.dcm"
        _make_rtplan_with_fractions(rtplan, num_fractions=25)
        assert extract_planned_fractions(rtplan) == 25

    def test_missing_sequence_returns_none(self, tmp_path):
        """RTPLAN with no FractionGroupSequence should return None, not raise."""
        pytest.importorskip("pydicom")
        from pydicom.dataset import Dataset, FileDataset
        from pydicom.uid import ExplicitVRLittleEndian, generate_uid

        from learn_upload.utils import extract_planned_fractions

        path = tmp_path / "noseq.dcm"
        file_meta = Dataset()
        file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.481.5"
        file_meta.MediaStorageSOPInstanceUID = generate_uid()
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\0" * 128)
        ds.Modality = "RTPLAN"
        ds.is_little_endian = True
        ds.is_implicit_VR = False
        ds.save_as(str(path))

        assert extract_planned_fractions(path) is None

    def test_unreadable_file_returns_none(self, tmp_path):
        from learn_upload.utils import extract_planned_fractions
        bogus = tmp_path / "not_a_dicom.dcm"
        bogus.write_bytes(b"this is not DICOM")
        assert extract_planned_fractions(bogus) is None
