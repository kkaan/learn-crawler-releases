#!/usr/bin/env python3
"""
Generate a markdown report of CBCT shift details for a patient.

Extracts correction values from RPS DICOM files and converts them to
Mosaiq-convention shifts (Sup/Lat/Ant translations + Cor/Sag/Trans rotations).
"""

import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

# Import shared utilities from compare_rps_mosaiq (same directory)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_rps_mosaiq import (
    find_rps_files,
    extract_rps_data,
    unwrap_angle,
    REPO_ROOT,
)

# RedCap template header fields with defaults.
# Edit these values to match the site/protocol before generating reports.
REDCAP_DEFAULTS = OrderedDict([
    ("RedCap ID",                   ""),
    ("Image Collected",             "CBCTs"),
    ("Linac Type",                  "Versa HD"),
    ("Imager Position (SDD)",       "150 cm"),
    ("Couch Type",                  "Precise Table/Hexapod"),
    ("Coordinate System",           ""),
    ("kV",                          "120"),
    ("mAs",                         "25"),
    ("Marker Length and Type",      ""),
    ("Cdog Version",                ""),
])


def clipbox_to_mosaiq(clipbox):
    """Convert RPS Clipbox values to Mosaiq-convention shifts.

    Returns dict with Mosaiq field names and signed values.
    """
    return {
        'sup': clipbox.get('longitudinal', 0.0),
        'lat': clipbox.get('lateral', 0.0),
        'ant': clipbox.get('vertical', 0.0),
        'cor': unwrap_angle(clipbox.get('roll', 0.0)) or 0.0,
        'sag': unwrap_angle(clipbox.get('rotation', 0.0)) or 0.0,
        'trans': -(unwrap_angle(clipbox.get('pitch', 0.0)) or 0.0),
    }


def generate_report(patient_path, redcap_id=None):
    """Generate markdown report for a patient directory."""
    patient_path = Path(patient_path)
    patient_id = patient_path.name

    # Find and extract all RPS files
    rps_files = find_rps_files(patient_path)
    if not rps_files:
        print(f"No RPS files found under {patient_path}")
        return None

    # Extract data and convert to Mosaiq format
    rows = []
    for rf in rps_files:
        data = extract_rps_data(rf['path'])
        dt = data['ini_datetime'] or data['dicom_datetime']
        mq = clipbox_to_mosaiq(data.get('clipbox', {}))
        rows.append({
            'fx': rf['fx'] or '?',
            'cbct': rf['cbct'] or '?',
            'datetime': dt,
            'date_str': dt.strftime('%d/%m/%Y') if dt else '?',
            'time_str': dt.strftime('%H:%M') if dt else '?',
            **mq,
        })

    # Sort by datetime
    rows.sort(key=lambda r: r['datetime'] or datetime.min)

    # Build markdown
    header = OrderedDict(REDCAP_DEFAULTS)
    header["RedCap ID"] = redcap_id or patient_id

    lines = [
        f"# CBCT Shift Report: {patient_id}",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d')}",
        "",
        "## Study Details",
        "",
    ]
    for key, val in header.items():
        lines.append(f"- **{key}:** {val}")

    lines += [
        "",
        "## CBCT Sessions",
        "",
        "| FX | CBCT | Date | Time | Sup (cm) | Lat (cm) | Ant (cm) | Cor (deg) | Sag (deg) | Trans (deg) |",
        "|----|------|------|------|----------|----------|----------|-----------|-----------|-------------|",
    ]

    for r in rows:
        lines.append(
            f"| {r['fx']} | {r['cbct']} "
            f"| {r['date_str']} | {r['time_str']} "
            f"| {r['sup']:.2f} | {r['lat']:.2f} | {r['ant']:.2f} "
            f"| {r['cor']:.1f} | {r['sag']:.1f} | {r['trans']:.1f} |"
        )

    lines += [
        "",
        "## Mapping Reference",
        "",
        "Translations: Clipbox long/lat/vert -> Mosaiq Sup/Lat/Ant (same sign, cm)",
        "Rotations: CB roll -> Cor(B), CB rotation -> Sag(B), -CB pitch -> Trans(B) (degrees)",
        "",
        "## Data Sources",
        "",
        "**Study Details**",
        "",
        "| Field | Source |",
        "|-------|--------|",
        "| RedCap ID | User-entered via GUI (or anonymised patient ID as fallback) |",
        "| Image Collected | Hardcoded default |",
        "| Linac Type | Hardcoded default |",
        "| Imager Position (SDD) | Hardcoded default |",
        "| Couch Type | Hardcoded default |",
        "| Coordinate System | Manual entry required |",
        "| kV | Hardcoded default |",
        "| mAs | Hardcoded default |",
        "| Marker Length and Type | Manual entry required |",
        "| Cdog Version | Manual entry required |",
        "",
        "**CBCT Sessions**",
        "",
        "| Column | Source |",
        "|--------|--------|",
        "| FX | Directory path label (e.g. `FX1/`) |",
        "| CBCT | Directory path label (e.g. `CBCT1/`) |",
        "| Date, Time | RPS DICOM INI `DateTime=` field; fallback: DICOM ContentDate/ContentTime |",
        "| Sup (cm) | RPS Clipbox `longitudinal` value |",
        "| Lat (cm) | RPS Clipbox `lateral` value |",
        "| Ant (cm) | RPS Clipbox `vertical` value |",
        "| Cor (deg) | RPS Clipbox `roll` (unwrapped from 0-360 to -180..180) |",
        "| Sag (deg) | RPS Clipbox `rotation` (unwrapped) |",
        "| Trans (deg) | Negated RPS Clipbox `pitch` (unwrapped) |",
        "",
        "RPS files located via glob: `**/Registration file/*.RPS.dcm`",
        "",
    ]

    return "\n".join(lines)


def main():
    if len(sys.argv) > 1:
        patient_path = Path(sys.argv[1])
    else:
        patient_path = REPO_ROOT / "output" / "Prostate" / "Patient Images" / "PAT01"

    report = generate_report(patient_path)
    if report is None:
        sys.exit(1)

    # Print to stdout
    print(report)

    # Write to file
    patient_id = patient_path.name
    output_path = Path(__file__).resolve().parent / f"{patient_id}_report.md"
    output_path.write_text(report, encoding="utf-8")
    print(f"\nReport written to {output_path}")


if __name__ == "__main__":
    main()
