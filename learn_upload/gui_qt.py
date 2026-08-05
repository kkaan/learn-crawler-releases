"""PyQt6 desktop GUI for the LEARN data transfer pipeline.

Provides a 6-step wizard wrapping the existing learn_upload modules:
  1. Configuration  -- paths, anon ID, PII strings
  2. Data Preview   -- session discovery and fraction assignment
  3. Anonymise      -- DICOM anonymisation with per-file progress
  4. Folder Sort    -- copy files into LEARN directory structure
  5. PII Verification -- scan output for residual patient data
  6. CBCT Shift Report -- generate markdown report of CBCT shifts

Usage:
    python -m learn_upload.gui_qt
"""

import ctypes
import faulthandler
import json
import logging
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from PyQt6.QtCore import (
    QObject,
    Qt,
    QThread,
    pyqtSignal,
)
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from learn_upload.anonymise_dicom import anonymise_output_folder, inspect_tps_export
from learn_upload.config import DEFAULT_LEARN_OUTPUT, setup_logging
from learn_upload.folder_sort import LearnFolderMapper
from learn_upload.fraction_assignment import (
    apply_manual_assignments,
    build_date_to_fraction,
    build_fraction_result,
    distinct_session_dates,
    has_trajectory_folders,
)
from learn_upload.source_layout import detect_source_layout
from learn_upload.verify_pii import verify_no_pii

logger = logging.getLogger(__name__)

CONFIG_FILE = Path.home() / ".learn_pipeline_config.json"

# ---------------------------------------------------------------------------
# Dark theme stylesheet
# ---------------------------------------------------------------------------

DARK_QSS = """
QMainWindow, QWidget {
    background-color: #0f1117;
    color: #e2e8f0;
    font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 13px;
}
QLabel {
    color: #e2e8f0;
    background: transparent;
}
QLabel[class="heading"] {
    font-size: 18px;
    font-weight: bold;
}
QLabel[class="section"] {
    font-size: 13px;
    font-weight: bold;
    color: #94a3b8;
    text-transform: uppercase;
}
QLabel[class="muted"] {
    color: #94a3b8;
    font-size: 12px;
}
QLineEdit {
    background-color: #1a2030;
    border: 1px solid #2a3040;
    border-radius: 5px;
    color: #e2e8f0;
    padding: 7px 10px;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 12px;
    selection-background-color: #6c63ff;
}
QLineEdit:focus {
    border-color: #6c63ff;
}
QLineEdit:disabled {
    color: #5c6578;
    background-color: #151820;
}
QPushButton {
    background-color: #1a1d27;
    border: 1px solid #2a3040;
    border-radius: 5px;
    color: #94a3b8;
    padding: 8px 16px;
    font-weight: bold;
    font-size: 13px;
}
QPushButton:hover {
    border-color: #6c63ff;
    color: #e2e8f0;
}
QPushButton:pressed {
    background-color: #252838;
}
QPushButton:disabled {
    color: #3a3f50;
    border-color: #1e2230;
}
QPushButton[class="primary"] {
    background-color: #6c63ff;
    color: #ffffff;
    border: none;
}
QPushButton[class="primary"]:hover {
    background-color: #5b53e0;
}
QPushButton[class="primary"]:disabled {
    background-color: #3a3660;
    color: #6c6880;
}
QCheckBox {
    color: #e2e8f0;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #2a3040;
    border-radius: 3px;
    background: #1a2030;
}
QCheckBox::indicator:checked {
    background-color: #6c63ff;
    border-color: #6c63ff;
}
QProgressBar {
    background-color: #1a2030;
    border: none;
    border-radius: 3px;
    height: 8px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background-color: #6c63ff;
    border-radius: 3px;
}
QTableWidget {
    background-color: #1a1d27;
    border: 1px solid #2a3040;
    border-radius: 5px;
    gridline-color: #2a3040;
    color: #e2e8f0;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 12px;
    selection-background-color: rgba(108, 99, 255, 0.2);
}
QTableWidget::item {
    padding: 6px 10px;
}
QHeaderView::section {
    background-color: #11151c;
    color: #94a3b8;
    border: none;
    border-bottom: 1px solid #2a3040;
    border-right: 1px solid #2a3040;
    padding: 8px 10px;
    font-weight: bold;
    font-size: 11px;
    text-transform: uppercase;
}
QTextEdit {
    background-color: #050810;
    border: 1px solid #2a3040;
    border-radius: 5px;
    color: #e2e8f0;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 12px;
    padding: 8px;
    selection-background-color: rgba(108, 99, 255, 0.3);
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #2a3040;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #3a4050;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
}
QScrollBar::handle:horizontal {
    background: #2a3040;
    border-radius: 4px;
    min-width: 30px;
}
QFrame[class="sidebar"] {
    background-color: #11151c;
    border-right: 1px solid #2a3040;
}
QFrame[class="card"] {
    background-color: #1a1d27;
    border: 1px solid #2a3040;
    border-radius: 6px;
}
QFrame[class="separator"] {
    background-color: #2a3040;
    max-height: 1px;
}
"""


# ---------------------------------------------------------------------------
# QThread workers
# ---------------------------------------------------------------------------

class DiscoveryWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, mapper: LearnFolderMapper, tps_path: Path | None = None):
        super().__init__()
        self.mapper = mapper
        self.tps_path = tps_path

    def run(self):
        try:
            self.progress.emit("Discovering sessions...")
            sessions = self.mapper.discover_sessions(enrich=True)
            tps_report = inspect_tps_export(self.tps_path)

            serialized = []
            for s in sessions:
                d = asdict(s)
                for key, val in d.items():
                    if isinstance(val, Path):
                        d[key] = str(val)
                    elif isinstance(val, datetime):
                        d[key] = val.isoformat()
                serialized.append(d)

            # Fraction assignment: detect PRIME (trajectory folders present) and
            # build a serializable preview.  Live session objects can't cross the
            # Qt signal, so the real result is rebuilt in FolderSortWorker.
            source_root = self.mapper.patient_dir
            prime = has_trajectory_folders(source_root)
            fraction_preview = self._fraction_preview(source_root, sessions, prime)
            session_dates = [d.isoformat() for d in distinct_session_dates(sessions)]

            self.finished.emit({
                "ok": True,
                "session_count": len(sessions),
                "sessions": serialized,
                "tps_report": tps_report,
                "prime_mode": prime,
                "fraction_preview": fraction_preview,
                "session_dates": session_dates,
            })
        except Exception as exc:
            logger.exception("Discovery failed")
            self.error.emit(str(exc))

    @staticmethod
    def _fraction_preview(source_root: Path, sessions: list, prime: bool) -> dict:
        """Serializable summary of the trajectory-based fraction assignment."""
        if not prime:
            return {"labels": [], "counts": {}, "unmatched": [], "ambiguous": [], "notes": []}
        result = build_fraction_result(sessions, source_root=source_root, mode="trajectory")

        def info(s) -> dict:
            return {
                "name": s.img_dir.name,
                "type": s.session_type,
                "date": s.scan_datetime.date().isoformat() if s.scan_datetime else "",
            }

        return {
            "labels": result.fraction_labels,
            "counts": {lbl: len(v) for lbl, v in result.assignments.items()},
            "unmatched": [info(s) for s in result.unmatched],
            "ambiguous": [{**info(s), "candidates": c} for s, c in result.ambiguous],
            "notes": list(result.notes),
        }


