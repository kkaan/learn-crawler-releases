# Elekta XVI RPS DICOM File Format - Technical Summary

## Overview
Elekta XVI exports Registration Position Storage (RPS) files as DICOM with modality "REG", but these are NOT standard DICOM Spatial Registration Objects. Instead, Elekta uses a proprietary format with embedded data.

## File Structure

### DICOM Header
- **Modality**: REG
- **SOP Class UID**: 1.2.840.10008.5.1.4.1.1.66 (Raw Data Storage)
- **Series Description**: RPS
- **Manufacturer**: ELEKTA

### Private Tags
Elekta stores the actual registration data in private DICOM tags:

- **(0019,0010)**: "ELEKTA" (private creator)
- **(0021,0010)**: "Elekta: zip file"
- **(0021,0011)**: "Elekta: RPS data"
- **(0021,103A)**: The actual ZIP file data (VR=UN)

### Embedded ZIP Archive
The private tag (0021,103A) contains a ZIP file with:

1. **[UID].INI.XVI** - Main registration data file (contains matrices!)
2. **[UID].INI** - Basic settings and display parameters
3. **[UID].MASK.[date]** - Binary mask data

## Registration Data Format

The .INI.XVI file contains the registration matrices in plain text format:

```
OnlineToRefTransformUnMatched = [16 space-separated float values]
OnlineToRefTransformCorrection = [16 space-separated float values]
```

### Matrix Format
- 16 values representing a 4×4 homogeneous transformation matrix
- **Row-major order** storage
- Values are in **centimeters** for translation
- Rotation matrix component uses standard 3×3 rotation representation

### Matrix Structure
```
[ R11  R12  R13  Tx ]
[ R21  R22  R23  Ty ]
[ R31  R32  R33  Tz ]
[  0    0    0    1 ]
```

Where:
- R = 3×3 rotation matrix
- T = translation vector (cm)

## Coordinate Systems

### IEC Convention
From the INI file:
- `IECAngleConvention=1`
- `IECLinearConvention=2`

### Typical XVI Matrix
The matrices typically show a coordinate system transformation. For example:
```
[[ 0   0  -1   0  ]
 [ 0   1   0   0  ]
 [ 1   0   0   0  ]
 [Tx  Ty  Tz  1  ]]
```

This represents:
- 90° rotation about Y-axis (X becomes -Z, Z becomes X)
- Translation by (Tx, Ty, Tz)

## Alignment Information Available

### 1. Clipbox Alignment
Initial bone-based registration (translation + rotation):
- Lateral, Longitudinal, Vertical (cm)
- Rotation, Pitch, Roll (degrees)

### 2. Mask Alignment
Refined grey-value registration within mask (translation + rotation):
- Lateral, Longitudinal, Vertical (cm)
- Rotation, Pitch, Roll (degrees)

### 3. Couch Shifts
Applied corrections:
- Lateral shift (cm)
- Longitudinal shift (cm)
- Vertical shift (cm)

### 4. Transformation Matrices
- **Unmatched**: Fixed coordinate-system rotation (XVI to patient/IEC coordinates) plus isocenter offset. This matrix is **identical across all fractions** for a given patient — it contains no patient-specific correction.
- **Correction**: Same coordinate rotation as Unmatched, plus the patient-specific translational and rotational corrections from the registration. The relative rotation `R_correction @ R_unmatched^(-1)` yields a near-identity matrix encoding the small correction angles.

In practice, the Clipbox INI values (`Align.clip1`) provide the corrections directly — matrix decomposition is not needed for extracting shifts and rotations.

### 5. INI Field Relationships

The INI `[ALIGNMENT]` section contains several related representations of the same correction:

```ini
Align.clip1=-0.21, 0.05, -0.28, 0.4, 0.8, 359.8
#            lat    long   vert   rot  pitch roll  (6-DOF)

Align.correction=-0.21, 0.05, -0.28, 0.4, 0.8, 359.8
#                 identical to Align.clip1 when Clipbox is the correction source

CouchShiftLat=0.21        # = negated Clipbox lateral
CouchShiftLong=-0.05      # = negated Clipbox longitudinal
CouchShiftHeight=0.28     # = negated Clipbox vertical
CouchPitch=-              # unavailable (couch rotation not recorded separately)
CouchRoll=-
CouchYaw=-
```

The CouchShift values are the **negated** Clipbox translations — they represent the physical couch movement direction (opposite to the image-space correction). Rotation values above 180 degrees use a 360-degree wrapping convention (e.g. 359.8 means -0.2 degrees).

