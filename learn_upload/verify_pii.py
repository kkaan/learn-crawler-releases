"""Post-anonymisation PII verification for LEARN data transfer pipeline.

Scans an output directory for residual patient-identifiable strings in DICOM
tags, XML text, plain-text files, and filenames.
"""

import argparse
import logging
import sys
from pathlib import Path

import pydicom

logger = logging.getLogger(__name__)

# pydicom VR types that contain human-readable strings worth checking.
_STRING_VRS = {
    "LO", "SH", "PN", "LT", "ST", "UT", "DA", "DS", "IS", "CS",
    "AE", "AS", "DT", "TM", "UC", "UI",
}


def verify_no_pii(directory: Path, pii_strings: list[str]) -> list[dict]:
    """Scan *directory* for residual PII and return a list of findings.

    Parameters
    ----------
    directory : Path
        Root directory to scan recursively.
    pii_strings : list[str]
        Substrings to search for (case-insensitive).

    Returns
    -------
    list[dict]
        Each finding is ``{"file": Path, "location": str, "matched": str}``.
    """
    directory = Path(directory)
    if not directory.is_dir():
        logger.error("Directory does not exist: %s", directory)
        return []

    pii_lower = [s.lower() for s in pii_strings]
    findings: list[dict] = []
    files_scanned = 0

    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        files_scanned += 1

        # --- Check filename ---
        name_lower = path.name.lower()
        for pii, original in zip(pii_lower, pii_strings):
            if pii in name_lower:
                findings.append({
                    "file": path,
                    "location": "filename",
                    "matched": original,
                })

        suffix = path.suffix.lower()

        # --- DICOM files ---
        if suffix in (".dcm",):
            findings.extend(_check_dicom(path, pii_lower, pii_strings))

        # --- XML files ---
        elif suffix in (".xml",):
            findings.extend(_check_text_file(path, pii_lower, pii_strings, "xml text"))

        # --- Plain text files ---
        elif suffix in (".txt",):
            findings.extend(_check_text_file(path, pii_lower, pii_strings, "text content"))

    # --- Human-readable summary ---
    print(f"\nPII Verification: scanned {files_scanned} files in {directory}")
    if findings:
        print(f"FAIL — {len(findings)} PII finding(s):")
        for f in findings:
            print(f"  {f['file']}  [{f['location']}]  matched '{f['matched']}'")
    else:
        print("PASS — no residual PII detected")

    return findings


def _check_dicom(
    path: Path, pii_lower: list[str], pii_originals: list[str],
) -> list[dict]:
    """Check all string-valued DICOM data elements for PII substrings."""
    findings: list[dict] = []
    try:
        ds = pydicom.dcmread(path, force=True)
    except Exception:
        logger.warning("Could not read DICOM file: %s", path)
        return findings

    for elem in ds.iterall():
        if elem.VR not in _STRING_VRS:
            continue
        value_str = str(elem.value).lower()
        for pii, original in zip(pii_lower, pii_originals):
            if pii in value_str:
                tag_name = elem.keyword or str(elem.tag)
                findings.append({
                    "file": path,
                    "location": f"tag {tag_name} {elem.tag}",
                    "matched": original,
                })
    return findings


def _check_text_file(
    path: Path,
    pii_lower: list[str],
    pii_originals: list[str],
    location_label: str,
) -> list[dict]:
    """Read a text file and check for PII substrings."""
    findings: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace").lower()
    except Exception:
        logger.warning("Could not read file: %s", path)
        return findings

    for pii, original in zip(pii_lower, pii_originals):
        if pii in text:
            findings.append({
                "file": path,
                "location": location_label,
                "matched": original,
            })
    return findings


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify an anonymised directory contains no residual PII.",
    )
    parser.add_argument("directory", type=Path, help="Directory to scan")
    parser.add_argument("pii_strings", nargs="+", help="PII substrings to search for")
    args = parser.parse_args()

    findings = verify_no_pii(args.directory, args.pii_strings)
    sys.exit(1 if findings else 0)


if __name__ == "__main__":
    main()
