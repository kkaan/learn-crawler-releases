# LEARN Upload Automation Plan

## Overview

This document describes the planned Python automation for the GC Elekta Patient Upload Process to USYD LEARN. The goal is to replace manual steps (MIM anonymisation, manual folder creation, manual data entry) with Python scripts while retaining user prompts for steps that require clinical judgement.

## Current Manual Bottlenecks

| Step | Current Method | Automation Target |
|------|---------------|-------------------|
| DICOM anonymisation | Export to MIM, right-click anonymise | Python script using `pydicom` |
| Folder structure creation | Manual folder creation + file copying | Python script maps XVI -> LEARN structure |
| Treatment Notes entry | Manual data entry from .ini files and Mosaiq | Auto-populate xlsx from parsed XVI data |
| Shift extraction | Copy from Mosaiq SRO browser | Auto-extract from RPS.dcm via `ElektaRPSExtractor` |
| Process coordination | Follow SOP document manually | Interactive CLI wrapper guides user through stages |

## Package Structure

```
learn_upload/
    __init__.py
    config.py                  # Shared configuration, paths, constants
    utils.py                   # INI parsing, XML parsing utilities
    anonymise_dicom.py         # DICOM anonymisation (replaces MIM)
    folder_sort.py             # XVI export -> LEARN structure mapping
    treatment_notes.py         # Treatment_Notes.xlsx generation
    upload_workflow.py         # Interactive wrapper CLI (main entry point)
```

## Dependencies

| Package | Status | Purpose |
|---------|--------|---------|
| `pydicom` 3.0.1+ | Already installed | DICOM file reading and anonymisation |
| `numpy` | Already installed | Matrix operations for shift extraction |
| `openpyxl` 3.1+ | **New - to install** | Treatment_Notes.xlsx generation |

## Script 1: `anonymise_dicom.py`

### Purpose
Replace the manual MIM-based anonymisation with Python. Only TPS data (CT_SET/, DICOM_PLAN/) needs anonymisation -- projection and CBCT files in elekta_fdt are already anonymised.

### Anonymised ID Format
**PATxx** (e.g., PAT01, PAT02) -- matching the LEARN folder structure convention.

### DICOM Tags to Modify

| Tag | Name | Action |
|-----|------|--------|
| (0010,0010) | PatientName | Replace with PATxx |
| (0010,0020) | PatientID | Replace with PATxx |
| (0010,0030) | PatientBirthDate | Clear |
| (0008,0050) | AccessionNumber | Clear |
| (0008,0080) | InstitutionName | Clear |
| (0008,0081) | InstitutionAddress | Clear |
| (0008,0090) | ReferringPhysicianName | Clear |
| (0008,1048) | PhysiciansOfRecord | Clear |
| (0008,1070) | OperatorsName | Clear |
| (0020,0010) | StudyID | Replace with PATxx |

### Tags to Preserve
- PatientSex, PatientAge, PatientSize, PatientWeight (needed for research)
- StudyDescription (contains treatment info)
- **All DICOM UIDs** (preserves referential integrity between CT, structure set, and plan)

### Class Design

```python
class DicomAnonymiser:
    def __init__(self, patient_dir: Path, anon_id: str, output_dir: Path):
        """
        patient_dir: Path to patient_XXXXXXXX directory
        anon_id: Sequential ID (e.g., "PAT01")
        output_dir: Staging directory for anonymised output
        """

    def anonymise_file(self, dcm_path: Path) -> Path
    def anonymise_ct_set(self) -> list[Path]
    def anonymise_plan(self) -> list[Path]
    def anonymise_all(self) -> dict  # Returns summary
```

### Reuse
- `pydicom` patterns from existing `scripts/extract_elekta_rps_matrices.py`
- Never modifies source files -- writes to staging directory

## Script 2: `folder_sort.py`

### Purpose
Map the flat XVI export structure into the hierarchical LEARN target structure automatically.

