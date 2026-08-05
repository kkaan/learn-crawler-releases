"""Tests for scripts/anonymise_dicom_file.py."""

import sys
from pathlib import Path

import pydicom

from tests.test_anonymise_dicom import _make_test_dicom

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def test_cli_anonymises_single_dicom_file(tmp_path):
    from anonymise_dicom_file import main

    source = _make_test_dicom(
        tmp_path / "incoming",
        "dose.dcm",
        patient_name="DOE^JANE",
        patient_id="87654321",
        study_description="Dose for 87654321",
    )
    output = tmp_path / "out" / "dose_anon.dcm"

    rc = main([
        "--input", str(source),
        "--output", str(output),
        "--anon-id", "PAT07",
        "--site-name", "Lung",
    ])

    assert rc == 0
    ds = pydicom.dcmread(output)
    assert str(ds.PatientName) == "PAT07^Lung"
    assert ds.PatientID == "PAT07"
    assert ds.StudyDescription == "Dose for PAT07"