class AnonymiseWorker(QThread):
    progress = pyqtSignal(int, int, str)  # current, total, filename
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, config: dict):
        super().__init__()
        self.config = config

    def run(self):
        cfg = self.config
        try:
            output_dir = Path(cfg["output_path"])
            site_name = cfg["site_name"].strip()
            anon_id = cfg["anon_id"].strip()
            patient_dir = Path(cfg["source_path"])
            tps_path = cfg.get("tps_path", "").strip()

            result = anonymise_output_folder(
                output_dir=output_dir,
                anon_id=anon_id,
                site_name=site_name,
                patient_dir=patient_dir,
                tps_path=Path(tps_path) if tps_path else None,
                progress_callback=lambda cur, tot, name: self.progress.emit(cur, tot, name),
            )
            self.finished.emit(result)
        except Exception as exc:
            logger.exception("Anonymisation failed")
            self.error.emit(str(exc))


class FolderSortWorker(QThread):
    progress = pyqtSignal(int, int, str)  # current, total, description
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, mapper: LearnFolderMapper, config: dict):
        super().__init__()
        self.mapper = mapper
        self.config = config

    def run(self):
        cfg = self.config
        try:
            centroid_path = cfg.get("centroid_path", "")
            trajectory_dir = cfg.get("trajectory_dir", "")
            calibrations_dir = cfg.get("calibrations_dir", "")
            dry_run = cfg.get("dry_run", False)

            # Rebuild the ground-truth fraction result from live session objects
            # (they can't cross the discovery signal), using the mode/date-map
            # the user chose in Data Preview.
            sessions = self.mapper.discover_sessions(enrich=True)
            mode = cfg.get("fraction_mode", "trajectory")
            date_map = {
                date.fromisoformat(k): v
                for k, v in (cfg.get("date_to_fraction") or {}).items()
            }
            fraction_result = build_fraction_result(
                sessions,
                source_root=self.mapper.patient_dir,
                mode=mode,
                date_to_fraction=date_map,
            )
            overrides = cfg.get("manual_assignments") or {}
            if overrides:
                apply_manual_assignments(fraction_result, sessions, overrides)

            summary = self.mapper.execute(
                fraction_result=fraction_result,
                centroid_path=Path(centroid_path) if centroid_path else None,
                trajectory_base_dir=Path(trajectory_dir) if trajectory_dir else None,
                calibrations_dir=Path(calibrations_dir) if calibrations_dir else None,
                dry_run=dry_run,
                progress_callback=lambda cur, tot, msg: self.progress.emit(cur, tot, msg),
            )
            self.finished.emit(summary)
        except Exception as exc:
            logger.exception("Folder sort failed")
            self.error.emit(str(exc))


class PiiCheckWorker(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, config: dict):
        super().__init__()
        self.config = config

    def run(self):
        cfg = self.config
        try:
            pii_strings = [s.strip() for s in cfg.get("pii_strings", []) if s.strip()]

            # Auto-detect original MRN from source directory name
            source_path = cfg.get("source_path", "")
            if source_path:
                dir_name = Path(source_path).name
                if dir_name.lower().startswith("patient_"):
                    mrn = dir_name[len("patient_"):]
                    if mrn and mrn not in pii_strings:
                        pii_strings.append(mrn)
                        logger.info("Auto-detected MRN from source path")

            if not pii_strings:
                self.finished.emit({
                    "passed": True,
                    "skipped": True,
                    "files_scanned": 0,
                    "findings": [],
                })
                return

            output_base = Path(cfg["output_path"])
            site_name = cfg["site_name"].strip()
            scan_dir = output_base / site_name

            if not scan_dir.is_dir():
                scan_dir = output_base

            findings = verify_no_pii(scan_dir, pii_strings)

            serialized = []
            for f in findings:
                serialized.append({
                    "file": str(f["file"]),
                    "location": f["location"],
                    "matched": f["matched"],
                })

            self.finished.emit({
                "passed": len(findings) == 0,
                "files_scanned": len(list(scan_dir.rglob("*"))),
                "findings": serialized,
            })
        except Exception as exc:
            logger.exception("PII verification failed")
            self.error.emit(str(exc))


class ReportWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, patient_images_path: str, redcap_id: str = ""):
        super().__init__()
        self.patient_images_path = patient_images_path
        self.redcap_id = redcap_id

    def run(self):
        try:
            # Import from cbct-shifts directory
            cbct_shifts_dir = Path(__file__).resolve().parent.parent / "cbct-shifts"
            if str(cbct_shifts_dir) not in sys.path:
                sys.path.insert(0, str(cbct_shifts_dir))
            from report_patient_details import generate_report

            report = generate_report(Path(self.patient_images_path), redcap_id=self.redcap_id)
            if report is None:
                self.error.emit("No RPS files found -- cannot generate report.")
            else:
                self.finished.emit(report)
        except Exception as exc:
            logger.exception("Report generation failed")
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------
# Logging handler that forwards to a QTextEdit widget
# ---------------------------------------------------------------------------

class _LogSignalBridge(QObject):
    """Thread-safe bridge: emits a signal so QTextEdit.append runs on the main thread."""
    log_message = pyqtSignal(str)


class QtLogHandler(logging.Handler):
    """Routes log records to a QTextEdit terminal widget (thread-safe via signal)."""

    def __init__(self, text_edit: QTextEdit):
        super().__init__()
        self._bridge = _LogSignalBridge()
        self._bridge.log_message.connect(text_edit.append)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            level = record.levelname.lower()
            if level == "error":
                color = "#ef4444"
            elif level == "warning":
                color = "#f59e0b"
            else:
                color = "#94a3b8"
            html = f'<span style="color:{color}">{_esc(msg)}</span>'
            self._bridge.log_message.emit(html)
        except Exception:
            pass


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# Sidebar step indicator
# ---------------------------------------------------------------------------

class StepIndicator(QWidget):
    """A single step label in the left sidebar. Clickable when completed."""

    clicked = pyqtSignal(int)  # emits step index when clicked

    def __init__(self, number: int, label: str, parent=None):
        super().__init__(parent)
        self.number = number
        self.label_text = label
        self._state = "future"  # "future" | "active" | "completed"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(12)

        self.circle = QLabel(str(number))
        self.circle.setFixedSize(28, 28)
        self.circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.circle.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        layout.addWidget(self.circle)

        self.label = QLabel(label)
        self.label.setFont(QFont("Segoe UI", 12))
        layout.addWidget(self.label)
        layout.addStretch()

        self.set_state("future")

    def mousePressEvent(self, event):
        if self._state == "completed":
            self.clicked.emit(self.number - 1)  # 0-indexed step
        super().mousePressEvent(event)

    def set_state(self, state: str):
        self._state = state
        if state == "active":
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.setStyleSheet(
                "background: rgba(108, 99, 255, 0.08); "
                "border-left: 3px solid #6c63ff;"
            )
            self.circle.setStyleSheet(
                "background-color: #6c63ff; color: #ffffff; "
                "border-radius: 14px; font-weight: bold;"
            )
            self.label.setStyleSheet("color: #e2e8f0; font-weight: bold;")
        elif state == "completed":
            self.setStyleSheet("background: transparent; border-left: 3px solid transparent;")
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.circle.setStyleSheet(
                "background-color: #22c55e; color: #ffffff; "
                "border-radius: 14px; font-weight: bold;"
            )
            self.circle.setText("\u2713")
            self.label.setStyleSheet("color: #94a3b8;")
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.setStyleSheet("background: transparent; border-left: 3px solid transparent;")
            self.circle.setStyleSheet(
                "background-color: transparent; color: #5c6578; "
                "border: 2px solid #5c6578; border-radius: 14px;"
            )
            self.circle.setText(str(self.number))
            self.label.setStyleSheet("color: #5c6578;")