### Source -> Target Mapping

| Source (XVI) | Target (LEARN) |
|-------------|----------------|
| `patient_XXXXXXXX/IMAGES/img_[UID]/*.his` | `Patient Images/PATxx/FXn/KIM-KV/` |
| `patient_XXXXXXXX/IMAGES/img_[UID]/Reconstruction/*.SCAN` | `Patient Images/PATxx/FXn/CBCT/CBCTm/Reconstructed CBCT/` |
| `patient_XXXXXXXX/IMAGES/img_[UID]/Reconstruction/*.SCAN.MACHINEORIENTATION` | `Patient Images/PATxx/FXn/CBCT/CBCTm/Reconstructed CBCT/` |
| `patient_XXXXXXXX/IMAGES/img_[UID]/Reconstruction/*.RPS.dcm` | `Patient Images/PATxx/FXn/CBCT/CBCTm/Registration file/` |
| `patient_XXXXXXXX/CT_SET/*.DCM` (anonymised) | `Patient Plans/PATxx/CT/` |
| `patient_XXXXXXXX/DICOM_PLAN/*.DCM` (anonymised) | `Patient Plans/PATxx/Plan/` |

### Target LEARN Folder Structure

```
[SiteName]/
    Patient Files/
        PATxx/
            Treatment_Notes.xlsx
    Patient Images/
        PATxx/
            FX0/
                CBCT/
                    CBCT1/
                        CBCT Projections/
                            CDOG/
                            IPS/
                        Reconstructed CBCT/
                        Registration file/
                    CBCT2/  (if multiple CBCTs same fraction)
                KIM-KV/     (.his projection files go here)
                    IFI/
            FX1/ ... FXn/
    Patient Plans/
        PATxx/
            CT/             (anonymised CT_SET DICOM)
            Plan/           (anonymised DICOM_PLAN)
    Ground Truth/PATxx/
    Patient Measured Motions/
    RPM/
    Trajectory Logs/
```

### Fraction Assignment Logic

1. Parse each `img_*/Reconstruction/*.INI` for ScanUID datetime (e.g., `...2023-03-21165402768`)
2. Sort all sessions chronologically
3. Assign FX0, FX1, FX2... by date order
4. Same-day CBCTs become CBCT1, CBCT2 within same FXn
5. **Filter:** Only include CBCTs with RPS.dcm and non-zero applied shifts (per SOP requirement)

### Session Data Model

```python
@dataclass
class CBCTSession:
    img_dir: Path
    scan_uid: str
    scan_datetime: datetime
    treatment_id: str       # From _Frames.xml <Treatment><ID>
    tube_kv: float          # From INI TubeKV
    tube_ma: float          # From INI TubeMA
    has_rps: bool
    rps_path: Optional[Path]
    couch_shifts: Optional[dict]  # From ElektaRPSExtractor
    ini_path: Path
```

### Class Design

```python
class LearnFolderMapper:
    def __init__(self, patient_dir: Path, anon_id: str, site_name: str,
                 output_base: Path)

    def discover_cbct_sessions(self) -> list[CBCTSession]
    def assign_fractions(self, sessions: list) -> dict[str, list]
    def filter_treated_sessions(self, sessions: list) -> list
    def create_directory_structure(self) -> Path
    def copy_projections(self, session, fx_path: Path, cbct_num: int)
    def copy_reconstructions(self, session, fx_path: Path, cbct_num: int)
    def copy_registration(self, session, fx_path: Path, cbct_num: int)
    def copy_anonymised_plans(self, anon_ct_dir: Path, anon_plan_dir: Path)
    def execute(self, dry_run: bool = False) -> dict
```

### Reuse
- `scripts/elektafdt_crawler.py` -- patient directory traversal and `_Frames.xml` parsing patterns
- `scripts/extract_elekta_rps_matrices.py` -- `ElektaRPSExtractor` for shift extraction from RPS.dcm

