# Elekta XVI Reconstruction Directory Analysis

## Overview

The Reconstruction directory comes from the Elekta XVI CBCT (Cone Beam Computed Tomography) imaging system export. This directory contains the reconstructed volumetric data and associated configuration files generated from the projection images (`.his` files) acquired during CBCT scanning on the VersaHD linear accelerator.

Export procedure to get this is in

The XVI system performs cone beam CT imaging for patient positioning verification and adaptive radiotherapy workflows. The Reconstruction directory stores the final 3D volumes along with all the technical parameters used during the reconstruction process.

## Directory Structure

Each patient's CBCT acquisition follows this structure:
```
patient_XXXXXXXX/
├── IMAGES/
│   └── img_[UID]/
│       ├── _Frames.xml                    # Projection acquisition parameters
│       ├── 00001.[UID].his               # Projection image files
│       ├── 00002.[UID].his               # ...
│       ├── ...                           # Additional projection files
│       └── Reconstruction/               # ← FOCUS OF THIS ANALYSIS
│           ├── [UID].INI                 # XVI software configuration
│           ├── [UID].INI.XVI             # Reconstruction parameters
│           ├── [UID].[timestamp].INI     # Session-specific configuration
│           ├── [UID].[timestamp].INI.XVI # Session-specific registratoin details
│           ├── [UID].[timestamp].SCAN    # Reconstructed volume data
│           ├── [UID].[timestamp].SCAN.MACHINEORIENTATION # Coordinate transformation
│           └── [UID].RPS.dcm             # DICOM registration data (optional)
```

## File Types and Contents

### 1. Configuration Files (.INI)

**Files**: `[UID].INI`, `[UID].[timestamp].INI`

These are XVI software configuration files containing:

#### XVI Software Settings
- User interface state and visibility settings
- Display parameters and zoom factors
- Administrative and logging configuration
- Multi-threading and refresh interval settings

#### Patient Identification
```ini
[IDENTIFICATION]
PatientID=15002197
TreatmentID=WholeBrain-C2Retrt
TreatmentUID=1.3.46.423632.33783920233217242713.224
ReferenceUID=1.2.840.113854.59112832676204369253232190232540417741
FirstName=Anonymized
LastName=Anonymized
```

#### Directory Paths
- `AdministrativeFilesDirectory`: Path to reconstruction admin files
- `ReferenceCacheDirectory`: CT reference image location
- `ProjectionDirectory`: Source projection files location
- `ReconstructedScansDirectory`: Output reconstruction location

#### Clinical Context
- Treatment plan description and patient information
- Links to treatment planning system via UIDs
- Status line text showing active treatment plan

### 2. Reconstruction Parameters (.INI.XVI)

**Files**: `[UID].INI.XVI`, `[UID].[timestamp].INI.XVI`

These files contain technical reconstruction parameters:

#### Volume Specifications
- `ReconstructionDimensionX/Y/Z`: Voxel dimensions (typically 264×270×270)
- `ReconstructionVoxelSize`: Spatial resolution (typically 0.1 cm)
- `ReconstructionOffsetX/Y/Z`: Volume positioning offsets

#### Image Processing Parameters
- `ProjectionImageDimension`: Detector size (typically 256×256)
- `ReconstructionFilter`: Applied filter type (e.g., "Wiener")
- `ReconstructionFilterParameters`: Filter-specific settings
- `ScatterCorrectionAlg`: Scatter correction algorithm
- `BowTieScatterCorrection`: Hardware scatter reduction

#### Technical Settings
- `ReconstructionDataType`: Internal data format (float)
- `OutputReconstructionDataType`: Export format (short)
- `ScaleOut` and `OffsetOut`: Hounsfield unit scaling
- `Interpolate`: Interpolation method
- `CollimatorName`: Beam collimation setup

### 3. Reconstructed Volume Data (.SCAN)

**Files**: `[UID].[timestamp].SCAN`

These are AVS (Application Visualization System) format files containing:

#### Header Information
```
# AVS wants to have the first line starting with its name

kv=100          # X-ray tube voltage
ma=10           # Tube current
ms=10           # Exposure time
ndim=3          # 3D volume data
dim1=264        # X dimension
dim2=270        # Y dimension
dim3=270        # Z dimension
```

#### Data Format Specification
- `nspace=3`: 3D spatial data
- `veclen=1`: Scalar values (not vector)
- `data=xdr_short`: 16-bit integer data in XDR format
- `field=uniform`: Regular grid spacing
- `nki_compression=2`: Compression type

#### Binary Volume Data
The remainder of the file contains the compressed 3D CBCT volume data representing the reconstructed CT numbers/Hounsfield units for each voxel.

### 4. Machine Orientation (.SCAN.MACHINEORIENTATION)

**Files**: `[UID].[timestamp].SCAN.MACHINEORIENTATION`

Contains coordinate system transformation data:

#### Transformation Matrix
- 4×4 transformation matrix in AVS format
- Maps between image coordinates and machine/IEC coordinates
- Essential for accurate patient positioning and registration
- Binary floating-point data in XDR format

### 5. DICOM Registration Data (.RPS.dcm)

**Files**: `[UID].RPS.dcm` (when present)

DICOM RT Registration and Positioning Structure files containing:
- Spatial registration information
- Coordinate system relationships
- Links to planning CT and treatment planning system
- DICOM-compliant metadata for integration with treatment planning

## Technical Context

### Coordinate Systems
The XVI system uses IEC 61217 coordinate conventions:
- Patient coordinate system (Fixed)
- Gantry coordinate system (Rotating)
- Table coordinate system (Translating/Rotating)

The MACHINEORIENTATION files provide the transformations between these coordinate systems at the time of imaging.

### Reconstruction Workflow
1. **Projection Acquisition**: kV X-ray projections captured as .his files
2. **Calibration**: Flat-field and dark-field corrections applied
3. **Preprocessing**: Scatter correction, beam hardening correction
4. **Reconstruction**: Filtered back-projection or iterative algorithms
5. **Output**: 3D volume saved as .SCAN files with metadata

### Data Integration
- **Treatment Planning**: ReferenceUID links to planning CT
- **Patient Positioning**: Transformation matrices enable registration
- **Quality Assurance**: Configuration files provide audit trail
- **Archive Storage**: Complete parameter set enables reprocessing


## File Size and Storage Considerations

- **.SCAN files**: Largest files, typically 20-50 MB depending on matrix size
- **.INI files**: Small text files, typically <10 KB
- **.MACHINEORIENTATION files**: Small binary files, typically <1 KB
- **.RPS.dcm files**: Variable size DICOM files, typically 1-10 KB

Total storage per CBCT scan: Approximately 25-60 MB including all reconstruction files.

