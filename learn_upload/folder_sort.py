"""Folder mapping and file sorting for the LEARN data transfer pipeline.

Automates the manual SOP steps of:
1. Discovering XVI acquisition sessions from patient IMAGES/ directories
2. Classifying sessions as CBCT, KIM Learning, or KIM MotionView
3. Assigning sessions to treatment fractions (FX0, FX1, ...)
4. Creating the LEARN hierarchical directory structure
5. Copying files to their correct destinations
"""

import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pydicom

from learn_upload.fraction_assignment import FractionResult
from learn_upload.utils import (
    extract_ini_from_rps,
    parse_couch_shifts,
    parse_frames_xml,
    parse_scan_datetime,
    parse_xvi_ini,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session dataclass
# ---------------------------------------------------------------------------

@dataclass
class CBCTSession:
    """Represents a single XVI acquisition session (img_* directory)."""

    img_dir: Path
    dicom_uid: str
    acquisition_preset: str
    session_type: str  # "cbct" | "kim_learning" | "motionview"
    treatment_id: str
    scan_datetime: datetime | None = None
    tube_kv: float | None = None
    tube_ma: float | None = None
    has_rps: bool = False
    rps_path: Path | None = None
    couch_shifts: dict | None = None
    ini_path: Path | None = None


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_acquisition(preset_name: str) -> str:
    """Classify an acquisition preset into session type.

    Parameters
    ----------
    preset_name : str
        AcquisitionPresetName from _Frames.xml.

    Returns
    -------
    str
        ``"motionview"``, ``"kim_learning"``, or ``"cbct"``.
    """
    lower = preset_name.lower()
    if "motionview" in lower:
        return "motionview"
    if "kim" in lower:
        return "kim_learning"
    return "cbct"


# ---------------------------------------------------------------------------
# Folder Mapper
# ---------------------------------------------------------------------------

class LearnFolderMapper:
    """Discovers XVI sessions and maps them to the LEARN directory structure."""

    def __init__(
        self,
        patient_dir: Path,
        anon_id: str,
        site_name: str,
        output_base: Path,
        images_subdir: str = "IMAGES",
    ) -> None:
        self.patient_dir = Path(patient_dir)
        self.anon_id = anon_id
        self.site_name = site_name
        self.output_base = Path(output_base)
        self.images_subdir = images_subdir

    # ----- DICOM classification -----

    _MODALITY_MAP = {
        "CT": "ct",
        "RTPLAN": "plan",
        "RTSTRUCT": "structures",
        "RTDOSE": "dose",
    }

    @staticmethod
    def classify_dicom_files(source_dir: Path) -> dict[str, list[Path]]:
        """Classify ``.dcm`` files by DICOM Modality tag ``(0008,0060)``.

        Recursively walks *source_dir* and reads only the Modality tag from
        each ``.dcm`` file to sort them into categories.

        Returns ``{"ct": [...], "plan": [...], "structures": [...], "dose": [...]}``.
        Files with unrecognised modality are logged as warnings and excluded.
        """
        source_dir = Path(source_dir)
        result: dict[str, list[Path]] = {
            "ct": [], "plan": [], "structures": [], "dose": [],
        }

        if not source_dir.is_dir():
            logger.warning("classify_dicom_files: directory not found: %s", source_dir)
            return result

        all_dcm = sorted(source_dir.rglob("*.dcm"), key=str) + sorted(
            source_dir.rglob("*.DCM"), key=str
        )
        # Deduplicate (case-insensitive filesystems)
        seen: set[Path] = set()
        unique: list[Path] = []
        for f in all_dcm:
            resolved = f.resolve()
            if resolved not in seen:
                seen.add(resolved)
                unique.append(f)

        for dcm_path in unique:
            try:
                ds = pydicom.dcmread(dcm_path, stop_before_pixels=True)
                modality = getattr(ds, "Modality", None) or ""
            except Exception:
                logger.warning("Could not read DICOM file: %s", dcm_path)
                continue

            category = LearnFolderMapper._MODALITY_MAP.get(modality.upper())
            if category:
                result[category].append(dcm_path)
            else:
                logger.warning(
                    "Unrecognised DICOM modality '%s' in %s — skipping",
                    modality,
                    dcm_path,
                )

        return result

    # ----- Discovery -----

    def discover_sessions(self, enrich: bool = True) -> list[CBCTSession]:
        """Scan IMAGES/img_* directories and build session objects.

        Returns
        -------
        list[CBCTSession]
            Sessions sorted by scan_datetime (None-datetime sessions at end).
        """
        images_dir = self.patient_dir / self.images_subdir
        if not images_dir.is_dir():
            logger.warning("No IMAGES directory in %s", self.patient_dir)
            return []

        sessions: list[CBCTSession] = []
        for img_dir in sorted(images_dir.iterdir()):
            if not img_dir.is_dir() or not img_dir.name.startswith("img_"):
                continue

            frames_xml = img_dir / "_Frames.xml"
            if not frames_xml.exists():
                logger.warning("No _Frames.xml in %s — skipping", img_dir)
                continue

            meta = parse_frames_xml(frames_xml)
            if meta.get("acquisition_preset") is None:
                logger.warning("No AcquisitionPresetName in %s — skipping", frames_xml)
                continue

            session_type = classify_acquisition(meta["acquisition_preset"])
            dicom_uid = meta.get("dicom_uid") or img_dir.name

            session = CBCTSession(
                img_dir=img_dir,
                dicom_uid=dicom_uid,
                acquisition_preset=meta["acquisition_preset"],
                session_type=session_type,
                treatment_id=meta.get("treatment_id") or "",
                tube_kv=meta.get("kv"),
                tube_ma=meta.get("ma"),
            )

            # Extract datetime and registration data (all session types)
            if enrich:
                self._enrich_cbct_session(session)

            sessions.append(session)

        # Sort: sessions with datetime first (chronological), None-datetime at end
        sessions.sort(key=lambda s: (s.scan_datetime is None, s.scan_datetime or datetime.min))
        return sessions

    def _enrich_cbct_session(self, session: CBCTSession) -> None:
        """Populate datetime, RPS, and couch shifts for a CBCT/KIM Learning session."""
        recon_dir = session.img_dir / "Reconstruction"

        # Find INI file for ScanUID → datetime
        if recon_dir.is_dir():
            ini_files = sorted(recon_dir.glob("*.INI"))
            if ini_files:
                session.ini_path = ini_files[0]
                ini_text = ini_files[0].read_text(encoding="utf-8", errors="ignore")
                ini_data = parse_xvi_ini(ini_text)
                scan_uid = ini_data.get("ScanUID")
                if scan_uid:
                    session.scan_datetime = parse_scan_datetime(scan_uid)

        # Find RPS DICOM → couch shifts
        rps_files = sorted(session.img_dir.glob("Reconstruction/*.dcm"))
        if not rps_files:
            rps_files = sorted(session.img_dir.glob("Reconstruction/*.RPS.dcm"))
        if rps_files:
            session.rps_path = rps_files[0]
            session.has_rps = True
            ini_text = extract_ini_from_rps(rps_files[0])
            if ini_text:
                session.couch_shifts = parse_couch_shifts(ini_text)

    # ----- MotionView date matching -----

    def _match_motionview_dates(
        self,
        dated: list[CBCTSession],
        undated: list[CBCTSession],
    ) -> None:
        """Assign scan_datetime to undated sessions by treatment_id and directory proximity.

        Matching strategy (in priority order):
        1. Same treatment_id → nearest by directory sort position
        2. No treatment_id match → nearest directory sort position overall

        All sessions share a parent directory; img_* names are sequential UIDs
        so alphabetical proximity correlates with temporal proximity.

        Mutates undated sessions in place.
        """
        if not dated or not undated:
            return

        # Build a sorted directory index for proximity lookups
        all_sessions = dated + undated
        sorted_names = sorted(s.img_dir.name for s in all_sessions)
        name_to_pos = {name: i for i, name in enumerate(sorted_names)}

        # Build lookup: treatment_id → list of dated sessions
        by_treatment: dict[str, list[CBCTSession]] = {}
        for d in dated:
            tid = d.treatment_id.strip()
            if tid:
                by_treatment.setdefault(tid, []).append(d)

        for mv_session in undated:
            best_match: CBCTSession | None = None
            mv_pos = name_to_pos.get(mv_session.img_dir.name, 0)

            # Strategy 1: match by treatment_id, pick nearest directory
            tid = mv_session.treatment_id.strip()
            candidates = by_treatment.get(tid, []) if tid else []
            if candidates:
                best_match = min(
                    candidates,
                    key=lambda d: abs(name_to_pos.get(d.img_dir.name, 0) - mv_pos),
                )

            # Strategy 2: fallback to nearest directory overall
            if best_match is None:
                best_match = min(
                    dated,
                    key=lambda d: abs(name_to_pos.get(d.img_dir.name, 0) - mv_pos),
                )

            if best_match and best_match.scan_datetime:
                mv_session.scan_datetime = best_match.scan_datetime
                logger.info(
                    "Matched undated session %s → %s (treatment=%s, date=%s)",
                    mv_session.img_dir.name,
                    best_match.img_dir.name,
                    best_match.treatment_id,
                    best_match.scan_datetime.strftime("%Y-%m-%d"),
                )
            else:
                logger.warning(
                    "Could not match undated session %s to any dated session",
                    mv_session.img_dir.name,
                )

    # ----- Fraction assignment -----

    def assign_fractions(self, sessions: list[CBCTSession]) -> dict[str, list[CBCTSession]]:
        """Group sessions into fractions by date.

        Parameters
        ----------
        sessions : list[CBCTSession]
            All sessions with scan_datetime assigned.

        Returns
        -------
        dict[str, list[CBCTSession]]
            ``{"FX0": [...], "FX1": [...], ...}`` sorted chronologically.
        """
        # Sort all sessions by datetime
        sorted_sessions = sorted(
            sessions,
            key=lambda s: s.scan_datetime or datetime.min,
        )

        # Group by date
        date_groups: dict[str, list[CBCTSession]] = {}
        for s in sorted_sessions:
            if s.scan_datetime is None:
                date_key = "unknown"
            else:
                date_key = s.scan_datetime.strftime("%Y-%m-%d")

            if date_key not in date_groups:
                date_groups[date_key] = []
            date_groups[date_key].append(s)

        # Assign fraction labels in chronological order
        fraction_map: dict[str, list[CBCTSession]] = {}
        for fx_idx, date_key in enumerate(sorted(date_groups.keys()), start=1):
            fx_label = f"FX{fx_idx}"
            fraction_map[fx_label] = date_groups[date_key]

        return fraction_map

    # ----- Directory creation -----

    def create_learn_structure(
        self,
        fraction_map: dict[str, list[CBCTSession]],
        trajectory_fx_labels: list[str] | None = None,
    ) -> Path:
        """Create the full LEARN directory tree.

        Parameters
        ----------
        fraction_map : dict
            Fraction label → list of sessions (for Patient Images).
        trajectory_fx_labels : list[str], optional
            Fraction labels (e.g. ``["FX01", "FX02"]``) for Trajectory Logs
            directories.  If *None*, trajectory dirs are not created.

        Returns the site root path.
        """
        site_root = self.output_base / self.site_name

        # Patient Files
        patient_files = site_root / "Patient Files" / self.anon_id
        patient_files.mkdir(parents=True, exist_ok=True)

        # Patient Plans
        plans_root = site_root / "Patient Plans" / self.anon_id
        for subdir in ("CT", "Plan", "Dose", "Structure Set"):
            (plans_root / subdir).mkdir(parents=True, exist_ok=True)

        # Ground Truth
        gt_root = site_root / "Ground Truth" / self.anon_id
        gt_root.mkdir(parents=True, exist_ok=True)

        # Patient Images — per fraction
        images_root = site_root / "Patient Images" / self.anon_id
        for fx_label, sessions in fraction_map.items():
            fx_path = images_root / fx_label

            # Count CBCT/KIM-Learning sessions for numbering
            cbct_sessions = [
                s for s in sessions if s.session_type in ("cbct", "kim_learning")
            ]
            cbct_sessions.sort(key=lambda s: s.scan_datetime or datetime.min)

            for cbct_idx, _session in enumerate(cbct_sessions, start=1):
                cbct_path = fx_path / "CBCT" / f"CBCT{cbct_idx}"
                (cbct_path / "CBCT Projections" / "CDOG").mkdir(parents=True, exist_ok=True)
                (cbct_path / "CBCT Projections" / "IPS").mkdir(parents=True, exist_ok=True)
                (cbct_path / "Reconstructed CBCT").mkdir(parents=True, exist_ok=True)
                (cbct_path / "Registration file").mkdir(parents=True, exist_ok=True)

            # KIM-KV directory (always created per fraction)
            (fx_path / "KIM-KV").mkdir(parents=True, exist_ok=True)

        # Trajectory Logs — per fraction label
        if trajectory_fx_labels:
            for fx_label in trajectory_fx_labels:
                traj_fx = site_root / "Trajectory Logs" / self.anon_id / fx_label
                (traj_fx / "Trajectory Logs").mkdir(parents=True, exist_ok=True)
                (traj_fx / "Treatment Records").mkdir(parents=True, exist_ok=True)

        return site_root

    # ----- File copying -----

    def copy_cbct_files(self, session: CBCTSession, cbct_path: Path) -> dict:
        """Copy CBCT/KIM-Learning files to the LEARN structure (raw, no anonymisation).

        Returns ``{"his": N, "scan": M, "rps": K, "frames_xml": 0|1, "ini": P}``.
        """
        counts = {"his": 0, "scan": 0, "rps": 0, "frames_xml": 0, "ini": 0}

        # .his → CBCT Projections/IPS/
        ips_dir = cbct_path / "CBCT Projections" / "IPS"
        ips_dir.mkdir(parents=True, exist_ok=True)
        for his_file in sorted(session.img_dir.glob("*.his")):
            shutil.copy2(his_file, ips_dir / his_file.name)
            counts["his"] += 1

        # _Frames.xml → CBCT Projections/IPS/_Frames.xml (raw copy)
        frames_xml = session.img_dir / "_Frames.xml"
        if frames_xml.exists():
            shutil.copy2(frames_xml, ips_dir / "_Frames.xml")
            counts["frames_xml"] = 1

        # Reconstruction/ → Reconstructed CBCT/
        recon_dest = cbct_path / "Reconstructed CBCT"
        recon_dest.mkdir(parents=True, exist_ok=True)
        recon_src = session.img_dir / "Reconstruction"
        if recon_src.is_dir():
            for recon_file in sorted(recon_src.iterdir()):
                if ".SCAN" in recon_file.name.upper():
                    shutil.copy2(recon_file, recon_dest / recon_file.name)
                    counts["scan"] += 1
                elif recon_file.name.upper().endswith((".INI", ".INI.XVI")):
                    shutil.copy2(recon_file, recon_dest / recon_file.name)
                    counts["ini"] += 1

        # RPS → Registration file/ (raw copy)
        if session.rps_path and session.rps_path.exists():
            reg_dest = cbct_path / "Registration file"
            reg_dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(session.rps_path, reg_dest / session.rps_path.name)
            counts["rps"] += 1

        return counts

    def copy_motionview_files(self, session: CBCTSession, fx_path: Path) -> dict:
        """Copy MotionView .his files to KIM-KV/{img_dirname}/.

        Returns ``{"his": N, "frames_xml": 0|1}``.
        """
        dest = fx_path / "KIM-KV" / session.img_dir.name
        dest.mkdir(parents=True, exist_ok=True)
        counts = {"his": 0, "frames_xml": 0}
        for his_file in sorted(session.img_dir.glob("*.his")):
            shutil.copy2(his_file, dest / his_file.name)
            counts["his"] += 1

        # _Frames.xml → KIM-KV/{img_dir}/_Frames.xml (raw copy)
        frames_xml = session.img_dir / "_Frames.xml"
        if frames_xml.exists():
            shutil.copy2(frames_xml, dest / "_Frames.xml")
            counts["frames_xml"] = 1

        return counts

    def copy_anonymised_plans(
        self,
        anon_ct_dir: Path = None,
        anon_plan_dir: Path = None,
        anon_struct_dir: Path = None,
        anon_dose_dir: Path = None,
    ) -> dict:
        """Copy anonymised DICOM files to the LEARN structure.

        Returns ``{"ct_count": N, "plan_count": M, "structures_count": P, "dose_count": Q}``.
        """
        site_root = self.output_base / self.site_name
        plans_root = site_root / "Patient Plans" / self.anon_id
        counts = {
            "ct_count": 0,
            "plan_count": 0,
            "structures_count": 0,
            "dose_count": 0,
        }

        mapping = [
            (anon_ct_dir, "CT", "ct_count"),
            (anon_plan_dir, "Plan", "plan_count"),
            (anon_struct_dir, "Structure Set", "structures_count"),
            (anon_dose_dir, "Dose", "dose_count"),
        ]

        for src_dir, dest_name, count_key in mapping:
            if src_dir is None:
                continue
            src_dir = Path(src_dir)
            if not src_dir.is_dir():
                continue
            dest = plans_root / dest_name
            dest.mkdir(parents=True, exist_ok=True)
            for f in sorted(src_dir.rglob("*")):
                if f.is_file():
                    shutil.copy2(f, dest / f.name)
                    counts[count_key] += 1

        return counts

    # ----- Centroid file -----

    def copy_centroid_file(self, centroid_path: Path) -> Path:
        """Copy a centroid file to Patient Files/{anon_id}/ (raw, no anonymisation).

        Anonymisation is handled separately by the anonymise module.

        Returns the output file path.
        """
        centroid_path = Path(centroid_path)

        site_root = self.output_base / self.site_name
        dest_dir = site_root / "Patient Files" / self.anon_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        output_path = dest_dir / centroid_path.name

        shutil.copy2(centroid_path, output_path)
        logger.info("Copied centroid -> %s", output_path.name)
        return output_path

    # ----- Trajectory logs -----

    def copy_trajectory_logs(self, trajectory_base_dir: Path) -> dict:
        """Copy KIM trajectory log files to the LEARN Trajectory Logs structure (raw).

        Auto-discovers FX## directories under *trajectory_base_dir* and copies
        all files as-is.  Anonymisation is handled separately by the anonymise
        module.

        Returns ``{"fx_count": N, "files_copied": M}``.
        """
        trajectory_base_dir = Path(trajectory_base_dir)
        site_root = self.output_base / self.site_name

        # Auto-discover FX## directories
        fx_dirs = sorted(
            d for d in trajectory_base_dir.iterdir()
            if d.is_dir() and re.match(r"FX\d+", d.name, re.IGNORECASE)
        )

        counts = {"fx_count": 0, "files_copied": 0}

        for fx_dir in fx_dirs:
            fx_label = fx_dir.name  # e.g. "FX01"
            dest_traj = (
                site_root / "Trajectory Logs" / self.anon_id
                / fx_label / "Trajectory Logs"
            )
            dest_traj.mkdir(parents=True, exist_ok=True)
            # Also create Treatment Records sibling
            dest_treat = (
                site_root / "Trajectory Logs" / self.anon_id
                / fx_label / "Treatment Records"
            )
            dest_treat.mkdir(parents=True, exist_ok=True)

            counts["fx_count"] += 1

            for f in sorted(fx_dir.iterdir()):
                if not f.is_file():
                    continue
                shutil.copy2(f, dest_traj / f.name)
                counts["files_copied"] += 1

        logger.info("Trajectory logs copied: %s", counts)
        return counts

    # ----- Current Calibrations -----

    def copy_calibrations(
        self,
        calibrations_dir: Path,
        fraction_map: dict[str, list],
    ) -> dict:
        """Copy a Current Calibration folder into every fraction directory.

        Parameters
        ----------
        calibrations_dir : Path
            Source directory containing calibration files.
        fraction_map : dict[str, list[CBCTSession]]
            Fraction label → list of sessions (determines FX labels).

        Returns
        -------
        dict
            ``{"fx_count": N, "files_copied": M}``.
        """
        calibrations_dir = Path(calibrations_dir)
        site_root = self.output_base / self.site_name
        images_root = site_root / "Patient Images" / self.anon_id

        counts = {"fx_count": 0, "files_copied": 0}

        for fx_label in sorted(fraction_map.keys()):
            dest = images_root / fx_label / "CurrentCalibrations"
            shutil.copytree(calibrations_dir, dest, dirs_exist_ok=True)
            counts["fx_count"] += 1
            counts["files_copied"] += sum(1 for f in dest.rglob("*") if f.is_file())

        logger.info("Calibrations copied: %s", counts)
        return counts

    # ----- Execute -----

    def execute(
        self,
        centroid_path: Path = None,
        trajectory_base_dir: Path = None,
        calibrations_dir: Path = None,
        fraction_result: FractionResult | None = None,
        dry_run: bool = False,
        progress_callback=None,
    ) -> dict:
        """Run the full folder mapping pipeline (raw copy, no anonymisation).

        Parameters
        ----------
        centroid_path : Path, optional
            Path to a centroid file to copy.
        trajectory_base_dir : Path, optional
            Base directory containing FX## trajectory log folders.
        dry_run : bool
            If True, create directories but skip file copies.

        Returns
        -------
        dict
            Summary with keys: sessions, fractions, files_copied, dry_run.
        """
        # 1-3. Fractions: use the supplied ground-truth result, or fall back to
        # legacy date-based grouping for non-GUI callers.
        if fraction_result is not None:
            fraction_map = {
                label: fraction_result.assignments.get(label, [])
                for label in fraction_result.fraction_labels
            }
            sessions = [s for group in fraction_map.values() for s in group]
            logger.info(
                "Using supplied FractionResult: %d fractions, %d assigned sessions",
                len(fraction_map),
                len(sessions),
            )
        else:
            sessions = self.discover_sessions()
            logger.info("Discovered %d sessions", len(sessions))
            dated = [s for s in sessions if s.scan_datetime is not None]
            undated = [s for s in sessions if s.scan_datetime is None]
            if undated:
                self._match_motionview_dates(dated, undated)
            fraction_map = self.assign_fractions(sessions)
            logger.info("Assigned %d fractions", len(fraction_map))

        # 4. Discover trajectory FX labels for directory creation
        trajectory_fx_labels = None
        if trajectory_base_dir:
            trajectory_base_dir = Path(trajectory_base_dir)
            if trajectory_base_dir.is_dir():
                trajectory_fx_labels = sorted(
                    d.name for d in trajectory_base_dir.iterdir()
                    if d.is_dir() and re.match(r"FX\d+", d.name, re.IGNORECASE)
                )

        # 5. Create directory structure
        site_root = self.create_learn_structure(fraction_map, trajectory_fx_labels)

        summary = {
            "sessions": len(sessions),
            "fractions": len(fraction_map),
            "files_copied": {
                "his": 0, "scan": 0, "rps": 0, "ini": 0,
                "motionview": 0, "frames_xml": 0,
            },
            "dry_run": dry_run,
        }

        if dry_run:
            logger.info("Dry run — directories created, no files copied")
            return summary

        def _progress(current: int, total: int, msg: str) -> None:
            if progress_callback:
                progress_callback(current, total, msg)

        # 6. Copy files
        total_sessions = len(sessions)
        completed_sessions = 0
        images_root = site_root / "Patient Images" / self.anon_id
        for fx_label, sessions_in_fx in fraction_map.items():
            fx_path = images_root / fx_label

            cbct_sessions = [
                s for s in sessions_in_fx if s.session_type in ("cbct", "kim_learning")
            ]
            cbct_sessions.sort(key=lambda s: s.scan_datetime or datetime.min)

            for cbct_idx, session in enumerate(cbct_sessions, start=1):
                cbct_path = fx_path / "CBCT" / f"CBCT{cbct_idx}"
                _progress(completed_sessions, total_sessions, f"{fx_label}/CBCT{cbct_idx}")
                counts = self.copy_cbct_files(session, cbct_path)
                summary["files_copied"]["his"] += counts["his"]
                summary["files_copied"]["scan"] += counts["scan"]
                summary["files_copied"]["rps"] += counts["rps"]
                summary["files_copied"]["ini"] += counts["ini"]
                summary["files_copied"]["frames_xml"] += counts["frames_xml"]
                completed_sessions += 1

            mv_sessions = [
                s for s in sessions_in_fx if s.session_type == "motionview"
            ]
            for session in mv_sessions:
                _progress(completed_sessions, total_sessions, f"{fx_label}/KIM-KV")
                mv_counts = self.copy_motionview_files(session, fx_path)
                summary["files_copied"]["motionview"] += mv_counts["his"]
                summary["files_copied"]["frames_xml"] += mv_counts["frames_xml"]
                completed_sessions += 1

        _progress(total_sessions, total_sessions, "File copy complete")

        # 7. Copy centroid file
        if centroid_path:
            centroid_path = Path(centroid_path)
            if centroid_path.exists():
                self.copy_centroid_file(centroid_path)
                summary["files_copied"]["centroid"] = 1

        # 8. Copy trajectory logs
        if trajectory_base_dir and Path(trajectory_base_dir).is_dir():
            traj_counts = self.copy_trajectory_logs(trajectory_base_dir)
            summary["files_copied"]["trajectory"] = traj_counts["files_copied"]

        # 9. Copy current calibrations
        if calibrations_dir and Path(calibrations_dir).is_dir():
            cal_counts = self.copy_calibrations(Path(calibrations_dir), fraction_map)
            summary["files_copied"]["calibrations"] = cal_counts["files_copied"]

        logger.info("Execute complete: %s", summary)
        return summary
