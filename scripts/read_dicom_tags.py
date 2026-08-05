"""Read and display all DICOM tags from a given DICOM file.

Usage (CLI):
    # Print tags to console
    python read_dicom_tags.py path/to/file.dcm

    # Write tags to a text file
    python read_dicom_tags.py path/to/file.dcm -o tags.txt

    # Include private tags
    python read_dicom_tags.py path/to/file.dcm --private

    # Combine options
    python read_dicom_tags.py path/to/file.dcm -o tags.txt --private

Usage (Python):
    from read_dicom_tags import read_dicom_tags

    # Print to console
    read_dicom_tags("path/to/file.dcm")

    # Write to file with private tags
    read_dicom_tags("path/to/file.dcm", output="tags.txt", show_private=True)
"""

import argparse
import sys

from pydicom import dcmread
from pydicom.errors import InvalidDicomError


def read_dicom_tags(filepath: str, output: str = None, show_private: bool = False) -> None:
    """Print every DICOM tag in the file, optionally writing to an output file."""
    try:
        ds = dcmread(filepath)
    except (InvalidDicomError, FileNotFoundError, PermissionError) as e:
        print(f"Error reading {filepath}: {e}", file=sys.stderr)
        sys.exit(1)

    lines = []
    lines.append(f"File: {filepath}")
    lines.append(f"SOP Class: {ds.SOPClassUID.name if 'SOPClassUID' in ds else 'N/A'}")
    lines.append("-" * 80)

    for elem in ds.iterall():
        if not show_private and elem.tag.is_private:
            continue
        tag = f"({elem.tag.group:04X},{elem.tag.element:04X})"
        vr = elem.VR
        name = elem.keyword or elem.name
        value = _format_value(elem)
        lines.append(f"{tag} {vr:4s} {name:40s} {value}")

    text = "\n".join(lines) + "\n"

    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Written to {output}")
    else:
        print(text, end="")


def _format_value(elem) -> str:
    """Format a DICOM element value for display."""
    if elem.VR == "SQ":
        return f"<Sequence with {len(elem.value)} item(s)>"
    if elem.VR in ("OB", "OW", "OF", "OD", "UN"):
        length = len(elem.value) if elem.value else 0
        return f"<{length} bytes>"
    value = str(elem.value)
    if len(value) > 120:
        return value[:120] + "..."
    return value


def main():
    parser = argparse.ArgumentParser(description="Read all DICOM tags from a file.")
    parser.add_argument("file", help="Path to the DICOM file")
    parser.add_argument(
        "-o", "--output", help="Path to output text file (prints to console if omitted)"
    )
    parser.add_argument(
        "--private", action="store_true", help="Include private tags in output"
    )
    args = parser.parse_args()

    read_dicom_tags(args.file, output=args.output, show_private=args.private)


if __name__ == "__main__":
    main()
