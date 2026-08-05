"""Run the LEARN pipeline on a patient example.

Usage:
    python examples/run_patient_example.py
"""

import logging
from pathlib import Path

from learn_upload.anonymise_dicom import DicomAnonymiser
from learn_upload.config import setup_logging
from learn_upload.folder_sort import LearnFolderMapper
from learn_upload.verify_pii import verify_no_pii

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PATIENT_ROOT = Path(r"P:\04_Projects\07_KIM\Trial Patients Data\Patient_12345678")
XVI_EXPORT = PATIENT_ROOT / "XVI Export"
TPS_EXPORT = PATIENT_ROOT / "TPS Export"
CENTROID_FILE = PATIENT_ROOT / "Centroid_12345678_BeamID_1.1_1.2_1.3_1.4.txt"

ANON_ID = "PAT01"
SITE_NAME = "Prostate"
OUTPUT_BASE = Path(r"C:\Users\kankean.kandasamy\Repo\learn-crawler\output")
STAGING_DIR = OUTPUT_BASE / "_staging"

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging(logging.INFO)

    # ------------------------------------------------------------------
    # 1. Anonymise TPS DICOM files
    # ------------------------------------------------------------------
    logger.info("=== Step 1: Anonymise TPS DICOM files ===")
    anon = DicomAnonymiser(
        patient_dir=PATIENT_ROOT,
        anon_id=ANON_ID,
        output_dir=STAGING_DIR,
        site_name=SITE_NAME,
    )

    # Classify and anonymise each DICOM category from TPS Export
    categories = {
        "ct": TPS_EXPORT / "DICOM CT Images",
        "plan": TPS_EXPORT / "DICOM RT Plan",
        "structures": TPS_EXPORT / "DICOM RT Structures",
    }

    anon_dirs = {}
    for category, source_dir in categories.items():
        if source_dir.is_dir():
            cat_staging = STAGING_DIR / category
            cat_anon = DicomAnonymiser(
                patient_dir=PATIENT_ROOT,
                anon_id=ANON_ID,
                output_dir=cat_staging,
                site_name=SITE_NAME,
            )
            results = cat_anon.anonymise_all_dcm(source_dir)
            anon_dirs[category] = cat_staging
            logger.info("  %s: %d files anonymised", category, len(results))
        else:
            logger.warning("  %s directory not found: %s", category, source_dir)

    # ------------------------------------------------------------------
    # 2. Run folder mapper (XVI sessions + copy everything)
    # ------------------------------------------------------------------
    logger.info("=== Step 2: Folder mapping and file copy ===")
    mapper = LearnFolderMapper(
        patient_dir=PATIENT_ROOT,
        anon_id=ANON_ID,
        site_name=SITE_NAME,
        output_base=OUTPUT_BASE,
        images_subdir="XVI Export",
    )

    summary = mapper.execute(
        anon_ct_dir=anon_dirs.get("ct"),
        anon_plan_dir=anon_dirs.get("plan"),
        anon_struct_dir=anon_dirs.get("structures"),
        anon_dose_dir=anon_dirs.get("dose"),
        centroid_path=CENTROID_FILE,
        trajectory_base_dir=PATIENT_ROOT,  # FX01-FX04 are direct children
        dry_run=False,
    )

    # ------------------------------------------------------------------
    # 3. Verify no residual PII in output
    # ------------------------------------------------------------------
    logger.info("=== Step 3: PII verification ===")
    pii_strings = ["12345678", "SMITH", "JOHN"]
    output_patient_dir = OUTPUT_BASE / SITE_NAME / "Patient Plans" / ANON_ID
    findings = verify_no_pii(output_patient_dir, pii_strings)
    if findings:
        logger.error("PII DETECTED — review findings above")
    else:
        logger.info("PII verification passed")

    # ------------------------------------------------------------------
    # 4. Summary
    # ------------------------------------------------------------------
    logger.info("=== Pipeline complete ===")
    logger.info("Sessions discovered: %d", summary["sessions"])
    logger.info("Fractions assigned:  %d", summary["fractions"])
    for key, val in summary["files_copied"].items():
        logger.info("  %-15s %d", key, val)


if __name__ == "__main__":
    main()