# ---------------------------------------------------------------------------
# Step pages
# ---------------------------------------------------------------------------

class ConfigPage(QWidget):
    """Step 1: Configuration form."""

    def __init__(self, parent=None):
        super().__init__(parent)
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        page_layout.addWidget(scroll)

        scroll_content = QWidget()
        outer_layout = QVBoxLayout(scroll_content)
        outer_layout.setContentsMargins(24, 24, 24, 24)
        outer_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        scroll.setWidget(scroll_content)

        inner = QWidget()
        inner.setMaximumWidth(800)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        outer_layout.addWidget(inner)

        # -- Patient Identity card --
        id_card = self._make_card("Patient Identity")
        id_form = QFormLayout()
        id_form.setSpacing(10)

        self.anon_id = QLineEdit("PAT01")
        self.anon_id.setPlaceholderText("PAT01")
        id_form.addRow("Anonymised ID:", self.anon_id)

        self.redcap_id = QLineEdit()
        self.redcap_id.setPlaceholderText("e.g. LEARN_001")
        id_form.addRow("REDCap ID:", self.redcap_id)

        self.site_name = QLineEdit()
        self.site_name.setPlaceholderText("e.g. Prostate")
        id_form.addRow("Site Name:", self.site_name)

        id_card.layout().addLayout(id_form)
        layout.addWidget(id_card)

        # -- Data Paths card --
        paths_card = self._make_card("Data Paths")
        paths_form = QFormLayout()
        paths_form.setSpacing(10)

        self.source_path = self._path_row(paths_form, "Source Path (XVI patient root):", folder=True)
        # Auto-detect the rest of the layout when the Source Path is chosen.
        self._last_detected_source: str | None = None
        self.source_path.editingFinished.connect(self._autodetect_layout)
        self.tps_path = self._path_row(paths_form, "TPS Export Path:", folder=True)
        self.output_path = self._path_row(paths_form, "Output Path:", folder=True)
        self.output_path.setText(str(DEFAULT_LEARN_OUTPUT))
        self.staging_path = self._path_row(paths_form, "Staging Path:", folder=True)
        self.staging_path.setPlaceholderText("(auto: output/_staging)")
        self.images_subdir = QLineEdit("XVI Export")
        self.images_subdir.setPlaceholderText("IMAGES")
        paths_form.addRow("Images Subdirectory:", self.images_subdir)
        self.centroid_path = self._path_row(paths_form, "Centroid File:", folder=False)
        self.trajectory_dir = self._path_row(paths_form, "Trajectory Logs Dir:", folder=True)
        self.calibrations_dir = self._path_row(paths_form, "Calibrations Dir:", folder=True)

        paths_card.layout().addLayout(paths_form)
        layout.addWidget(paths_card)

        # -- PII Strings card --
        pii_card = self._make_card("PII Search Strings")
        pii_hint = QLabel("Comma-separated patient identifiers to scan for after anonymisation.")
        pii_hint.setProperty("class", "muted")
        pii_hint.setStyleSheet("color: #94a3b8; font-size: 12px; background: transparent;")
        pii_card.layout().addWidget(pii_hint)
        self.pii_strings = QLineEdit()
        self.pii_strings.setPlaceholderText("e.g. Smith, John, 12345678")
        pii_card.layout().addWidget(self.pii_strings)
        layout.addWidget(pii_card)

        # -- Options card --
        opt_card = self._make_card("Options")
        self.dry_run = QCheckBox("Dry run (preview only, no files copied)")
        opt_card.layout().addWidget(self.dry_run)
        layout.addWidget(opt_card)

        layout.addStretch()

    def _make_card(self, title: str) -> QFrame:
        card = QFrame()
        card.setProperty("class", "card")
        card.setStyleSheet(
            "QFrame[class='card'] { background-color: #1a1d27; "
            "border: 1px solid #2a3040; border-radius: 6px; padding: 16px; }"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(12)
        heading = QLabel(title)
        heading.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: #94a3b8; "
            "text-transform: uppercase; letter-spacing: 0.5px; background: transparent;"
        )
        card_layout.addWidget(heading)
        return card

    def _path_row(self, form: QFormLayout, label: str, folder: bool) -> QLineEdit:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        line_edit = QLineEdit()
        line_edit.setPlaceholderText("(optional)" if "optional" in label.lower() or "TPS" in label or "Centroid" in label or "Trajectory" in label else "")
        row_layout.addWidget(line_edit)
        btn = QPushButton("Browse")
        btn.setFixedWidth(80)
        if folder:
            btn.clicked.connect(lambda: self._browse_folder(line_edit))
        else:
            btn.clicked.connect(lambda: self._browse_file(line_edit))
        row_layout.addWidget(btn)
        form.addRow(label, row)
        return line_edit

    def _browse_folder(self, target: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "Select Folder", target.text())
        if path:
            target.setText(path)
            target.editingFinished.emit()  # trigger auto-detect for the Source Path

    def _autodetect_layout(self, *, fill_empty_only: bool = False):
        """Pre-fill the layout fields from the Source Path (user can still edit).

        ``fill_empty_only`` leaves already-populated fields untouched (used on
        startup so saved/edited values are never clobbered); a manual Source Path
        change overwrites the detected fields.
        """
        source = self.source_path.text().strip()
        if not source or source == self._last_detected_source:
            return
        if not Path(source).is_dir():
            logger.info("Auto-detect skipped: not a directory: %s", source)
            return
        self._last_detected_source = source
        try:
            layout = detect_source_layout(Path(source))
        except Exception:
            logger.warning("Source layout auto-detection failed", exc_info=True)
            return
        logger.info("Auto-detected source layout: %s", layout)
        field_for = {
            "images_subdir": self.images_subdir,
            "tps_path": self.tps_path,
            "trajectory_dir": self.trajectory_dir,
            "centroid_path": self.centroid_path,
        }
        for key, widget in field_for.items():
            value = layout.get(key)
            if value and not (fill_empty_only and widget.text().strip()):
                widget.setText(value)

    def _browse_file(self, target: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(self, "Select File", target.text())
        if path:
            target.setText(path)

    def get_config(self) -> dict:
        pii = [s.strip() for s in self.pii_strings.text().split(",") if s.strip()]
        return {
            "anon_id": self.anon_id.text().strip(),
            "redcap_id": self.redcap_id.text().strip(),
            "site_name": self.site_name.text().strip(),
            "source_path": self.source_path.text().strip(),
            "tps_path": self.tps_path.text().strip(),
            "output_path": self.output_path.text().strip(),
            "staging_path": self.staging_path.text().strip(),
            "images_subdir": self.images_subdir.text().strip() or "IMAGES",
            "centroid_path": self.centroid_path.text().strip(),
            "trajectory_dir": self.trajectory_dir.text().strip(),
            "calibrations_dir": self.calibrations_dir.text().strip(),
            "pii_strings": pii,
            "dry_run": self.dry_run.isChecked(),
        }

    def validate(self) -> str | None:
        cfg = self.get_config()
        if not cfg["anon_id"]:
            return "Anonymised ID is required."
        if not cfg["anon_id"].startswith("PAT") or not cfg["anon_id"][3:].isdigit():
            return "Anon ID must match PATxx format (e.g. PAT01)."
        if not cfg["site_name"]:
            return "Site Name is required."
        if not cfg["source_path"]:
            return "Source Path is required."
        if not cfg["output_path"]:
            return "Output Path is required."
        return None

    def set_config(self, cfg: dict) -> None:
        """Pre-populate form fields from a config dict."""
        self.anon_id.setText(cfg.get("anon_id", ""))
        self.redcap_id.setText(cfg.get("redcap_id", ""))
        self.site_name.setText(cfg.get("site_name", ""))
        self.source_path.setText(cfg.get("source_path", ""))
        self.tps_path.setText(cfg.get("tps_path", ""))
        self.output_path.setText(cfg.get("output_path", ""))
        self.staging_path.setText(cfg.get("staging_path", ""))
        self.images_subdir.setText(cfg.get("images_subdir", "XVI Export"))
        self.centroid_path.setText(cfg.get("centroid_path", ""))
        self.trajectory_dir.setText(cfg.get("trajectory_dir", ""))
        self.calibrations_dir.setText(cfg.get("calibrations_dir", ""))
        pii = cfg.get("pii_strings", [])
        if isinstance(pii, list):
            self.pii_strings.setText(", ".join(pii))
        else:
            self.pii_strings.setText(str(pii))
        self.dry_run.setChecked(bool(cfg.get("dry_run", False)))


class PreviewPage(QWidget):
    """Step 2: Data Preview -- shows discovered sessions in a table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Stats row
        self.stats_layout = QHBoxLayout()
        self.stats_layout.setSpacing(12)
        layout.addLayout(self.stats_layout)

        self.warning_banner = QLabel()
        self.warning_banner.setWordWrap(True)
        self.warning_banner.setStyleSheet(
            "background: rgba(245, 158, 11, 0.12); border: 1px solid #f59e0b; "
            "border-radius: 6px; padding: 10px 12px; color: #fbbf24; "
            "font-family: 'Cascadia Code', monospace; font-size: 12px;"
        )
        self.warning_banner.hide()
        layout.addWidget(self.warning_banner)

        # -- Fraction assignment controls --
        self.fraction_frame = QFrame()
        fl = QVBoxLayout(self.fraction_frame)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(8)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Fraction source:"))
        self.radio_trajectory = QRadioButton("Trajectory folders (ground truth)")
        self.radio_manual = QRadioButton("Manual date → fraction")
        self.fraction_mode_group = QButtonGroup(self)
        self.fraction_mode_group.addButton(self.radio_trajectory, 0)
        self.fraction_mode_group.addButton(self.radio_manual, 1)
        mode_row.addWidget(self.radio_trajectory)
        mode_row.addWidget(self.radio_manual)
        mode_row.addStretch()
        fl.addLayout(mode_row)

        self.fraction_warning = QLabel(
            "Fraction assignment uses your trajectory folder names as ground truth "
            "— verify each FXnn folder is named with the correct fraction number, "
            "as CBCT and KIM-KV images will be sorted into them."
        )
        self.fraction_warning.setWordWrap(True)
        self.fraction_warning.setStyleSheet("color: #f59e0b; font-size: 12px;")
        fl.addWidget(self.fraction_warning)

        self.fraction_hint = QLabel(
            "Enter the fraction number for each date. Look these up in the Mosaiq "
            "patient schedule / image browser."
        )
        self.fraction_hint.setWordWrap(True)
        self.fraction_hint.setStyleSheet("color: #94a3b8; font-size: 12px;")
        fl.addWidget(self.fraction_hint)

        self.fraction_table = QTableWidget()
        self.fraction_table.setColumnCount(2)
        self.fraction_table.setHorizontalHeaderLabels(["Date", "Fraction #"])
        self.fraction_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.fraction_table.verticalHeader().setVisible(False)
        self.fraction_table.setMaximumHeight(180)
        fl.addWidget(self.fraction_table)

        self.fraction_attention = QLabel()
        self.fraction_attention.setWordWrap(True)
        self.fraction_attention.setStyleSheet("color: #fbbf24; font-size: 12px;")
        self.fraction_attention.hide()
        fl.addWidget(self.fraction_attention)

        # Manual reassignment of unmatched/ambiguous sessions (PRIME mode).
        self.reassign_label = QLabel("Reassign unplaced sessions (optional):")
        self.reassign_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.reassign_label.hide()
        fl.addWidget(self.reassign_label)

        self.reassign_table = QTableWidget()
        self.reassign_table.setColumnCount(4)
        self.reassign_table.setHorizontalHeaderLabels(
            ["Session", "Type", "Date", "Assign to (e.g. FX10)"]
        )
        self.reassign_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.reassign_table.verticalHeader().setVisible(False)
        self.reassign_table.setMaximumHeight(160)
        self.reassign_table.hide()
        fl.addWidget(self.reassign_table)

        self.fraction_frame.hide()
        layout.addWidget(self.fraction_frame)

        self.radio_trajectory.toggled.connect(self._on_fraction_mode_changed)
        self.fraction_table.itemChanged.connect(lambda _: self._refresh_attention())

        self._fraction_preview: dict = {}
        self._session_dates: list[str] = []

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Type", "Directory", "Datetime",
            "Treatment", "kV", "mA", "RPS",
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        # Status label (shown during loading)
        self.status = QLabel("Discovering sessions...")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet("color: #94a3b8; font-size: 14px; padding: 40px;")
        layout.addWidget(self.status)

    def set_loading(self, loading: bool):
        self.table.setVisible(not loading)
        self.status.setVisible(loading)
        if loading:
            self.status.setText("Discovering sessions...")

    def populate(self, data: dict):
        self.set_loading(False)

        # Clear old stat cards
        while self.stats_layout.count():
            item = self.stats_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.stats_layout.addWidget(self._stat_card(str(data["session_count"]), "Sessions"))
        self._populate_tps_preview(data.get("tps_report", {}))
        self._populate_fraction_ui(data)

        # Fill table
        sessions = data.get("sessions", [])
        self.table.setRowCount(len(sessions))
        for row, s in enumerate(sessions):
            self.table.setItem(row, 0, QTableWidgetItem(s.get("session_type", "")))
            img_dir = s.get("img_dir", "")
            dir_name = Path(img_dir).name if img_dir else ""
            self.table.setItem(row, 1, QTableWidgetItem(dir_name))
            dt = s.get("scan_datetime")
            dt_str = str(dt).replace("T", " ")[:19] if dt else "-"
            self.table.setItem(row, 2, QTableWidgetItem(dt_str))
            self.table.setItem(row, 3, QTableWidgetItem(s.get("treatment_id") or "-"))
            kv = s.get("tube_kv")
            self.table.setItem(row, 4, QTableWidgetItem(str(kv) if kv is not None else "-"))
            ma = s.get("tube_ma")
            self.table.setItem(row, 5, QTableWidgetItem(str(ma) if ma is not None else "-"))
            self.table.setItem(row, 6, QTableWidgetItem("Yes" if s.get("has_rps") else "-"))

    # -- Fraction assignment UI --

    def _populate_fraction_ui(self, data: dict):
        self._fraction_preview = data.get("fraction_preview", {}) or {}
        self._session_dates = data.get("session_dates", []) or []
        prime = bool(data.get("prime_mode", False))

        self.fraction_frame.show()
        self._populate_fraction_dates(self._session_dates)
        self._populate_reassign_table(self._fraction_preview)

        self.radio_trajectory.blockSignals(True)
        self.radio_manual.blockSignals(True)
        self.radio_trajectory.setChecked(prime)
        self.radio_manual.setChecked(not prime)
        self.radio_trajectory.blockSignals(False)
        self.radio_manual.blockSignals(False)
        self._on_fraction_mode_changed()

    def _populate_reassign_table(self, preview: dict):
        """Fill the reassignment table from unmatched + ambiguous sessions."""
        unmatched = preview.get("unmatched", [])
        ambiguous = preview.get("ambiguous", [])
        rows = [(s, "") for s in unmatched] + [
            # pre-fill the first candidate as a suggestion for ambiguous rows
            (s, (s.get("candidates") or [""])[0]) for s in ambiguous
        ]
        self.reassign_table.blockSignals(True)
        self.reassign_table.setRowCount(len(rows))
        for r, (s, suggestion) in enumerate(rows):
            for col, key in enumerate(("name", "type", "date")):
                item = QTableWidgetItem(s.get(key, ""))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.reassign_table.setItem(r, col, item)
            self.reassign_table.setItem(r, 3, QTableWidgetItem(suggestion))
        self.reassign_table.blockSignals(False)

    def _populate_fraction_dates(self, dates: list[str]):
        self.fraction_table.blockSignals(True)
        self.fraction_table.setRowCount(len(dates))
        for row, iso in enumerate(dates):
            date_item = QTableWidgetItem(iso)
            date_item.setFlags(date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.fraction_table.setItem(row, 0, date_item)
            self.fraction_table.setItem(row, 1, QTableWidgetItem(""))
        self.fraction_table.blockSignals(False)

    def _on_fraction_mode_changed(self, *_):
        trajectory = self.radio_trajectory.isChecked()
        self.fraction_warning.setVisible(trajectory)
        self.fraction_hint.setVisible(not trajectory)
        self.fraction_table.setVisible(not trajectory)
        # The reassignment table only applies to trajectory (PRIME) mode and
        # only when there is something to reassign.
        show_reassign = trajectory and self.reassign_table.rowCount() > 0
        self.reassign_label.setVisible(show_reassign)
        self.reassign_table.setVisible(show_reassign)
        self._refresh_attention()

    def _reassign_rows(self) -> dict:
        """Read the reassignment table into ``{session_name: raw_fraction_text}``."""
        overrides: dict = {}
        for r in range(self.reassign_table.rowCount()):
            name_item = self.reassign_table.item(r, 0)
            label_item = self.reassign_table.item(r, 3)
            if name_item is None or label_item is None:
                continue
            label = label_item.text().strip()
            if label:
                overrides[name_item.text().strip()] = label
        return overrides

    def _date_rows(self) -> dict:
        """Read the date table into ``{date: raw_fraction_text}``."""
        rows: dict = {}
        for r in range(self.fraction_table.rowCount()):
            d_item = self.fraction_table.item(r, 0)
            f_item = self.fraction_table.item(r, 1)
            if d_item is None:
                continue
            try:
                day = date.fromisoformat(d_item.text().strip())
            except ValueError:
                continue
            rows[day] = f_item.text().strip() if f_item else ""
        return rows

    def _refresh_attention(self):
        if self.radio_trajectory.isChecked():
            prev = self._fraction_preview
            labels = prev.get("labels", [])
            unmatched = prev.get("unmatched", [])
            ambiguous = prev.get("ambiguous", [])
            bits = []
            if unmatched:
                names = ", ".join(s["name"] for s in unmatched)
                bits.append(f"{len(unmatched)} unmatched: {names}")
            if ambiguous:
                names = ", ".join(s["name"] for s in ambiguous)
                bits.append(f"{len(ambiguous)} ambiguous: {names}")
            bits.extend(prev.get("notes", []))
            summary = "Fractions: " + (", ".join(labels) if labels else "none detected")
            text = summary + ("   •   " + "   •   ".join(bits) if bits else "")
        else:
            rows = self._date_rows()
            mapping, errors = build_date_to_fraction(rows)
            blanks = [d.isoformat() for d, raw in rows.items() if not raw]
            bits = []
            if blanks:
                bits.append(f"{len(blanks)} date(s) without a fraction number")
            bits.extend(errors)
            text = (
                "Needs attention: " + "   •   ".join(bits)
                if bits
                else f"{len(mapping)} date(s) assigned."
            )
        self.fraction_attention.setText(text)
        self.fraction_attention.show()

    def get_fraction_config(self) -> dict:
        """Return the chosen mode, date map, and any manual reassignments."""
        if self.radio_trajectory.isChecked():
            return {
                "fraction_mode": "trajectory",
                "date_to_fraction": {},
                "manual_assignments": self._reassign_rows(),
            }
        mapping, _errors = build_date_to_fraction(self._date_rows())
        return {
            "fraction_mode": "manual",
            "date_to_fraction": {d.isoformat(): lbl for d, lbl in mapping.items()},
            "manual_assignments": {},
        }

    def _populate_tps_preview(self, tps_report: dict):
        self.warning_banner.hide()
        self.warning_banner.setText("")

        if not tps_report.get("provided"):
            return

        categories = tps_report.get("categories", {})
        labels = {
            "ct": "TPS CT",
            "plan": "TPS Plan",
            "structures": "TPS Structures",
            "dose": "TPS Dose",
        }
        for key in ("ct", "plan", "structures", "dose"):
            count = categories.get(key, {}).get("count", 0)
            color = "#f59e0b" if count == 0 else "#22c55e"
            self.stats_layout.addWidget(self._stat_card(str(count), labels[key], color))

        warnings = tps_report.get("warnings", [])
        if warnings:
            self.warning_banner.setText(
                "TPS export warning: " + " · ".join(warnings)
                + ". You can continue, but missing categories will not be imported."
            )
            self.warning_banner.show()

    def _stat_card(self, value: str, label: str, color: str = "#6c63ff") -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            "background-color: #1a1d27; border: 1px solid #2a3040; "
            "border-radius: 6px; padding: 12px;"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(4)
        val_label = QLabel(value)
        val_label.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {color}; "
            f"font-family: 'Cascadia Code', 'Consolas', monospace; background: transparent;"
        )
        card_layout.addWidget(val_label)
        name_label = QLabel(label)
        name_label.setStyleSheet(
            "font-size: 11px; color: #94a3b8; text-transform: uppercase; "
            "letter-spacing: 0.5px; background: transparent;"
        )
        card_layout.addWidget(name_label)
        return card


class ProgressPage(QWidget):
    """Reusable step page with progress bar, status label, and log terminal."""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Error banner (hidden by default)
        self.error_banner = QLabel()
        self.error_banner.setStyleSheet(
            "background: rgba(239, 68, 68, 0.1); border: 1px solid #ef4444; "
            "border-radius: 6px; padding: 12px; color: #ef4444; "
            "font-family: 'Cascadia Code', monospace; font-size: 13px;"
        )
        self.error_banner.setWordWrap(True)
        self.error_banner.hide()
        layout.addWidget(self.error_banner)

        # Stats row
        self.stats_layout = QHBoxLayout()
        self.stats_layout.setSpacing(12)
        layout.addLayout(self.stats_layout)

        # Progress section
        self.progress_label = QLabel("Preparing...")
        self.progress_label.setStyleSheet("color: #94a3b8; font-size: 12px; background: transparent;")
        layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Log terminal
        terminal_heading = QLabel("Log Output")
        terminal_heading.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: #94a3b8; "
            "text-transform: uppercase; letter-spacing: 0.5px; background: transparent;"
        )
        layout.addWidget(terminal_heading)

        self.terminal = QTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.setMinimumHeight(180)
        layout.addWidget(self.terminal)

        layout.addStretch()

    def reset(self):
        self.error_banner.hide()
        self.progress_label.setText("Preparing...")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.terminal.clear()
        self._clear_stats()

    def set_indeterminate(self, text: str = "Running..."):
        self.progress_bar.setRange(0, 0)  # indeterminate mode
        self.progress_label.setText(text)

    def set_progress(self, current: int, total: int, text: str = ""):
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        pct = round(current / total * 100) if total > 0 else 0
        self.progress_label.setText(f"{text}  ({pct}%)" if text else f"{pct}%")

    def set_complete(self, text: str = "Complete"):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_label.setText(text)

    def show_error(self, message: str):
        self.error_banner.setText(message)
        self.error_banner.show()

    def add_stat(self, value: str, label: str, color: str = "#6c63ff"):
        card = QFrame()
        card.setStyleSheet(
            "background-color: #1a1d27; border: 1px solid #2a3040; "
            "border-radius: 6px; padding: 12px;"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(4)
        vl = QLabel(value)
        vl.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {color}; "
            f"font-family: 'Cascadia Code', monospace; background: transparent;"
        )
        cl.addWidget(vl)
        nl = QLabel(label)
        nl.setStyleSheet(
            "font-size: 11px; color: #94a3b8; text-transform: uppercase; "
            "letter-spacing: 0.5px; background: transparent;"
        )
        cl.addWidget(nl)
        self.stats_layout.addWidget(card)

    def _clear_stats(self):
        while self.stats_layout.count():
            item = self.stats_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()


class PiiResultPage(QWidget):
    """Step 5: PII Verification results."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Banner
        self.banner = QLabel()
        self.banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner.setStyleSheet("font-size: 16px; font-weight: bold; padding: 16px;")
        layout.addWidget(self.banner)

        # Stats row
        self.stats_layout = QHBoxLayout()
        self.stats_layout.setSpacing(12)
        layout.addLayout(self.stats_layout)

        # Findings table
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["File", "Location", "Matched"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.hide()
        layout.addWidget(self.table)

        # Status (loading)
        self.status = QLabel("Scanning for PII...")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet("color: #94a3b8; font-size: 14px; padding: 40px;")
        layout.addWidget(self.status)

        layout.addStretch()

    def set_loading(self, loading: bool):
        self.status.setVisible(loading)
        self.banner.setVisible(not loading)
        if loading:
            self.status.setText("Scanning for PII...")
            self.table.hide()

    def populate(self, data: dict):
        self.set_loading(False)

        # Clear old stat cards
        while self.stats_layout.count():
            item = self.stats_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if data.get("skipped"):
            self.banner.setText("SKIPPED -- No PII search strings configured")
            self.banner.setStyleSheet(
                "background: rgba(245, 158, 11, 0.1); border: 1px solid #f59e0b; "
                "border-radius: 6px; padding: 16px; color: #f59e0b; "
                "font-size: 16px; font-weight: bold;"
            )
        elif data.get("passed"):
            self.banner.setText("PASS -- No residual PII detected")
            self.banner.setStyleSheet(
                "background: rgba(34, 197, 94, 0.1); border: 1px solid #22c55e; "
                "border-radius: 6px; padding: 16px; color: #22c55e; "
                "font-size: 16px; font-weight: bold;"
            )
        else:
            count = len(data.get("findings", []))
            self.banner.setText(f"FAIL -- {count} PII finding(s)")
            self.banner.setStyleSheet(
                "background: rgba(239, 68, 68, 0.1); border: 1px solid #ef4444; "
                "border-radius: 6px; padding: 16px; color: #ef4444; "
                "font-size: 16px; font-weight: bold;"
            )

        self.stats_layout.addWidget(
            self._stat_card(str(data.get("files_scanned", 0)), "Files Scanned")
        )
        findings = data.get("findings", [])
        error_color = "#ef4444" if findings else "#6c63ff"
        self.stats_layout.addWidget(
            self._stat_card(str(len(findings)), "Findings", error_color)
        )

        if findings:
            self.table.show()
            self.table.setRowCount(len(findings))
            for i, f in enumerate(findings):
                short_file = "/".join(Path(f["file"]).parts[-3:])
                self.table.setItem(i, 0, QTableWidgetItem(short_file))
                self.table.setItem(i, 1, QTableWidgetItem(f["location"]))
                item = QTableWidgetItem(f["matched"])
                item.setForeground(Qt.GlobalColor.red)
                self.table.setItem(i, 2, item)
        else:
            self.table.hide()

    def _stat_card(self, value: str, label: str, color: str = "#6c63ff") -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            "background-color: #1a1d27; border: 1px solid #2a3040; "
            "border-radius: 6px; padding: 12px;"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(4)
        vl = QLabel(value)
        vl.setStyleSheet(
            f"font-size: 24px; font-weight: bold; color: {color}; "
            f"font-family: 'Cascadia Code', monospace; background: transparent;"
        )
        cl.addWidget(vl)
        nl = QLabel(label)
        nl.setStyleSheet(
            "font-size: 11px; color: #94a3b8; text-transform: uppercase; "
            "letter-spacing: 0.5px; background: transparent;"
        )
        cl.addWidget(nl)
        return card


class ReportPage(QWidget):
    """Step 6: CBCT Shift Report display."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        self.status = QLabel("Generating report...")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet("color: #94a3b8; font-size: 14px; padding: 40px;")
        layout.addWidget(self.status)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setMinimumHeight(400)
        self.text_edit.hide()
        layout.addWidget(self.text_edit)

        layout.addStretch()

    def set_loading(self, loading: bool):
        self.status.setVisible(loading)
        self.text_edit.setVisible(not loading)
        if loading:
            self.status.setText("Generating report...")

    def set_report(self, markdown: str):
        self.set_loading(False)
        self.text_edit.setPlainText(markdown)

    def show_error(self, message: str):
        self.set_loading(False)
        self.text_edit.show()
        self.text_edit.setPlainText(f"Error: {message}")


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class LearnPipelineWindow(QMainWindow):

    STEP_NAMES = [
        "Configuration",
        "Data Preview",
        "Folder Sort",
        "Anonymise",
        "PII Verification",
        "CBCT Shift Report",
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LEARN Pipeline")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 820)

        self._config: dict = {}
        self._mapper: LearnFolderMapper | None = None
        self._current_step = 0
        self._completed_steps: set[int] = set()
        self._active_worker: QThread | None = None
        self._workers: list[QThread] = []  # prevent GC of running workers

        self._build_ui()
        self._load_config()

    def _load_config(self) -> None:
        """Load persisted config from JSON file into the config form."""
        try:
            if CONFIG_FILE.is_file():
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                self._config_page.set_config(data)
                logger.info("Loaded config from %s", CONFIG_FILE)
        except Exception:
            logger.warning("Failed to load config from %s", CONFIG_FILE, exc_info=True)
        # Auto-fill any layout fields the saved config left blank, from the
        # (possibly pre-loaded) Source Path — without clobbering saved values.
        self._config_page._autodetect_layout(fill_empty_only=True)

    def _save_config(self, cfg: dict) -> None:
        """Persist config dict to JSON file."""
        try:
            CONFIG_FILE.write_text(
                json.dumps(cfg, indent=2, default=str), encoding="utf-8",
            )
            logger.info("Saved config to %s", CONFIG_FILE)
        except Exception:
            logger.warning("Failed to save config to %s", CONFIG_FILE, exc_info=True)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # -- Sidebar --
        sidebar = QFrame()
        sidebar.setFixedWidth(260)
        sidebar.setProperty("class", "sidebar")
        sidebar.setStyleSheet(
            "QFrame { background-color: #11151c; border-right: 1px solid #2a3040; }"
        )
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 20, 0, 0)
        sidebar_layout.setSpacing(0)

        title = QLabel("LEARN Pipeline")
        title.setStyleSheet(
            "color: #6c63ff; font-size: 14px; font-weight: bold; "
            "letter-spacing: 1.5px; text-transform: uppercase; "
            "padding: 0 20px 20px 20px; background: transparent;"
        )
        sidebar_layout.addWidget(title)

        self._step_indicators: list[StepIndicator] = []
        for i, name in enumerate(self.STEP_NAMES):
            si = StepIndicator(i + 1, name)
            si.clicked.connect(self._on_step_clicked)
            self._step_indicators.append(si)
            sidebar_layout.addWidget(si)

        sidebar_layout.addStretch()

        version_label = QLabel("learn_upload v0.1.0")
        version_label.setStyleSheet(
            "color: #5c6578; font-size: 11px; padding: 16px 20px; "
            "border-top: 1px solid #2a3040; background: transparent;"
        )
        sidebar_layout.addWidget(version_label)

        main_layout.addWidget(sidebar)

        # -- Right panel --
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setStyleSheet("background: #0f1117; border-bottom: 1px solid #2a3040;")
        header.setFixedHeight(56)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 0, 24, 0)
        self._header_title = QLabel("Configuration")
        self._header_title.setStyleSheet(
            "font-size: 18px; font-weight: bold; color: #e2e8f0; background: transparent;"
        )
        header_layout.addWidget(self._header_title)
        header_layout.addStretch()
        right_layout.addWidget(header)

        # Stacked widget for pages
        self._stack = QStackedWidget()
        right_layout.addWidget(self._stack)

        # Pages
        self._config_page = ConfigPage()
        self._preview_page = PreviewPage()
        self._anon_page = ProgressPage("Anonymise")
        self._sort_page = ProgressPage("Folder Sort")
        self._pii_page = PiiResultPage()
        self._report_page = ReportPage()

        self._stack.addWidget(self._config_page)
        self._stack.addWidget(self._preview_page)
        self._stack.addWidget(self._sort_page)
        self._stack.addWidget(self._anon_page)
        self._stack.addWidget(self._pii_page)
        self._stack.addWidget(self._report_page)

        # Bottom button bar
        btn_bar = QFrame()
        btn_bar.setStyleSheet("background: #0f1117; border-top: 1px solid #2a3040;")
        btn_bar.setFixedHeight(60)
        btn_layout = QHBoxLayout(btn_bar)
        btn_layout.setContentsMargins(24, 0, 24, 0)

        self._btn_back = QPushButton("Back")
        self._btn_back.clicked.connect(self._on_back)
        btn_layout.addWidget(self._btn_back)

        btn_layout.addStretch()

        self._btn_continue = QPushButton("Continue")
        self._btn_continue.setProperty("class", "primary")
        self._btn_continue.clicked.connect(self._on_continue)
        btn_layout.addWidget(self._btn_continue)

        right_layout.addWidget(btn_bar)
        main_layout.addWidget(right_panel)

        # Initial state
        self._go_to_step(0)

        # Attach log handler to the progress page terminals
        self._log_handler_anon = QtLogHandler(self._anon_page.terminal)
        self._log_handler_anon.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(name)s -- %(message)s"))
        self._log_handler_sort = QtLogHandler(self._sort_page.terminal)
        self._log_handler_sort.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(name)s -- %(message)s"))

    # -- Worker management --

    def _start_worker(self, worker: QThread) -> None:
        """Store worker reference to prevent GC, then start it."""
        self._active_worker = worker
        self._workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        worker.start()

    def _cleanup_worker(self, worker: QThread) -> None:
        """Remove finished worker from the keep-alive list."""
        try:
            self._workers.remove(worker)
        except ValueError:
            pass

    # -- Navigation --

    def _go_to_step(self, step: int):
        self._current_step = step
        self._stack.setCurrentIndex(step)
        self._header_title.setText(self.STEP_NAMES[step])

        for i, si in enumerate(self._step_indicators):
            if i == step:
                si.set_state("active")
            elif i in self._completed_steps:
                si.set_state("completed")
            else:
                si.set_state("future")

        # Update button labels and visibility
        self._btn_back.setVisible(step > 0)

        # If this step is already completed, enable Continue to advance
        already_done = step in self._completed_steps

        if step == 0:
            self._btn_continue.setText("Continue to Preview")
            self._btn_continue.setEnabled(True)
        elif step == 1:
            self._btn_continue.setText("Start Folder Sort")
            self._btn_continue.setEnabled(already_done or True)
        elif step == 2:
            self._btn_continue.setText("Start Anonymisation")
            self._btn_continue.setEnabled(already_done)
        elif step == 3:
            self._btn_continue.setText("Run PII Verification")
            self._btn_continue.setEnabled(already_done)
        elif step == 4:
            self._btn_continue.setText("Generate CBCT Report")
            self._btn_continue.setEnabled(already_done)
        elif step == 5:
            self._btn_continue.setText("New Patient")
            self._btn_continue.setEnabled(already_done)

    def _on_step_clicked(self, step: int):
        """Navigate to a completed step for review."""
        if step in self._completed_steps:
            self._go_to_step(step)

    def _on_back(self):
        if self._current_step > 0:
            self._go_to_step(self._current_step - 1)

    def _on_continue(self):
        step = self._current_step
        # If both this step AND the next are already completed, just advance
        # (user is re-visiting a past step).  Otherwise fall through to
        # actually run the next step's worker.
        if step in self._completed_steps and (step + 1) in self._completed_steps and step < 5:
            self._go_to_step(step + 1)
            return
        if step == 0:
            self._submit_config()
        elif step == 1:
            self._start_folder_sort()
        elif step == 2:
            self._start_anonymise()
        elif step == 3:
            self._start_pii_check()
        elif step == 4:
            self._start_report()
        elif step == 5:
            self._reset_for_new_patient()

    # -- Step 1: Config --

    def _submit_config(self):
        error = self._config_page.validate()
        if error:
            QMessageBox.warning(self, "Validation Error", error)
            return

        self._config = self._config_page.get_config()
        self._save_config(self._config)
        self._completed_steps.add(0)
        self._go_to_step(1)
        self._run_discovery()

    # -- Step 2: Discovery --

    def _run_discovery(self):
        self._preview_page.set_loading(True)
        self._btn_continue.setEnabled(False)

        cfg = self._config
        patient_dir = Path(cfg["source_path"])
        images_subdir = cfg.get("images_subdir", "IMAGES").strip() or "IMAGES"

        self._mapper = LearnFolderMapper(
            patient_dir=patient_dir,
            anon_id=cfg["anon_id"],
            site_name=cfg["site_name"],
            output_base=Path(cfg["output_path"]),
            images_subdir=images_subdir,
        )

        tps_path_text = cfg.get("tps_path", "").strip()
        worker = DiscoveryWorker(
            self._mapper,
            tps_path=Path(tps_path_text) if tps_path_text else None,
        )
        worker.finished.connect(self._on_discovery_done)
        worker.error.connect(self._on_discovery_error)
        self._start_worker(worker)

    def _on_discovery_done(self, data: dict):
        self._preview_page.populate(data)
        self._btn_continue.setEnabled(True)
        self._active_worker = None

    def _on_discovery_error(self, message: str):
        self._preview_page.set_loading(False)
        self._preview_page.status.setText(f"Discovery failed: {message}")
        self._preview_page.status.setStyleSheet(
            "color: #ef4444; font-size: 14px; padding: 40px;"
        )
        self._active_worker = None

    # -- Step 3: Anonymise --

    def _start_anonymise(self):
        self._completed_steps.add(2)
        self._go_to_step(3)
        self._anon_page.reset()
        self._anon_page.set_indeterminate("Scanning files...")

        # Attach log handler
        logging.getLogger().addHandler(self._log_handler_anon)

        worker = AnonymiseWorker(self._config)
        worker.progress.connect(self._on_anon_progress)
        worker.finished.connect(self._on_anon_done)
        worker.error.connect(self._on_anon_error)
        self._start_worker(worker)

    def _on_anon_progress(self, current: int, total: int, filename: str):
        self._anon_page.set_progress(current, total, filename)

    def _on_anon_done(self, data: dict):
        logging.getLogger().removeHandler(self._log_handler_anon)

        self._anon_page.set_complete("Anonymisation complete")

        self._anon_page.add_stat(str(data.get("dcm", 0)), "DICOM")
        self._anon_page.add_stat(str(data.get("xml", 0)), "XML")
        self._anon_page.add_stat(str(data.get("ini", 0)), "INI")
        self._anon_page.add_stat(str(data.get("tps_imported", 0)), "TPS Imported")
        errors = data.get("errors", 0)
        self._anon_page.add_stat(
            str(errors), "Errors", "#ef4444" if errors > 0 else "#6c63ff"
        )

        self._completed_steps.add(3)
        self._btn_continue.setEnabled(True)
        self._active_worker = None

    def _on_anon_error(self, message: str):
        logging.getLogger().removeHandler(self._log_handler_anon)
        self._anon_page.show_error(message)
        self._active_worker = None

    # -- Step 4: Folder Sort --

    def _start_folder_sort(self):
        self._completed_steps.add(1)
        self._go_to_step(2)
        self._sort_page.reset()
        self._sort_page.set_indeterminate("Running folder sort...")

        logging.getLogger().addHandler(self._log_handler_sort)

        # Carry the fraction mode + manual date map chosen in Data Preview.
        self._config.update(self._preview_page.get_fraction_config())

        worker = FolderSortWorker(self._mapper, self._config)
        worker.progress.connect(
            lambda cur, tot, msg: self._sort_page.set_progress(cur, tot, msg)
        )
        worker.finished.connect(self._on_sort_done)
        worker.error.connect(self._on_sort_error)
        self._start_worker(worker)

    def _on_sort_done(self, data: dict):
        logging.getLogger().removeHandler(self._log_handler_sort)

        dry = data.get("dry_run", False)
        self._sort_page.set_complete("Dry run complete" if dry else "Folder sort complete")

        self._sort_page.add_stat(str(data.get("sessions", 0)), "Sessions")
        self._sort_page.add_stat(str(data.get("fractions", 0)), "Fractions")
        fc = data.get("files_copied", {})
        self._sort_page.add_stat(str(fc.get("his", 0)), ".his Files")
        self._sort_page.add_stat(str(fc.get("scan", 0)), "SCAN Files")
        self._sort_page.add_stat(str(fc.get("rps", 0)), "RPS Files")
        self._sort_page.add_stat(str(fc.get("ini", 0)), "INI Files")

        self._completed_steps.add(2)
        self._btn_continue.setEnabled(True)
        self._active_worker = None

    def _on_sort_error(self, message: str):
        logging.getLogger().removeHandler(self._log_handler_sort)
        self._sort_page.show_error(message)
        self._active_worker = None

    # -- Step 5: PII Verification --

    def _start_pii_check(self):
        self._completed_steps.add(3)
        self._go_to_step(4)
        self._pii_page.set_loading(True)
        self._btn_continue.setEnabled(False)

        worker = PiiCheckWorker(self._config)
        worker.finished.connect(self._on_pii_done)
        worker.error.connect(self._on_pii_error)
        self._start_worker(worker)

    def _on_pii_done(self, data: dict):
        self._pii_page.populate(data)
        self._completed_steps.add(4)
        self._btn_continue.setEnabled(True)
        self._active_worker = None

    def _on_pii_error(self, message: str):
        self._pii_page.set_loading(False)
        self._pii_page.banner.setText(f"Error: {message}")
        self._pii_page.banner.setStyleSheet(
            "background: rgba(239, 68, 68, 0.1); border: 1px solid #ef4444; "
            "border-radius: 6px; padding: 16px; color: #ef4444; "
            "font-size: 16px; font-weight: bold;"
        )
        self._pii_page.banner.show()
        self._active_worker = None

    # -- Step 6: CBCT Shift Report --

    def _start_report(self):
        self._completed_steps.add(4)
        self._go_to_step(5)
        self._report_page.set_loading(True)
        self._btn_continue.setEnabled(False)

        cfg = self._config
        output_base = Path(cfg["output_path"])
        site_name = cfg["site_name"].strip()
        anon_id = cfg["anon_id"].strip()
        patient_images_path = str(output_base / site_name / "Patient Images" / anon_id)
        redcap_id = cfg.get("redcap_id", "")

        worker = ReportWorker(patient_images_path, redcap_id=redcap_id)
        worker.finished.connect(self._on_report_done)
        worker.error.connect(self._on_report_error)
        self._start_worker(worker)

    def _on_report_done(self, markdown: str):
        self._report_page.set_report(markdown)

        # Save report to Patient Files folder
        cfg = self._config
        output_base = Path(cfg["output_path"])
        site_name = cfg["site_name"].strip()
        anon_id = cfg["anon_id"].strip()
        report_dir = output_base / site_name / "Patient Files" / anon_id
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "cbct_shift_report.md"
        try:
            report_path.write_text(markdown, encoding="utf-8")
            logger.info("Saved CBCT shift report to %s", report_path)
        except Exception:
            logger.warning("Failed to save shift report to %s", report_path, exc_info=True)

        self._completed_steps.add(5)
        self._btn_continue.setText("New Patient")
        self._btn_continue.setEnabled(True)
        self._active_worker = None

    def _on_report_error(self, message: str):
        self._report_page.show_error(message)
        self._completed_steps.add(5)
        self._btn_continue.setText("New Patient")
        self._btn_continue.setEnabled(True)
        self._active_worker = None

    # -- Reset --

    def _reset_for_new_patient(self):
        self._config = {}
        self._mapper = None
        self._completed_steps.clear()
        self._go_to_step(0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _enable_dark_title_bar(hwnd: int) -> None:
    """Use DwmSetWindowAttribute to enable immersive dark mode title bar on Windows 11."""
    try:
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value), ctypes.sizeof(value),
        )
    except Exception:
        pass  # Non-Windows or unsupported version


def main() -> None:
    if sys.stderr is not None:
        faulthandler.enable()
    setup_logging(logging.INFO)

    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_QSS)
    app.setFont(QFont("Segoe UI", 10))

    window = LearnPipelineWindow()
    window.show()

    if sys.platform == "win32":
        hwnd = int(window.winId())
        _enable_dark_title_bar(hwnd)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
