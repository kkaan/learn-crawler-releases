"""Auto-detect the layout of an XVI patient Source Path.

Given only the Source Path, locate the sub-locations the pipeline needs by the
files they contain rather than by hard-coded folder names:

* **images subdirectory** — the folder holding ``img_<UID>/`` acquisition dirs
  (each with a ``_Frames.xml``); returned relative to the source root.
* **trajectory dir** — the folder whose children are ``FXnn/`` fraction folders
  containing KIM ``MarkerLocations*.txt`` logs.
* **TPS export** — a folder (outside the images tree) whose subtree holds DICOM.
* **centroid file** — a ``Centroid*.txt`` file.

All detectors are best-effort and return ``None`` when nothing matches; the GUI
pre-fills the fields and lets the user edit.
"""
from __future__ import annotations

import re
from collections import deque
from pathlib import Path

_FX_FOLDER_RE = re.compile(r"^FX\d+(-\d+)?$", re.IGNORECASE)
_MAX_DEPTH = 4


def _iter_dirs(root: Path, max_depth: int = _MAX_DEPTH):
    """Yield *root* and its subdirectories breadth-first up to *max_depth*."""
    queue: deque[tuple[Path, int]] = deque([(root, 0)])
    while queue:
        d, depth = queue.popleft()
        yield d
        if depth >= max_depth:
            continue
        try:
            children = sorted(c for c in d.iterdir() if c.is_dir())
        except OSError:
            continue
        for child in children:
            queue.append((child, depth + 1))


def _has_dcm(directory: Path) -> bool:
    """True if *directory*'s subtree contains any ``.dcm``/``.DCM`` file."""
    for p in directory.rglob("*"):
        if p.is_file() and p.suffix.lower() == ".dcm":
            return True
    return False


def detect_images_subdir(source_root: Path | str) -> str | None:
    """Return the images subdirectory (relative to *source_root*) or ``None``.

    The images subdirectory is the shallowest folder that directly contains an
    ``img_*`` directory with a ``_Frames.xml``.  Returns ``"."`` when the
    ``img_*`` dirs sit directly in *source_root*.
    """
    source_root = Path(source_root)
    if not source_root.is_dir():
        return None
    for d in _iter_dirs(source_root):
        try:
            children = sorted(d.iterdir())
        except OSError:
            continue
        for child in children:
            if (
                child.is_dir()
                and child.name.startswith("img_")
                and (child / "_Frames.xml").is_file()
            ):
                rel = d.relative_to(source_root)
                return "." if rel == Path() else rel.as_posix()
    return None


def detect_trajectory_dir(source_root: Path | str) -> Path | None:
    """Return the folder whose children are ``FXnn/`` trajectory folders."""
    source_root = Path(source_root)
    if not source_root.is_dir():
        return None
    for d in _iter_dirs(source_root):
        try:
            children = sorted(d.iterdir())
        except OSError:
            continue
        for child in children:
            if (
                child.is_dir()
                and _FX_FOLDER_RE.match(child.name)
                and any(child.glob("MarkerLocations*.txt"))
            ):
                return d
    return None


def detect_tps_export(
    source_root: Path | str, images_subdir: str | None = None
) -> Path | None:
    """Return a DICOM-bearing folder outside the images tree (the TPS export).

    Scans the immediate children of *source_root*, skips the images subdirectory
    and ``FXnn/`` trajectory folders (which contain only non-DICOM logs or RPS
    DICOM noise), and returns the first child whose subtree contains a ``.dcm``.
    """
    source_root = Path(source_root)
    if not source_root.is_dir():
        return None
    images_root = None
    if images_subdir:
        images_root = (source_root / images_subdir).resolve()
    for child in sorted(source_root.iterdir()):
        if not child.is_dir():
            continue
        if images_root is not None and child.resolve() == images_root:
            continue
        if _FX_FOLDER_RE.match(child.name):
            continue
        if _has_dcm(child):
            return child
    return None


def detect_centroid_file(source_root: Path | str) -> Path | None:
    """Return the first ``Centroid*.txt`` file found under *source_root*."""
    source_root = Path(source_root)
    if not source_root.is_dir():
        return None
    for d in _iter_dirs(source_root):
        matches = sorted(d.glob("Centroid*.txt"))
        if matches:
            return matches[0]
    return None


def detect_source_layout(source_root: Path | str) -> dict:
    """Detect all known sub-locations under *source_root*.

    Returns a dict with string values (paths as strings, ``None`` when absent)
    suitable for populating GUI fields:
    ``{"images_subdir", "trajectory_dir", "tps_path", "centroid_path"}``.
    """
    source_root = Path(source_root)
    images_subdir = detect_images_subdir(source_root)
    trajectory_dir = detect_trajectory_dir(source_root)
    tps_path = detect_tps_export(source_root, images_subdir)
    centroid_path = detect_centroid_file(source_root)
    return {
        "images_subdir": images_subdir,
        "trajectory_dir": str(trajectory_dir) if trajectory_dir else None,
        "tps_path": str(tps_path) if tps_path else None,
        "centroid_path": str(centroid_path) if centroid_path else None,
    }
