"""Run the LEARN pipeline on a patient without the GUI.

Mirrors the wizard's steps: discover sessions and assign fractions, copy raw
files into the LEARN structure, anonymise the output in place (importing the
TPS export by DICOM Modality), then scan for residual PII.

Edit the paths in the Configuration block before running.  Copy the XVI export
to a local drive first -- reading thousands of .his files over SMB is slow.

Usage:
    uv run python examples/run_patient_example.py
"""

import logging
from pathlib import Path

from learn_upload.anonymise_dicom import anonymise_output_folder
from learn_upload.config import setup_logging
from learn_upload.folder_sort import LearnFolderMapper
from learn_upload.fraction_assignment import build_fraction_result
from learn_upload.verify_pii import verify_no_pii

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# The Source Path: the folder that CONTAINS the images subdirectory (a sibling
# of the TPS export), not the images folder itself.  For PRIME patients the
# FXnn/ trajectory folders usually sit directly inside it.
PATIENT_ROOT = Path(r"E:\XVI_COLLECTION\Patient_12345678")
IMAGES_SUBDIR = "XVI Export"
TPS_EXPORT = PATIENT_ROOT / "TPS Export"
TRAJECTORY_DIR = PATIENT_ROOT
CENTROID_FILE = PATIENT_ROOT / "Centroid_12345678_BeamID_1.1_1.2.txt"

ANON_ID = "PAT01"
REDCAP_ID = "LEARN_001"
SITE_NAME = "Prostate"
OUTPUT_BASE = Path(r"E:\LEARN_OUTPUT")

# Everything the PII scan should look for: MRN and name fragments.
PII_STRINGS = ["12345678", "SMITH", "JOHN"]

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging(logging.INFO)

    mapper = LearnFolderMapper(
        patient_dir=PATIENT_ROOT,
        anon_id=ANON_ID,
        site_name=SITE_NAME,
        output_base=OUTPUT_BASE,
        images_subdir=IMAGES_SUBDIR,
    )

    # ------------------------------------------------------------------
    # 1. Discover sessions and assign fractions (trajectory ground truth)
    # ------------------------------------------------------------------
    logger.info("=== Step 1: Discover sessions and assign fractions ===")
    sessions = mapper.discover_sessions(enrich=True)
    fractions = build_fraction_result(
        sessions, source_root=TRAJECTORY_DIR, mode="trajectory"
    )
    logger.info(
        "%d sessions across %s", len(sessions), ", ".join(fractions.fraction_labels)
    )
    for ref in fractions.missing_references:
        logger.warning(
            "%s references %s but it is not in the export", ref.log_name, ref.uid
        )
    for s in fractions.unmatched:
        logger.warning("Could not place %s", s.img_dir.name)

    # ------------------------------------------------------------------
    # 2. Copy raw files into the LEARN structure
    # ------------------------------------------------------------------
    # Also writes fraction_assignment_record_<ANON_ID>.md into PATIENT_ROOT.
    logger.info("=== Step 2: Folder sort ===")
    summary = mapper.execute(
        fraction_result=fractions,
        centroid_path=CENTROID_FILE if CENTROID_FILE.exists() else None,
        trajectory_base_dir=TRAJECTORY_DIR,
        dry_run=False,
    )

    # ------------------------------------------------------------------
    # 3. Anonymise the output in place and import the TPS export
    # ------------------------------------------------------------------
    logger.info("=== Step 3: Anonymise ===")
    counts = anonymise_output_folder(
        output_dir=OUTPUT_BASE,
        anon_id=ANON_ID,
        site_name=SITE_NAME,
        patient_dir=PATIENT_ROOT,
        tps_path=TPS_EXPORT if TPS_EXPORT.is_dir() else None,
        redcap_id=REDCAP_ID,
    )
    logger.info("Anonymised: %s", counts)

    # ------------------------------------------------------------------
    # 4. Verify no residual PII in the whole site output
    # ------------------------------------------------------------------
    logger.info("=== Step 4: PII verification ===")
    findings = verify_no_pii(OUTPUT_BASE / SITE_NAME, PII_STRINGS)
    if findings:
        logger.error("PII DETECTED -- review findings above")
    else:
        logger.info("PII verification passed")

    # ------------------------------------------------------------------
    # 5. Summary
    # ------------------------------------------------------------------
    logger.info("=== Pipeline complete ===")
    logger.info("Sessions:  %d", summary["sessions"])
    logger.info("Fractions: %d", summary["fractions"])
    logger.info("Record:    %s", summary["assignment_record"])
    for key, val in summary["files_copied"].items():
        logger.info("  %-12s %d", key, val)


if __name__ == "__main__":
    main()