## Mapping to Mosaiq CBCT Shift Records

The following mapping was validated against 6 CBCT registration sessions (PAT01, 4 fractions) by comparing RPS Clipbox values to Mosaiq image-list shift records. All non-zero values matched exactly.

### Translations (cm)

| Mosaiq Field | RPS Clipbox Field | Sign | CouchShift Field | Sign |
|---|---|---|---|---|
| Sup/Inf | `longitudinal` | same | `CouchShiftLong` | negated |
| Lft/Rht | `lateral` | same | `CouchShiftLat` | negated |
| Ant/Pos | `vertical` | same | `CouchShiftHeight` | negated |

Mosaiq sign convention: Sup=+, Inf=-, Lft=+, Rht=-, Ant=+, Pos=-.

### Rotations (degrees)

| Mosaiq Field | RPS Clipbox Field | Sign |
|---|---|---|
| Cor(B) | `roll` | same |
| Sag(B) | `rotation` | same |
| Trans(B) | `pitch` | **negated** |

Mosaiq sign convention: CW=+, CCW=-. Clipbox angles >180 must be unwrapped (subtract 360) before comparison.

**The rotation axes are permuted** — Mosaiq's Coronal maps to Clipbox Roll, Sagittal maps to Clipbox Rotation, and Transverse maps to negated Clipbox Pitch. This was confirmed across all 4 non-zero rotation cases with exact agreement.

### Verification Script

The mapping was determined using `cbct-shifts/compare_rps_mosaiq.py`, which parses the Mosaiq TSV log (`cbct-shifts/CBCT-shifts-from-mosaiq.txt`), extracts RPS data from all fraction CBCT files, matches records by date/time, and prints a side-by-side comparison.

## Safety Considerations

⚠️ **CRITICAL SAFETY NOTES:**

1. **Coordinate System Validation**
   - ALWAYS verify the coordinate system conventions when importing these matrices into other systems
   - XVI uses IEC conventions which may differ from your TPS
   - The rotation matrix and translation vector must be interpreted correctly

2. **Matrix Application Order**
   - Verify whether matrices are applied as pre-multiplication or post-multiplication
   - Understand the reference frames: Online→Reference vs Reference→Online

3. **Units**
   - Translation values are in CENTIMETERS
   - Rotations are in DEGREES (in alignment parameters)
   - Verify unit consistency when exporting to other systems

4. **Clinical Validation**
   - Any automated extraction and use of these matrices for treatment must be validated
   - Verify end-to-end with known test cases
   - Compare against XVI display for several cases

5. **Version Compatibility**
   - This format is for XVI 5.x (seen in your file: "NKI-XVI 5.103")
   - Different XVI versions may have format variations
   - Always test with your specific XVI version

## Extraction Methods

### Method 1: Python with pydicom (Recommended)
```python
from extract_elekta_rps_matrices import ElektaRPSExtractor  # in scripts/

extractor = ElektaRPSExtractor("rps_file.dcm")
extractor.extract_all()
correction_matrix = extractor.get_correction_matrix(0)
```

### Method 2: Manual Extraction
1. Read DICOM file
2. Extract private tag (0021,103A)
3. Unzip the embedded data
4. Parse .INI.XVI file for matrix strings
5. Convert 16-element array to 4×4 matrix

## Common Use Cases

1. **QA Verification**: Compare XVI registrations with independent calculations
2. **Data Analysis**: Analyze registration patterns over time
3. **Export to TPS**: Import XVI registrations into treatment planning systems
4. **Research**: Study registration accuracy and reproducibility

## Example Output from Your File

**Patient**: Anonymised, DOB (01-01-1999))
**Treatment**: LtLungSBRT  
**Alignment Date**: 2023-10-10 16:17:49  
**Protocol**: Clipbox → Mask

**Couch Shifts Applied**:
- Lateral: -0.12 cm
- Longitudinal: 0.54 cm
- Vertical: 0.12 cm

**Correction Matrix**:
```
[[ 0.    0.   -1.    0.  ]
 [ 0.    1.    0.    0.  ]
 [ 1.    0.    0.    0.  ]
 [10.8   4.92  5.21  1.  ]]
```

## References & Resources

- Elekta XVI User Manual (version-specific)
- DICOM Standard PS3.3 (for private tag conventions)
- IEC 61217: Radiotherapy equipment - Coordinates, movements and scales

---

**Document Version**: 1.1
**Date**: 2026-02-24
**Tool**: scripts/extract_elekta_rps_matrices.py, cbct-shifts/compare_rps_mosaiq.py
