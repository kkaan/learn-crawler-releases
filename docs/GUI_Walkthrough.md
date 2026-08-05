# LEARN Pipeline GUI Walkthrough

> Looking for the download? Grab `learn_upload.exe` from the
> [public releases page](https://github.com/kkaan/learn-crawler-releases/releases/latest).

## Purpose

The LEARN Pipeline GUI is a 6-step desktop wizard that automates the transfer of Elekta XVI CBCT patient data from GenesisCare exports to the USYD RDS/research/PRJ-LEARN directory structure. It replaces the manual workflow documented in the [GC Elekta Patient Upload Process](GC_Elekta_Patient_Upload_Process.md) with a guided, reproducible process covering folder sorting, DICOM anonymisation, PII verification, and CBCT shift reporting.

## Prerequisites

- **Python 3.10+** and [uv](https://docs.astral.sh/uv/). Install dependencies with:
  ```bash
  uv sync --extra gui --extra dev
  ```
- Access to the XVI patient export directory (e.g. `\\GC04PRBAK02\elekta_fdt\XVI_COLLECTION\processed\`)
- A writable output directory for the LEARN folder structure

## Expected Input: XVI Export Directory

The **Source Path** in Step 1 should point to an Elekta XVI patient export with this structure:

```
patient_XXXXXXXX/
  XVI Export/                          <- configurable via "Images Subdirectory" field
    img_<UID>/                         <- one directory per acquisition session
      _Frames.xml                      <- treatment ID, acquisition preset, kV/mA
      *.his                            <- raw X-ray projection images
      Reconstruction/
        *.INI / *.INI.XVI              <- ScanUID (embeds datetime), tube kV/mA
        *.SCAN                         <- reconstructed CBCT volume
        *.SCAN.MACHINEORIENTATION      <- machine orientation metadata
        *.RPS.dcm                      <- registration DICOM (couch shifts)
    img_<UID>/ ...                     <- additional sessions
```

### Optional Input: TPS Export

If a **TPS Export Path** is provided, the whole export tree is scanned and DICOM
files are classified by their **Modality** tag (not by folder name), so the
export's folder layout does not matter:

| Modality | Picked up as |
|----------|--------------|
| `CT` | reference CT slices |
| `RTPLAN` | treatment plan |
| `RTSTRUCT` | structure set |
| `RTDOSE` | dose distribution |

A typical Monaco export nests these under folders such as `DICOM CT Images/`,
`DICOM RT Plan/`, and `TPS Calculated/` (for dose) — but any layout works, and
non-target modalities (e.g. EPID/portal images) are ignored.

### Optional Input: Trajectory Logs

If a **Trajectory Logs Dir** is provided, it should contain fraction-numbered subdirectories:

```
Trajectory_Logs/
  FX01/
    MarkerLocations*.txt               <- KIM marker tracking data
  FX02/ ...
```

## Launching the GUI

```bash
uv run python -m learn_upload
```

The window opens with a dark-themed interface. A sidebar on the left shows all six steps; the main panel on the right displays the active step. Completed steps get a green checkmark in the sidebar and can be clicked to review.

---

## Step 1: Configuration

The Configuration page collects all the parameters needed for the pipeline run. It is divided into four cards.

### Patient Identity

| Field | Description |
|-------|-------------|
| **Anonymised ID** | The PATxx identifier for this patient (e.g. `PAT01`). Must match the format `PATxx` where `xx` is a two-digit number. |
| **Site Name** | The treatment site label used as a subfolder in the output (e.g. `prostate`). |

### Data Paths

| Field | Description |
|-------|-------------|
| **Source Path** | Root of the XVI patient export (e.g. `Patient_258215`). Contains the `IMAGES/` or `XVI Export/` subdirectory. |
| **TPS Export Path** | Path to exported treatment planning system DICOM files (optional). |
| **Output Path** | Root output directory where the LEARN folder structure will be created. |
| **Staging Path** | Intermediate staging directory. Defaults to `output/_staging` if left blank. |
| **Images Subdirectory** | Name of the images folder within the patient export. Defaults to `XVI Export`. |
| **Centroid File** | Path to a centroid CSV file for KIM data (optional). |
| **Trajectory Logs Dir** | Directory containing trajectory log files (optional). |

### PII Search Strings

A comma-separated list of patient identifiers (MRN, name fragments, etc.) that will be searched for during the PII verification step. The patient's MRN is also auto-detected from the source directory name.

### Options

- **Dry run** -- When checked, the folder sort step previews the file operations without copying any files.

![Configuration page showing Patient Identity, Data Paths, and PII Search Strings cards](images/gui-walkthrough/01.png)

![Options card with dry run checkbox and "Continue to Preview" button](images/gui-walkthrough/02.png)

Once all required fields are filled in, click **Continue to Preview** to proceed.

---

## Step 2: Data Preview

After submitting the configuration, the GUI discovers all imaging sessions within the source directory. A table displays the results with the following columns:

| Column | Description |
|--------|-------------|
| **Type** | Session type (e.g. `cbct`, `planar`). |
| **Directory** | The `img_` directory name containing this session. |
| **Datetime** | Scan date and time extracted from the ScanUID. |
| **Treatment** | Treatment plan ID parsed from `_Frames.xml`. |
| **kV** | Tube voltage from the reconstruction INI file. |
| **mA** | Tube current from the reconstruction INI file. |
| **RPS** | Whether an RPS registration file was found for this session. |

A stat card above the table shows the total number of discovered sessions. If
a **TPS Export Path** was provided, additional stat cards show the number of CT,
plan, structure, and dose DICOM files found in the expected TPS export folders.
Missing TPS categories are shown in orange as warnings, but the workflow can
continue; missing categories simply will not be imported during anonymisation.

Review the table to confirm the expected sessions are present, then click **Start Folder Sort** to proceed.

> *Screenshot to be added.*

---

## Step 3: Folder Sort

The folder sort step copies files from the XVI export into the LEARN directory structure, organising them by fraction and file type.

During execution, a progress bar shows the current operation (e.g. `FX4/KIM-KV`) and percentage. The log output panel displays real-time messages including treatment ID discovery from `_Frames.xml` files and session-to-fraction matching.

![Folder Sort in progress at 80%, log showing session matching and fraction assignment](images/gui-walkthrough/03.png)

When complete, stat cards display a summary of the sorted data:

| Stat | Description |
|------|-------------|
| **Sessions** | Total imaging sessions processed. |
| **Fractions** | Number of treatment fractions identified. |
| **.his Files** | Projection image files copied to KIM-KV folders. |
| **SCAN Files** | Reconstructed CBCT scan files copied. |
| **RPS Files** | Registration Position Storage DICOM files copied. |
| **INI Files** | Reconstruction parameter files copied. |

![Folder Sort complete showing 30 sessions, 5 fractions, 2673 .his files, 22 SCAN files, 8 RPS files, 44 INI files](images/gui-walkthrough/04.png)

Click **Start Anonymisation** to proceed.

---

## Step 4: Anonymise

The anonymisation step processes all DICOM, XML, and INI files in the output directory, replacing patient-identifiable information with the anonymised ID.

A progress bar tracks the current file being processed (e.g. `CT_1859_301.dcm`) and the overall percentage. The log output shows each file as it is anonymised, including the source and destination paths.

![Anonymise step in progress at 93%, processing DICOM files with log output](images/gui-walkthrough/05.png)

When complete, stat cards show:

| Stat | Description |
|------|-------------|
| **DICOM** | Number of DICOM files anonymised. |
| **XML** | Number of `_Frames.xml` files anonymised. |
| **INI** | Number of INI configuration files anonymised. |
| **TPS Imported** | Number of TPS export files imported and anonymised. |
| **Errors** | Number of files that failed to anonymise (highlighted in red if > 0). |

![Bottom of Anonymise page showing "Run PII Verification" button](images/gui-walkthrough/06.png)

Click **Run PII Verification** to proceed.

---

## Step 5: PII Verification

The PII verification step scans all files in the output directory for any residual patient-identifiable information matching the search strings configured in Step 1. The MRN extracted from the source directory name is automatically included.

![PII Verification scanning in progress](images/gui-walkthrough/07.png)

The result is displayed as either **PASS** (green banner) or **FAIL** (red banner), along with stat cards showing the number of files scanned and the number of findings.

![PII Verification FAIL result: 10,291 files scanned, 3 findings](images/gui-walkthrough/08.png)

If findings are detected, a table lists each one with:

| Column | Description |
|--------|-------------|
| **File** | Relative path to the file containing PII. |
| **Location** | Where in the file the match was found (e.g. DICOM tag name, XML element). |
| **Matched** | The PII string that was matched. |

If the result is FAIL, you should investigate and resolve the findings before uploading to LEARN. Common causes include PII embedded in private DICOM tags or XML metadata that was not covered by the anonymisation rules.

![Bottom of PII Verification page showing "Generate CBCT Report" button](images/gui-walkthrough/09.png)

Click **Generate CBCT Report** to proceed.

---

## Step 6: CBCT Shift Report

The final step generates a markdown report of CBCT couch shifts extracted from the RPS registration files. The report is displayed in a text viewer and automatically saved to the `Patient Files/PATxx/` folder as `cbct_shift_report.md`.

The report includes per-fraction registration shifts in patient coordinates, which can be cross-referenced with Mosaiq image list values for quality assurance.

If no RPS files are found in the output directory, an error message is shown instead.

Once the report is generated, click **New Patient** to reset the wizard and start processing the next patient.

> *Screenshot to be added.*
