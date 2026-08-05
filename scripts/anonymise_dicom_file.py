"""Anonymise a single DICOM file for one-off LEARN resends.

Usage:
    python scripts/anonymise_dicom_file.py --input dose.dcm --output dose_anon.dcm \
        --anon-id PAT01 [--site-name Prostate]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure repo root is on sys.path so learn_upload is importable from the script.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from learn_upload.anonymise_dicom import anonymise_dicom_file  # noqa: E402
from learn_upload.config import setup_logging  # noqa: E402

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Anonymise one DICOM file without running the full LEARN pipeline.",
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Source DICOM file, for example an RT Dose .dcm file.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Destination anonymised DICOM file. The source is not modified.",
    )
    parser.add_argument(
        "--anon-id",
        required=True,
        help="Anonymised patient ID, for example PAT01.",
    )
    parser.add_argument(
        "--site-name",
        default="",
        help="Optional site name stored after the caret in PatientName.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args(argv)

    setup_logging(level=getattr(logging, args.log_level))

    if not args.input.is_file():
        logger.error("Input DICOM file not found: %s", args.input)
        return 2

    output = anonymise_dicom_file(
        input_path=args.input,
        output_path=args.output,
        anon_id=args.anon_id,
        site_name=args.site_name,
    )
    print(f"Wrote anonymised DICOM to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
