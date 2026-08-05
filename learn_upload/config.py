"""
Centralised configuration for the learn_upload package.

Paths, constants, DICOM tag lists, and logging setup used across all modules.
"""

import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Anonymised ID format
# ---------------------------------------------------------------------------
ANON_ID_PREFIX = "PAT"


def make_anon_id(n: int) -> str:
    """Format a sequential anonymised patient ID, e.g. make_anon_id(1) -> 'PAT01'."""
    return f"{ANON_ID_PREFIX}{n:02d}"


# ---------------------------------------------------------------------------
# Default data paths (override via CLI or environment as needed)
# ---------------------------------------------------------------------------
DEFAULT_XVI_BASE = Path(r"E:\XVI_COLLECTION\processed\20230403_Flinders")
DEFAULT_LEARN_OUTPUT = Path(r"E:\LEARN_OUTPUT")

# ---------------------------------------------------------------------------
# Elekta XVI DICOM private tags
# ---------------------------------------------------------------------------
# RPS DICOM files embed a ZIP archive in this private tag containing .INI.XVI
# registration data.  See scripts/extract_elekta_rps_matrices.py for usage.
RPS_ZIP_TAG = (0x0021, 0x103A)

# ---------------------------------------------------------------------------
# DICOM tags for anonymisation
# ---------------------------------------------------------------------------
# Tags whose value is replaced with the anonymised ID (PATxx).
DICOM_TAGS_REPLACE = {
    (0x0010, 0x0010): "PatientName",
    (0x0010, 0x0020): "PatientID",
    (0x0020, 0x0010): "StudyID",
}

# Tags that are cleared (set to empty string).
DICOM_TAGS_CLEAR = {
    (0x0010, 0x0030): "PatientBirthDate",
    (0x0010, 0x1000): "OtherPatientIDs",
    (0x0010, 0x1001): "OtherPatientNames",
    (0x0008, 0x0050): "AccessionNumber",
    (0x0008, 0x0080): "InstitutionName",
    (0x0008, 0x0081): "InstitutionAddress",
    (0x0008, 0x0090): "ReferringPhysicianName",
    (0x0008, 0x1048): "PhysiciansOfRecord",
    (0x0008, 0x1070): "OperatorsName",
}

# Tags explicitly preserved — listed here for documentation; the anonymiser
# simply leaves any tag not in the replace/clear sets untouched.
DICOM_TAGS_PRESERVE = {
    (0x0010, 0x0040): "PatientSex",
    (0x0010, 0x1010): "PatientAge",
    (0x0010, 0x1020): "PatientSize",
    (0x0010, 0x1030): "PatientWeight",
    (0x0008, 0x1030): "StudyDescription",
    # All DICOM UIDs are preserved to maintain referential integrity.
}

# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logging for learn_upload scripts."""
    logging.basicConfig(level=level, format=LOG_FORMAT)