## Script 3: `treatment_notes.py`

### Purpose
Auto-generate Treatment_Notes.xlsx pre-filled with data extractable from XVI exports.

### Auto-Filled Fields

| Field | Source |
|-------|--------|
| RedCap ID | PATxx (user input) |
| Image Collected | "CBCTs" (constant) |
| Linac Type | "Elekta VersaHD" (constant) |
| Imager Position (SDD) | "150cm" (constant) |
| Couch Type | "Precise Table" (constant) |
| Coordinate System | "Patient Coordinate System (Beam)" (constant per SOP) |
| kV | From INI `TubeKV` |
| mA | From INI `TubeMA` |
| Per-fraction Date | Parsed from ScanUID datetime |
| Per-fraction Shifts (Sup/Lat/Ant) | From RPS.dcm via ElektaRPSExtractor |
| Per-fraction Rotations (Cor/Sag/Trans) | From RPS.dcm rotation values |

### Manual Fields (prompted by wrapper)

| Field | Notes |
|-------|-------|
| Height/Weight | From Mosaiq assessments only |
| Marker Length and Type | If applicable |
| CDOG version | If applicable |
| mAs confirmation | Verify if TubeMA is mA or mAs |

### Package
`openpyxl` for .xlsx generation with formatting matching the existing Treatment_Notes.xlsx templates in `Docs/Prostate/Patient Files/PATxx/`.

## Script 4: `upload_workflow.py` (Interactive Wrapper)

### Purpose
Guide the user through the complete upload process with an interactive CLI. Automates what can be automated, prompts when manual clinical judgement is needed.

### 8-Stage Workflow

```
STAGE 1: PATIENT SELECTION
  [AUTO]   Scan elekta_fdt base directory for patient_* folders
  [AUTO]   Display list with plan names (reuses elektafdt_crawler logic)
  [PROMPT] "Enter patient folder name (e.g., patient_22002761): "
  [PROMPT] "Enter sequential anonymised ID (e.g., PAT01): "
  [PROMPT] "Enter anatomical site name (e.g., Prostate): "

STAGE 2: DATA DISCOVERY
  [AUTO]   Enumerate all img_* directories under IMAGES/
  [AUTO]   Parse INI files for scan dates, kV, mA
  [AUTO]   Parse _Frames.xml for treatment plan name
  [AUTO]   Check for RPS.dcm presence
  [AUTO]   Extract registration shifts from RPS.dcm
  [DISPLAY] Summary table of all CBCT sessions with dates, shifts, plan names

STAGE 3: MANUAL VERIFICATION CHECKPOINTS
  [PROMPT] "Have you verified height/weight in Mosaiq assessments? (y/n)"
  [PROMPT] "Have you opened the plan in Monaco and verified PTV in 3D view? (y/n)"
  [PROMPT] "Have you run Contour Alignment Tool and confirmed target in >=180 deg? (y/n)"
  [PROMPT] "Is this SFOV CBCT? (y/n)"

STAGE 4: FRACTION ASSIGNMENT
  [AUTO]   Sort sessions chronologically, assign FX0, FX1...
  [AUTO]   Group same-day CBCTs as CBCT1, CBCT2
  [DISPLAY] Proposed fraction assignment table
  [PROMPT] "Accept fraction assignment? (y/n/edit)"

STAGE 5: ANONYMISATION
  [AUTO]   Run DicomAnonymiser on CT_SET/ and DICOM_PLAN/
  [DISPLAY] Summary: "Anonymised X CT files and Y plan files with ID: PATxx"
  [PROMPT] "Verify anonymisation. Continue? (y/n)"

STAGE 6: FOLDER STRUCTURE CREATION
  [AUTO]   Create LEARN directory structure
  [AUTO]   Copy .his files to KIM-KV/
  [AUTO]   Copy .SCAN files to Reconstructed CBCT/
  [AUTO]   Copy .RPS.dcm to Registration file/
  [AUTO]   Copy anonymised CT/Plan to Patient Plans/
  [DISPLAY] File manifest with counts and sizes

STAGE 7: TREATMENT NOTES GENERATION
  [AUTO]   Generate Treatment_Notes.xlsx pre-filled with extracted data
  [PROMPT] "Enter mAs value (or Enter if same as mA): "
  [PROMPT] "Marker Length and Type (or N/A): "
  [PROMPT] "CDOG version (or N/A): "
  [AUTO]   Save to Patient Files/PATxx/Treatment_Notes.xlsx

STAGE 8: TRANSFER READINESS CHECK
  [AUTO]   Validate directory structure against LEARN template
  [AUTO]   Count files per fraction, verify completeness
  [AUTO]   Spot-check anonymised files for residual PHI
  [DISPLAY] Final summary with total size and file counts
  [PROMPT] "Ready for SFTP transfer. Use Cyberduck/WinSCP to upload."
```

