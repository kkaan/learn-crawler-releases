# learn_upload

Desktop wizard that automates the LEARN data transfer pipeline: transferring
Elekta XVI CBCT patient imaging from GenesisCare exports to the USYD
RDS/research/PRJ-LEARN structure. Covers folder sorting, DICOM anonymisation,
PII verification, and CBCT shift reporting.

**Landing page:** https://kkaan.github.io/learn-crawler-releases/

## Download

Grab the latest **`learn_upload.exe`** from the
**[latest release](https://github.com/kkaan/learn-crawler-releases/releases/latest)**.
No Python installation required — download and double-click.

### Use a local drive

XVI exports contain thousands of small `.his` projection files. Reading
these over a network share is significantly slower than working from a
local disk.

1. Copy the `patient_XXXXXXXX/` folder from the network to a local drive.
2. Run `learn_upload.exe`.
3. Point the source path to your local copy.
4. Set the output path to another local directory (e.g. `E:\LEARN_OUTPUT`).
5. Once processing is complete, copy the output to the RDS research drive.

## Run from source

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/kkaan/learn-crawler-releases.git
cd learn-crawler-releases

uv sync --extra gui --extra dev
uv run python -m learn_upload      # launch the GUI
uv run python -m pytest tests/ -v  # run tests
```

## What the GUI does

The wizard walks through 6 steps:

1. **Configuration** — paths, anonymised ID (PATxx), site name, PII search strings.
2. **Data Preview** — discover XVI sessions and preview fraction assignments.
3. **Folder Sort** — copy files into the LEARN directory structure.
4. **Anonymise** — run DICOM anonymisation with per-file progress.
5. **PII Verification** — scan output for residual patient data.
6. **CBCT Shift Report** — generate a markdown report of CBCT registration shifts.

See the **[GUI Walkthrough](https://kkaan.github.io/learn-crawler-releases/#doc=GUI_Walkthrough.md)**
for a step-by-step guide with screenshots.

## Repository layout

| Directory | Description |
|-----------|--------------|
| `learn_upload/` | Core package — anonymisation, folder sorting, PII verification, GUI |
| `cbct-shifts/` | CBCT shift analysis scripts (Mosaiq vs RPS comparison) |
| `scripts/` | Standalone CLI tools (RPS matrix extraction, DICOM tag reader, XVI crawler, single-file anonymiser) |
| `examples/` | Pipeline usage example |
| `tests/` | pytest suite |
| `docs/` | This landing page and the documentation linked from it |

## Documentation

- [GUI Walkthrough](https://kkaan.github.io/learn-crawler-releases/#doc=GUI_Walkthrough.md)
- [GC Elekta Patient Upload Process (SOP)](https://kkaan.github.io/learn-crawler-releases/#doc=GC_Elekta_Patient_Upload_Process.md)
- [LEARN Upload Automation Plan](https://kkaan.github.io/learn-crawler-releases/#doc=LEARN_Upload_Automation_Plan.md)
- [XVI Reconstruction Directory Analysis](https://kkaan.github.io/learn-crawler-releases/#doc=Elekta_XVI_Reconstruction_Directory_Analysis.md)
- [Elekta RPS Format Documentation](https://kkaan.github.io/learn-crawler-releases/#doc=elekta_rps_format_documentation.md)
- [SRO Experimental Validation Notes](https://kkaan.github.io/learn-crawler-releases/#doc=elekta_xvi_sro_experimental_validation.md)
