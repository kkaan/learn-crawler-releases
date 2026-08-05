"""Ground-truth fraction assignment for the LEARN pipeline.

Two strategies decide which treatment fraction each XVI session belongs to:

* ``TrajectoryGroundTruth`` (PRIME): the name of the FXnn/ folder holding the
  KIM trajectory logs is the fraction number. Every img_<UID> session those logs
  reference (MotionView and KIM-Learning alike) belongs to that fraction; the
  dated ones anchor the fraction's date so unreferenced setup CBCTs can attach by
  shared acquisition date.
* ``ManualDateTable`` (non-PRIME): a user-supplied date -> fraction mapping.

Both return a ``FractionResult``. This module is pure domain logic: it reads
trajectory-log text but performs no copying and has no GUI dependency.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from learn_upload.folder_sort import CBCTSession

logger = logging.getLogger(__name__)

_FX_FOLDER_RE = re.compile(r"^FX(\d+)(?:-(\d+))?$", re.IGNORECASE)
# img_<UID> dir names are digit groups joined by dots; anchoring to that shape
# stops the match cleanly at any separator (\, /, quote, space) after the UID.
_IMG_REF_RE = re.compile(r"img_[0-9]+(?:\.[0-9]+)+")
_TRAJECTORY_GLOB = "MarkerLocations*.txt"

CBCT_LIKE = ("cbct", "kim_learning")
KIM_KV = "motionview"

# Sort key for labels that don't match the FX pattern: places them after all FX.
_NON_FX_SORT_LAST = 10**9


@dataclass
class FractionResult:
    """The outcome of assigning sessions to fractions."""

    assignments: dict[str, list[CBCTSession]] = field(default_factory=dict)
    fraction_labels: list[str] = field(default_factory=list)
    unmatched: list[CBCTSession] = field(default_factory=list)
    ambiguous: list[tuple[CBCTSession, list[str]]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def parse_trajectory_referenced_uids(log_path: Path) -> set[str]:
    """Return the set of ``img_<UID>`` directory names referenced in a KIM log.

    ``MarkerLocations*.txt`` files carry a ``Filename`` column with absolute
    paths like ``X:\\patient_x\\IMAGES\\img_<UID>\\00001.<UID>.his``.
    """
    text = Path(log_path).read_text(encoding="utf-8", errors="ignore")
    return set(_IMG_REF_RE.findall(text))


def discover_trajectory_folders(source_root: Path) -> dict[str, Path]:
    """Map ``FXnn`` folder name -> path for folders that contain KIM logs."""
    source_root = Path(source_root)
    folders: dict[str, Path] = {}
    if not source_root.is_dir():
        return folders
    for child in sorted(source_root.iterdir()):
        if not child.is_dir() or not _FX_FOLDER_RE.match(child.name):
            continue
        if any(child.glob(_TRAJECTORY_GLOB)):
            folders[child.name] = child
    return folders


def base_number(label: str) -> str:
    """Return the leading FX number of a fraction label (``FX13-1`` -> ``"13"``)."""
    match = _FX_FOLDER_RE.match(label)
    return match.group(1) if match else label


def select_base_label(labels: list[str]) -> str:
    """Pick the base folder of a same-number group: un-suffixed, else lowest suffix."""

    def sort_key(label: str):
        match = _FX_FOLDER_RE.match(label)
        suffix = match.group(2) if match and match.group(2) else None
        return (suffix is not None, int(suffix) if suffix else -1)

    return sorted(labels, key=sort_key)[0]


def fraction_sort_key(label: str) -> tuple[int, int, str]:
    """Natural sort key so FX2 < FX13 < FX13-1."""
    match = _FX_FOLDER_RE.match(label)
    if not match:
        return (_NON_FX_SORT_LAST, 0, label)  # non-FX labels sort after all FX labels
    suffix = int(match.group(2)) if match.group(2) else -1
    return (int(match.group(1)), suffix, label)


class TrajectoryGroundTruth:
    """PRIME strategy: trajectory folder names are the fraction ground truth."""

    def __init__(self, source_root: Path) -> None:
        self.source_root = Path(source_root)

    def assign(self, sessions: list[CBCTSession]) -> FractionResult:
        folders = discover_trajectory_folders(self.source_root)
        result = FractionResult()
        result.fraction_labels = sorted(folders, key=fraction_sort_key)
        result.assignments = {label: [] for label in result.fraction_labels}

        # base label per base number (FX13 is base for FX13 + FX13-1)
        groups: dict[str, list[str]] = {}
        for label in folders:
            groups.setdefault(base_number(label), []).append(label)
        base_label_for = {num: select_base_label(lbls) for num, lbls in groups.items()}

        # img_<UID> -> fraction label, from the trajectory logs
        uid_to_fraction: dict[str, str] = {}
        referenced_uids: set[str] = set()
        for label, folder in folders.items():
            for log in sorted(folder.glob(_TRAJECTORY_GLOB)):
                for uid in parse_trajectory_referenced_uids(log):
                    referenced_uids.add(uid)
                    uid_to_fraction[uid] = label

        session_names = {s.img_dir.name for s in sessions}

        # 1. Assign every trajectory-referenced session by UID — regardless of
        #    session type (the logs reference both MotionView and KIM-Learning
        #    img dirs).  Dated referenced sessions anchor the fraction's date so
        #    unreferenced setup CBCTs can attach to it later.  This avoids relying
        #    on MotionView dates, which the export does not record.
        date_candidates: dict[date, set[str]] = {}
        assigned_names: set[str] = set()
        for s in sessions:
            label = uid_to_fraction.get(s.img_dir.name)
            if label is None:
                continue
            result.assignments[label].append(s)
            assigned_names.add(s.img_dir.name)
            if s.scan_datetime is not None:
                base = base_label_for[base_number(label)]
                date_candidates.setdefault(s.scan_datetime.date(), set()).add(base)

        # referenced-but-missing sessions -> note
        for uid in sorted(referenced_uids):
            if uid not in session_names:
                result.notes.append(
                    f"Trajectory log references {uid} but it is not in the export"
                )

        # 2. Unreferenced sessions: CBCT-like attach by shared date with a
        #    fraction's dated sessions; an unreferenced KIM-KV (MotionView) or an
        #    undated CBCT cannot be placed and is flagged for the user.
        for s in sessions:
            if s.img_dir.name in assigned_names:
                continue
            if s.session_type == KIM_KV or s.scan_datetime is None:
                result.unmatched.append(s)
                continue
            cands = date_candidates.get(s.scan_datetime.date())
            if not cands:
                result.unmatched.append(s)
            elif len(cands) == 1:
                result.assignments[next(iter(cands))].append(s)
            else:
                result.ambiguous.append((s, sorted(cands, key=fraction_sort_key)))

        return result


class ManualDateTable:
    """Non-PRIME strategy: a user-supplied date -> fraction-label mapping."""

    def __init__(self, date_to_fraction: dict[date, str]) -> None:
        self.date_to_fraction = date_to_fraction

    def assign(self, sessions: list[CBCTSession]) -> FractionResult:
        result = FractionResult()
        result.fraction_labels = sorted(
            set(self.date_to_fraction.values()), key=fraction_sort_key
        )
        result.assignments = {label: [] for label in result.fraction_labels}
        for s in sessions:
            if s.scan_datetime is None:
                result.unmatched.append(s)
                continue
            label = self.date_to_fraction.get(s.scan_datetime.date())
            if label is None:
                result.unmatched.append(s)
            else:
                result.assignments[label].append(s)
        return result


# ---------------------------------------------------------------------------
# GUI helper pure functions (kept here for unit-testability without Qt)
# ---------------------------------------------------------------------------


def has_trajectory_folders(source_root: Path) -> bool:
    """True if the source contains FXnn folders with KIM trajectory logs."""
    return bool(discover_trajectory_folders(source_root))


def format_fraction_label(number: str | int) -> str:
    """Format a user-entered fraction number as a label (``5`` -> ``"FX5"``)."""
    return f"FX{int(number)}"


def normalize_fraction_label(text: str) -> str:
    """Coerce user-entered fraction text to a canonical ``FXnn`` label.

    Accepts a bare number (``"10"`` -> ``"FX10"``) or an already-prefixed label
    (``"fx10"`` -> ``"FX10"``, ``"FX13-1"`` -> ``"FX13-1"``).  Returns the
    stripped input unchanged if it matches neither shape, and ``""`` for blanks.
    """
    text = (text or "").strip()
    if not text:
        return ""
    # Already prefixed: only normalise the "FX" case, never re-number it, so an
    # existing zero-padded folder (``FX09``) is matched rather than reformatted.
    if _FX_FOLDER_RE.match(text):
        return "FX" + text[2:]
    if text.isdigit():
        return format_fraction_label(text)
    return text


def distinct_session_dates(sessions: list[CBCTSession]) -> list[date]:
    """Sorted, unique acquisition dates across *sessions* (undated skipped)."""
    days = {s.scan_datetime.date() for s in sessions if s.scan_datetime is not None}
    return sorted(days)


def build_date_to_fraction(
    rows: dict[date, str],
) -> tuple[dict[date, str], list[str]]:
    """Build a ``date -> FXn`` map from table rows; blanks skipped, bad numbers reported.

    Returns ``(mapping, errors)``.  Errors are human-readable strings.
    """
    mapping: dict[date, str] = {}
    errors: list[str] = []
    for day, raw in rows.items():
        text = (raw or "").strip()
        if not text:
            continue
        try:
            mapping[day] = format_fraction_label(text)
        except ValueError:
            errors.append(f"{day.isoformat()}: '{raw}' is not a valid fraction number")
    return mapping, errors


def build_fraction_result(
    sessions: list[CBCTSession],
    *,
    source_root: Path,
    mode: str,
    date_to_fraction: dict[date, str] | None = None,
) -> FractionResult:
    """Dispatch to the correct strategy for the chosen *mode*.

    ``mode == "manual"`` uses :class:`ManualDateTable` with *date_to_fraction*;
    any other value (``"trajectory"``) uses :class:`TrajectoryGroundTruth`
    rooted at *source_root*.
    """
    if mode == "manual":
        return ManualDateTable(date_to_fraction or {}).assign(sessions)
    return TrajectoryGroundTruth(source_root).assign(sessions)


def apply_manual_assignments(
    result: FractionResult,
    sessions: list[CBCTSession],
    overrides: dict[str, str],
) -> FractionResult:
    """Apply user reassignments (``{img_dir_name: fraction_label}``) in place.

    Each named session is removed from ``unmatched``/``ambiguous`` and from any
    current assignment, then placed under the chosen label (created if new).
    Unknown session names are ignored. Returns the same *result* for chaining.
    """
    by_name = {s.img_dir.name: s for s in sessions}
    for name, label in overrides.items():
        session = by_name.get(name)
        label = normalize_fraction_label(label)
        if session is None or not label:
            continue
        result.unmatched = [u for u in result.unmatched if u.img_dir.name != name]
        result.ambiguous = [
            (a, c) for (a, c) in result.ambiguous if a.img_dir.name != name
        ]
        for existing in result.assignments.values():
            existing[:] = [x for x in existing if x.img_dir.name != name]
        if label not in result.assignments:
            result.assignments[label] = []
        if label not in result.fraction_labels:
            result.fraction_labels.append(label)
            result.fraction_labels.sort(key=fraction_sort_key)
        result.assignments[label].append(session)
    return result