## Data Extraction: Automatic vs Manual

| Data Point | Auto? | Source |
|------------|-------|--------|
| Patient MRN | Yes | Folder name `patient_XXXXXXXX` |
| Treatment plan name | Yes | `_Frames.xml` `<Treatment><ID>` |
| Scan date/time | Yes | INI `ScanUID` (embedded datetime) |
| kV | Yes | INI `TubeKV=` |
| mA | Yes | INI `TubeMA=` |
| Registration shifts (Sup/Lat/Ant) | Yes | RPS.dcm via ElektaRPSExtractor |
| Angular corrections (Cor/Sag/Trans) | Yes | RPS.dcm rotation values |
| Fraction number | Derived | Chronological sort of scan dates |
| CBCT number within fraction | Derived | Same-day grouping |
| FOV type (SFOV/MFOV) | Partial | Could check INI.XVI CollimatorName |
| Sequential anonymised ID | **Manual** | User assigns from Patient Data Log |
| Anatomical site name | **Manual** | User determines from plan name |
| Height/weight | **Manual** | Mosaiq assessments only |
| Target in projections | **Manual** | Visual check with Contour Alignment Tool |
| Mosaiq shift verification | **Manual** | Cross-check with Mosaiq SRO display |
| Plan verified in Monaco | **Manual** | User opens Monaco 3D view |

## Implementation Phases

### Phase 1: Foundation
1. Create `learn_upload/` package with `__init__.py`, `config.py`, `utils.py`
2. Implement INI parsing utilities (generalise from existing scripts)
3. Write unit tests for INI parsing

### Phase 2: Anonymisation
4. Implement `anonymise_dicom.py` with `DicomAnonymiser`
5. Test against sample DICOM files
6. Verify UID integrity in anonymised output

### Phase 3: Folder Mapping
7. Implement `folder_sort.py` with `LearnFolderMapper`
8. Implement fraction assignment logic
9. Add dry-run mode
10. Validate output against `Docs/Prostate/` template

### Phase 4: Treatment Notes
11. Implement `treatment_notes.py`
12. Match formatting to existing Treatment_Notes.xlsx templates

### Phase 5: Wrapper Integration
13. Implement `upload_workflow.py` with all 8 stages
14. End-to-end testing with real patient directory

## Technical Notes

- All scripts use `pathlib.Path` for Windows UNC and mapped drive compatibility
- Source data is never modified -- all output goes to a staging directory
- Dry-run mode available for folder sorting (preview without copying)
- Large .his file copies use `shutil.copy2` with progress reporting
- Error handling follows existing patterns: graceful degradation for missing files/malformed data

## Existing Code to Reuse

| File | What to Reuse |
|------|--------------|
| `scripts/elektafdt_crawler.py` | Patient directory traversal, `_Frames.xml` parsing, CSV output |
| `scripts/extract_elekta_rps_matrices.py` | `ElektaRPSExtractor` class for RPS.dcm shift extraction, ZIP-embedded INI parsing |
