"""
Centralised configuration for the learn_upload package.

Paths, constants, DICOM tag lists, and logging setup used across all modules.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Anonymised ID format
# ---------------------------------------------------------------------------
ANON_ID_PREFIX = "PAT"


def make_anon_id(n: int) -> str:
    """Format a sequential anonymised patient ID, e.g. make_anon_id(1) -> 'PAT01'."""
    return f"{ANON_ID_PREFIX}{n:02d}"


# ---------------------------------------------------------------------------
# Patient MRN verification
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MrnCheck:
    """Outcome of comparing the operator's MRN against the export's own."""

    status: str  # "match" | "mismatch" | "not_found" | "conflicting_export"
    entered: str
    export_ids: list[str]

    @property
    def export_id(self) -> str | None:
        """The export's MRN, or *None* when there isn't exactly one."""
        return self.export_ids[0] if len(self.export_ids) == 1 else None


def check_patient_mrn(entered: str, export_ids: dict[str, list[str]]) -> MrnCheck:
    """Compare the MRN the operator entered against the IDs found in the export.

    *export_ids* comes from ``source_layout.detect_export_patient_ids``.
    Comparison ignores surrounding whitespace and case, so a formatting
    difference is not reported as a mismatch.

    Pure decision logic: the GUI renders the result and offers the choice.
    """
    entered_clean = entered.strip()
    ids = list(export_ids)

    if not ids:
        return MrnCheck("not_found", entered_clean, [])
    if len(ids) > 1:
        return MrnCheck("conflicting_export", entered_clean, ids)
    if ids[0].strip().casefold() == entered_clean.casefold():
        return MrnCheck("match", entered_clean, ids)
    return MrnCheck("mismatch", entered_clean, ids)


# ---------------------------------------------------------------------------
# Wizard configuration validation
# ---------------------------------------------------------------------------
def validate_config(cfg: dict) -> str | None:
    """Validate a wizard configuration dict.

    Returns the first error message, or *None* when the config is usable.
    Kept free of Qt so it can be tested without a display; the GUI's
    ``ConfigPage.validate()`` delegates here.

    The REDCap ID is mandatory because it is written to line 1 of the
    centroid file during anonymisation.  No format is enforced -- REDCap
    project IDs vary between studies.
    """
    if not cfg.get("anon_id"):
        return "Anonymised ID is required."
    anon_id = cfg["anon_id"]
    if not anon_id.startswith(ANON_ID_PREFIX) or not anon_id[len(ANON_ID_PREFIX):].isdigit():
        return "Anon ID must match PATxx format (e.g. PAT01)."
    if not cfg.get("redcap_id"):
        return "REDCap ID is required."
    if not cfg.get("patient_mrn"):
        return "Patient MRN is required."
    if not cfg.get("site_name"):
        return "Site Name is required."
    if not cfg.get("source_path"):
        return "Source Path is required."
    if not cfg.get("output_path"):
        return "Output Path is required."
    return None


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
