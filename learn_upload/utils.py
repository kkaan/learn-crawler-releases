"""
Shared parsing utilities for Elekta XVI data files.

Functions here are generalised from patterns in the existing standalone scripts:
- scripts/elektafdt_crawler.py          (XML parsing)
- scripts/extract_elekta_rps_matrices.py (ZIP-embedded INI parsing from RPS DICOM)

They are designed to be reused across anonymise_dicom, folder_sort,
treatment_notes, and upload_workflow modules.
"""

import io
import logging
import re
import zipfile
from datetime import datetime
from pathlib import Path

import defusedxml.ElementTree as ET

from learn_upload.config import RPS_ZIP_TAG

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Plain INI parsing  (Reconstruction/*.INI files)
# ---------------------------------------------------------------------------

# Fields we extract from XVI plain INI files.  The regex approach (not
# configparser) is inherited from scripts/extract_elekta_rps_matrices.py because XVI
# INI files use non-standard formatting that configparser chokes on.
_INI_FIELDS = [
    "PatientID",
    "TreatmentID",
    "TreatmentUID",
    "ReferenceUID",
    "FirstName",
    "LastName",
    "ScanUID",
    "TubeKV",
    "TubeMA",
    "CollimatorName",
    "FOV",
]


def parse_xvi_ini(ini_text: str) -> dict:
    """Parse an Elekta XVI INI file and return extracted fields.

    Handles both ``[IDENTIFICATION]``-section fields from ``.INI`` files and
    reconstruction parameters (TubeKV, TubeMA, ScanUID, CollimatorName) from
    ``.INI.XVI`` files — the same regex works on either since the key=value
    format is identical.

    Parameters
    ----------
    ini_text : str
        Raw text content of the INI file.

    Returns
    -------
    dict
        Mapping of field name -> string value for every field found.
        Missing fields are omitted (not set to None).
    """
    result = {}
    for field in _INI_FIELDS:
        match = re.search(rf"^{field}=(.+)$", ini_text, re.MULTILINE)
        if match:
            value = match.group(1).strip()
            result[field] = value
    return result


# ---------------------------------------------------------------------------
# ScanUID datetime parsing
# ---------------------------------------------------------------------------

# ScanUID format example:
#   1.3.46.423632.33783920233217242713.224.2023-03-21165402768
# The datetime is embedded at the end: YYYY-MM-DD then HHMMSSmmm (9 digits).
# Some exports drop the leading zero of an early-hour timestamp, leaving 6-8
# time digits (e.g. "93851230" for 09:38:51.230), so the time width is variable
# and is left-padded back to 9 digits before splitting.
_SCAN_DATETIME_PATTERN = re.compile(r"(\d{4})-(\d{2})-(\d{2})(\d{6,9})$")


def parse_scan_datetime(scan_uid: str) -> datetime | None:
    """Extract the embedded datetime from an Elekta ScanUID string.

    Parameters
    ----------
    scan_uid : str
        Full ScanUID value, e.g.
        ``"1.3.46.423632.33783920233217242713.224.2023-03-21165402768"``

    Returns
    -------
    datetime or None
        Parsed datetime, or None if the pattern is not found.
    """
    match = _SCAN_DATETIME_PATTERN.search(scan_uid)
    if not match:
        logger.warning("Could not parse datetime from ScanUID: %s", scan_uid)
        return None

    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    # Time is HHMMSSmmm; left-pad in case a leading-zero hour was stripped.
    time_digits = match.group(4).rjust(9, "0")
    hour, minute = int(time_digits[0:2]), int(time_digits[2:4])
    second, ms = int(time_digits[4:6]), int(time_digits[6:9])
    try:
        return datetime(year, month, day, hour, minute, second, ms * 1000)
    except ValueError as exc:
        logger.warning("Invalid datetime values in ScanUID %s: %s", scan_uid, exc)
        return None


# ---------------------------------------------------------------------------
# _Frames.xml parsing
# ---------------------------------------------------------------------------

def parse_frames_xml(xml_path: Path) -> dict:
    """Parse a ``_Frames.xml`` file and return treatment + acquisition metadata.

    Refactored from ``scripts/elektafdt_crawler.py:get_plan_name_from_xml()``.

    Parameters
    ----------
    xml_path : Path
        Path to the ``_Frames.xml`` file.

    Returns
    -------
    dict
        Keys:
        - ``treatment_id`` (str or None) — ``<Treatment><ID>``
        - ``acquisition_preset`` (str or None) — ``<Image><AcquisitionPresetName>``
        - ``dicom_uid`` (str or None) — ``<Image><DicomUID>``
        - ``kv`` (float or None) — ``<Image><kV>``
        - ``ma`` (float or None) — ``<Image><mA>``
    """
    result: dict = {
        "treatment_id": None,
        "acquisition_preset": None,
        "dicom_uid": None,
        "kv": None,
        "ma": None,
    }
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Treatment ID
        treatment_el = root.find("Treatment")
        if treatment_el is not None:
            id_el = treatment_el.find("ID")
            if id_el is not None and id_el.text:
                result["treatment_id"] = id_el.text.strip()
                logger.info("Found treatment_id '%s' in %s", result["treatment_id"], xml_path)
        else:
            logger.warning("No Treatment/ID found in %s", xml_path)

        # Image acquisition metadata
        image_el = root.find("Image")
        if image_el is not None:
            preset_el = image_el.find("AcquisitionPresetName")
            if preset_el is not None and preset_el.text:
                result["acquisition_preset"] = preset_el.text.strip()

            uid_el = image_el.find("DicomUID")
            if uid_el is not None and uid_el.text:
                result["dicom_uid"] = uid_el.text.strip()

            kv_el = image_el.find("kV")
            if kv_el is not None and kv_el.text:
                try:
                    result["kv"] = float(kv_el.text.strip())
                except ValueError:
                    logger.warning("Non-numeric kV value in %s: %s", xml_path, kv_el.text)

            ma_el = image_el.find("mA")
            if ma_el is not None and ma_el.text:
                try:
                    result["ma"] = float(ma_el.text.strip())
                except ValueError:
                    logger.warning("Non-numeric mA value in %s: %s", xml_path, ma_el.text)

    except ET.ParseError as exc:
        logger.error("XML parse error in %s: %s", xml_path, exc)
    except OSError as exc:
        logger.error("Could not read %s: %s", xml_path, exc)

    return result


# ---------------------------------------------------------------------------
# Couch shift extraction from INI text
# ---------------------------------------------------------------------------

def parse_couch_shifts(ini_text: str) -> dict | None:
    """Extract CouchShiftLat/Long/Height from XVI INI text.

    Parameters
    ----------
    ini_text : str
        Raw INI text content (from ``.INI.XVI`` or plain INI file).

    Returns
    -------
    dict or None
        ``{"lateral": float, "longitudinal": float, "vertical": float}``
        if all three shift keys are found, otherwise None.
    """
    couch_lat = re.search(r"CouchShiftLat=(.+)", ini_text)
    couch_long = re.search(r"CouchShiftLong=(.+)", ini_text)
    couch_height = re.search(r"CouchShiftHeight=(.+)", ini_text)

    if couch_lat and couch_long and couch_height:
        try:
            return {
                "lateral": float(couch_lat.group(1).strip()),
                "longitudinal": float(couch_long.group(1).strip()),
                "vertical": float(couch_height.group(1).strip()),
            }
        except ValueError as exc:
            logger.warning("Non-numeric couch shift value: %s", exc)
            return None

    return None


# ---------------------------------------------------------------------------
# ZIP-embedded INI extraction from RPS DICOM
# ---------------------------------------------------------------------------

def extract_ini_from_rps(dcm_path: Path) -> str | None:
    """Read an Elekta RPS DICOM file and return the embedded INI text.

    The RPS DICOM stores a ZIP archive in private tag ``(0021,103A)``.
    Inside the ZIP is a ``.INI.XVI`` file with registration data.

    Refactored from ``scripts/extract_elekta_rps_matrices.py:extract_zip()``.

    Parameters
    ----------
    dcm_path : Path
        Path to the ``.RPS.dcm`` file.

    Returns
    -------
    str or None
        Raw INI text content, or None on failure.
    """
    try:
        import pydicom
    except ImportError:
        logger.error("pydicom is required for RPS extraction but not installed")
        return None

    try:
        dcm = pydicom.dcmread(str(dcm_path))
    except Exception as exc:
        logger.error("Failed to read DICOM %s: %s", dcm_path, exc)
        return None

    if RPS_ZIP_TAG not in dcm:
        logger.error("ZIP data tag %s not found in %s", RPS_ZIP_TAG, dcm_path)
        return None

    zip_data = dcm[RPS_ZIP_TAG].value
    try:
        zip_buffer = io.BytesIO(zip_data)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            ini_files = [f for f in zf.namelist() if f.endswith(".INI.XVI")]
            if not ini_files:
                logger.error("No .INI.XVI file in ZIP from %s", dcm_path)
                return None
            return zf.read(ini_files[0]).decode("utf-8", errors="ignore")
    except zipfile.BadZipFile:
        logger.error("Invalid ZIP data in %s", dcm_path)
        return None


# ---------------------------------------------------------------------------
# RTPLAN fraction count
# ---------------------------------------------------------------------------

def extract_planned_fractions(rtplan_path: Path) -> int | None:
    """Read an RTPLAN DICOM file and return ``NumberOfFractionsPlanned``.

    Reads ``(300A,0070) FractionGroupSequence`` and returns the
    ``(300A,0078) NumberOfFractionsPlanned`` value from its first item.
    Returns ``None`` (with a warning logged) if the file cannot be read,
    is not an RTPLAN, or lacks the expected sequence.

    Parameters
    ----------
    rtplan_path : Path
        Path to a DICOM RTPLAN file (Modality == ``"RTPLAN"``).

    Returns
    -------
    int or None
        Number of fractions planned, or None if unavailable.
    """
    try:
        import pydicom
    except ImportError:
        logger.error("pydicom is required for extract_planned_fractions but not installed")
        return None

    try:
        ds = pydicom.dcmread(str(rtplan_path), stop_before_pixels=True)
    except Exception as exc:
        logger.warning("Could not read RTPLAN %s: %s", rtplan_path, exc)
        return None

    fg_seq = getattr(ds, "FractionGroupSequence", None)
    if not fg_seq:
        logger.info("No FractionGroupSequence in %s", rtplan_path)
        return None

    first_group = fg_seq[0]
    n = getattr(first_group, "NumberOfFractionsPlanned", None)
    if n is None:
        logger.info("No NumberOfFractionsPlanned in %s", rtplan_path)
        return None

    try:
        return int(n)
    except (TypeError, ValueError):
        logger.warning("Non-integer NumberOfFractionsPlanned in %s: %r", rtplan_path, n)
        return None
