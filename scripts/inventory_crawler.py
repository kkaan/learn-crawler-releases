"""LEARN trial data inventory crawler.

Walks an XVI processed root (e.g. ``E:\\XVI_COLLECTION\\processed``), filters
to machines with calibration FlexMap files, and emits one CSV row per
``IMAGES/img_<UID>`` folder capturing treatment plan, FOV, planned fractions,
and acquisition timestamp.

Usage:
    python scripts/inventory_crawler.py [--root PATH] [--output PATH] [--log-level LEVEL]
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo root is on sys.path so the learn_upload package is importable
# even when this file is invoked as a script.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from learn_upload.config import DEFAULT_XVI_BASE, setup_logging  # noqa: E402
from learn_upload.utils import (  # noqa: E402  (import after sys.path tweak)
    extract_planned_fractions,
    parse_frames_xml,
    parse_scan_datetime,
    parse_xvi_ini,
)

logger = logging.getLogger(__name__)

# Calibration files live at:
#   <machine>\Current Calibration Files\Current\FlexMap\*.flexmap
FLEXMAP_SUBPATH = Path("Current Calibration Files") / "Current" / "FlexMap"


def find_machines_with_flexmaps(processed_root: Path) -> list[Path]:
    """Return machine directories under ``processed_root`` containing flexmap files.

    A machine qualifies if at least one ``*.flexmap`` file exists under
    ``<machine>/Current Calibration Files/Current/FlexMap/``.

    Parameters
    ----------
    processed_root : Path
        Root directory containing ``<Date_Center_Machine>`` subdirectories.

    Returns
    -------
    list[Path]
        Sorted list of machine directories with at least one flexmap.
    """
    if not processed_root.is_dir():
        logger.error("Processed root does not exist or is not a directory: %s", processed_root)
        return []

    machines: list[Path] = []
    for entry in sorted(processed_root.iterdir()):
        if not entry.is_dir():
            continue
        flexmap_dir = entry / FLEXMAP_SUBPATH
        if not flexmap_dir.is_dir():
            logger.info("No flexmap dir under %s — skipping machine", entry.name)
            continue
        flexmaps = list(flexmap_dir.glob("*.flexmap"))
        if not flexmaps:
            logger.info("Flexmap dir present but empty under %s — skipping", entry.name)
            continue
        logger.info("Machine %s has %d flexmap file(s)", entry.name, len(flexmaps))
        machines.append(entry)
    return machines


def find_patient_folders(machine_dir: Path) -> list[Path]:
    """Return ``patient_*`` subdirectories of a machine directory, sorted.

    Mirrors the discovery convention used by ``scripts/elektafdt_crawler.py:69-94``.
    """
    if not machine_dir.is_dir():
        logger.warning("Machine directory not found: %s", machine_dir)
        return []
    return sorted(
        p for p in machine_dir.iterdir()
        if p.is_dir() and p.name.startswith("patient_")
    )


def _pick_recon_file(recon_dir: Path, img_uid: str, suffix: str) -> Path | None:
    """Choose the right Reconstruction/ file for an img_<UID> folder.

    Prefers the exact ``<img_uid><suffix>`` filename (the bare-UID file the
    user spec refers to). Falls back to the first sorted match for ``*<suffix>``
    if the exact filename isn't present.

    Note: ``glob("*.INI")`` does NOT match ``*.INI.XVI`` (the suffix differs),
    so the two suffixes can be queried independently without crosstalk.
    """
    preferred = recon_dir / f"{img_uid}{suffix}"
    if preferred.exists():
        return preferred
    candidates = sorted(recon_dir.glob(f"*{suffix}"))
    return candidates[0] if candidates else None


@dataclass
class ImgRecord:
    """One inventory row corresponding to a single ``IMAGES/img_<UID>/`` folder."""
    machine: str
    patient_folder: str
    img_uid: str
    treatment_id: str | None
    fov: str | None
    scan_datetime: datetime | None
    planned_fractions: int | None  # populated later in trawl_machine
    img_dir: Path


def iter_img_records(patient_dir: Path) -> Iterator[ImgRecord]:
    """Yield one ``ImgRecord`` per ``IMAGES/img_<UID>/`` directory.

    Per-img extraction:
      * ``treatment_id`` from ``_Frames.xml`` ``<Treatment><ID>``
        (via ``learn_upload.utils.parse_frames_xml``).
      * ``fov`` from ``Reconstruction/<UID>.INI.XVI`` ``FOV=`` line
        (via ``learn_upload.utils.parse_xvi_ini``).
      * ``scan_datetime`` parsed from ``ScanUID`` if present.

    ``planned_fractions`` is left as ``None`` here; ``trawl_machine`` fills it
    once per patient (it is plan-level data, not per-image).
    """
    images_dir = patient_dir / "IMAGES"
    if not images_dir.is_dir():
        logger.info("No IMAGES dir in %s", patient_dir)
        return

    for img_dir in sorted(images_dir.iterdir()):
        if not img_dir.is_dir() or not img_dir.name.startswith("img_"):
            continue
        img_uid = img_dir.name[len("img_"):]

        treatment_id: str | None = None
        frames_xml = img_dir / "_Frames.xml"
        if frames_xml.exists():
            meta = parse_frames_xml(frames_xml)
            treatment_id = meta.get("treatment_id")
        else:
            logger.warning("No _Frames.xml in %s", img_dir)

        fov: str | None = None
        scan_dt: datetime | None = None
        recon_dir = img_dir / "Reconstruction"
        if recon_dir.is_dir():
            # FOV: <img_uid>.INI.XVI is authoritative (per user spec). The
            # Reconstruction folder also contains <img_uid>.<datetime>.INI.XVI
            # which omits FOV (it stores reconstruction params only). Picking
            # the bare-UID file by exact name avoids the alphabetical-sort trap
            # where the timestamped sibling sorts first ('2' < 'I' in ASCII).
            target_xvi = _pick_recon_file(recon_dir, img_uid, suffix=".INI.XVI")
            if target_xvi is not None:
                ini_data = parse_xvi_ini(
                    target_xvi.read_text(encoding="utf-8", errors="ignore")
                )
                fov = ini_data.get("FOV")

            # ScanUID lives in the plain <img_uid>.INI file (not .INI.XVI),
            # consistent with the convention in learn_upload/folder_sort.py:219.
            target_ini = _pick_recon_file(recon_dir, img_uid, suffix=".INI")
            if target_ini is not None:
                ini_data = parse_xvi_ini(
                    target_ini.read_text(encoding="utf-8", errors="ignore")
                )
                scan_uid = ini_data.get("ScanUID")
                if scan_uid:
                    scan_dt = parse_scan_datetime(scan_uid)

        yield ImgRecord(
            machine=patient_dir.parent.name,
            patient_folder=patient_dir.name,
            img_uid=img_uid,
            treatment_id=treatment_id,
            fov=fov,
            scan_datetime=scan_dt,
            planned_fractions=None,
            img_dir=img_dir,
        )


def _is_rtplan(dcm_path: Path) -> bool:
    """Cheaply check whether a .dcm file has Modality == 'RTPLAN'.

    Uses ``pydicom.dcmread(..., specific_tags=["Modality"])`` so we only read
    the Modality tag — important when sweeping hundreds of DICOM files.
    """
    try:
        import pydicom
        ds = pydicom.dcmread(
            str(dcm_path), stop_before_pixels=True, specific_tags=["Modality"],
        )
        return getattr(ds, "Modality", "").upper() == "RTPLAN"
    except Exception:
        return False


def find_planned_fractions_for_patient(patient_dir: Path) -> int | None:
    """Search a patient directory for an RTPLAN DICOM and return its fraction count.

    Order of search:
      1. ``patient_dir/DICOM_PLAN/**/*.dcm`` — preferred location.
      2. Recursive ``patient_dir/**/*.dcm`` fallback (if no RTPLAN was found
         in DICOM_PLAN, e.g. only RTSTRUCT was present there).

    Files are filtered by DICOM ``Modality == "RTPLAN"`` (per the convention
    in ``learn_upload/folder_sort.py`` ``_MODALITY_MAP``). Returns the first
    fraction count found, or ``None`` if no usable RTPLAN exists.
    """
    if not patient_dir.is_dir():
        return None

    # Preferred: DICOM_PLAN/
    plan_dir = patient_dir / "DICOM_PLAN"
    rtplans_in_plan_dir: list[Path] = []
    if plan_dir.is_dir():
        rtplans_in_plan_dir = [p for p in sorted(plan_dir.rglob("*.dcm")) if _is_rtplan(p)]

    candidates = rtplans_in_plan_dir
    if not candidates:
        # Fallback: anywhere under patient_dir
        candidates = [p for p in sorted(patient_dir.rglob("*.dcm")) if _is_rtplan(p)]

    for dcm in candidates:
        n = extract_planned_fractions(dcm)
        if n is not None:
            return n

    logger.info("No RTPLAN with NumberOfFractionsPlanned for %s", patient_dir.name)
    return None


def trawl_machine(machine_dir: Path) -> list[ImgRecord]:
    """Walk every patient and image under one machine; return all ImgRecords.

    Each record's ``planned_fractions`` is filled in once per patient
    (since fraction count is plan-level metadata).
    """
    records: list[ImgRecord] = []
    patients = find_patient_folders(machine_dir)
    for patient_dir in patients:
        fractions = find_planned_fractions_for_patient(patient_dir)
        for rec in iter_img_records(patient_dir):
            rec.planned_fractions = fractions
            records.append(rec)
    logger.info(
        "Trawled %s: %d image records across %d patients",
        machine_dir.name, len(records), len(patients),
    )
    return records


def trawl_root(processed_root: Path) -> list[ImgRecord]:
    """Trawl every flexmap-equipped machine under ``processed_root``.

    Machines lacking a flexmap calibration directory are logged and skipped
    (they cannot contribute usable trial data).
    """
    machines = find_machines_with_flexmaps(processed_root)
    if not machines:
        logger.warning("No machines with flexmaps found under %s", processed_root)
        return []

    all_records: list[ImgRecord] = []
    for machine_dir in machines:
        all_records.extend(trawl_machine(machine_dir))
    logger.info(
        "Trawl complete: %d total image records across %d machines",
        len(all_records), len(machines),
    )
    return all_records


CSV_HEADERS = [
    "machine",
    "patient_folder",
    "img_uid",
    "treatment_id",
    "fov",
    "scan_datetime",
    "planned_fractions",
    "img_dir",
]


def write_inventory_csv(records: list[ImgRecord], output_path: Path) -> None:
    """Write inventory records to CSV.

    Empty/None fields are rendered as empty strings (not the literal "None").
    Datetimes are rendered ISO 8601. Parent directories are created if needed.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADERS)
        for r in records:
            writer.writerow([
                r.machine,
                r.patient_folder,
                r.img_uid,
                r.treatment_id or "",
                r.fov or "",
                r.scan_datetime.isoformat(timespec="seconds") if r.scan_datetime else "",
                r.planned_fractions if r.planned_fractions is not None else "",
                str(r.img_dir),
            ])
    logger.info("Wrote %d rows to %s", len(records), output_path)


def _default_output_path() -> Path:
    """``Data/inventory/inventory_<UTC-timestamp>.csv`` relative to repo root."""
    repo_root = Path(__file__).resolve().parents[1]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return repo_root / "Data" / "inventory" / f"inventory_{stamp}.csv"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Trawl XVI processed root, emit one CSV row per CBCT img folder.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        # NOTE: DEFAULT_XVI_BASE points at one machine; for a multi-machine trawl
        # pass --root E:\XVI_COLLECTION\processed explicitly. Default here is its
        # parent so a bare invocation walks all machines under processed/.
        default=DEFAULT_XVI_BASE.parent,
        help="Root containing <Date_Center_Machine> subdirectories "
             "(default: parent of DEFAULT_XVI_BASE)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="CSV output path (default: Data/inventory/inventory_<UTC-timestamp>.csv)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    args = parser.parse_args(argv)

    setup_logging(level=getattr(logging, args.log_level))

    output_path = args.output or _default_output_path()
    logger.info("Trawling %s -> %s", args.root, output_path)

    records = trawl_root(args.root)
    write_inventory_csv(records, output_path)

    print(f"Wrote {len(records)} rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
