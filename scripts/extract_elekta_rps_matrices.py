#!/usr/bin/env python3
"""
Elekta XVI RPS DICOM Matrix Extractor

Extracts registration/transformation matrices from Elekta XVI RPS DICOM exports.
These files use proprietary private tags with embedded ZIP files containing INI files
with the actual registration data.

Author: Medical Physics Utility
Usage: python extract_elekta_rps_matrices.py <rps_dicom_file>
"""

import io
import re
import sys
import zipfile
from pathlib import Path

import numpy as np
import pydicom


class ElektaRPSExtractor:
    """Extract registration matrices from Elekta XVI RPS DICOM files"""

    def __init__(self, dicom_path):
        self.dicom_path = Path(dicom_path)
        self.dcm = None
        self.ini_content = None
        self.matrices = {}
        self.alignment_info = {}

    def read_dicom(self):
        """Read the DICOM file"""
        print(f"Reading DICOM file: {self.dicom_path}")
        self.dcm = pydicom.dcmread(str(self.dicom_path))

        # Verify it's an Elekta REG modality
        if self.dcm.Modality != 'REG':
            print(f"Warning: Modality is {self.dcm.Modality}, expected REG")

        if hasattr(self.dcm, 'Manufacturer'):
            print(f"Manufacturer: {self.dcm.Manufacturer}")

        return True

    def extract_zip(self):
        """Extract the embedded ZIP file from private DICOM tag"""
        # Elekta stores ZIP data in private tag (0021,103A)
        if (0x0021, 0x103A) not in self.dcm:
            raise ValueError("ZIP data not found in expected tag (0021,103A)")

        zip_data = self.dcm[0x0021, 0x103A].value

        try:
            zip_buffer = io.BytesIO(zip_data)
            with zipfile.ZipFile(zip_buffer, 'r') as zf:
                print(f"\nFound ZIP archive with {len(zf.namelist())} files:")
                for filename in zf.namelist():
                    print(f"  - {filename}")

                # Find and read the .INI.XVI file (contains registration data)
                ini_files = [f for f in zf.namelist() if f.endswith('.INI.XVI')]
                if not ini_files:
                    raise ValueError("No .INI.XVI file found in ZIP archive")

                print(f"\nReading registration data from: {ini_files[0]}")
                self.ini_content = zf.read(ini_files[0]).decode('utf-8', errors='ignore')

        except zipfile.BadZipFile:
            raise ValueError("Invalid ZIP data in DICOM file")

        return True

    def parse_matrix(self, matrix_string):
        """Parse a 16-element transformation matrix string into 4x4 numpy array"""
        values = [float(x) for x in matrix_string.split()]
        if len(values) != 16:
            return None

        # Reshape into 4x4 matrix (row-major order)
        matrix = np.array(values).reshape(4, 4)
        return matrix

    def extract_matrices(self):
        """Extract all transformation matrices from INI content"""
        if not self.ini_content:
            raise ValueError("No INI content loaded")

        # Extract unmatched transformation matrices
        unmatched_pattern = r'OnlineToRefTransformUnMatched=(.+?)(?:\n|$)'
        unmatched_matches = re.findall(unmatched_pattern, self.ini_content)

        # Extract correction transformation matrices
        correction_pattern = r'OnlineToRefTransformCorrection=(.+?)(?:\n|$)'
        correction_matches = re.findall(correction_pattern, self.ini_content)

        self.matrices['unmatched'] = []
        for matrix_str in unmatched_matches:
            matrix = self.parse_matrix(matrix_str)
            if matrix is not None:
                self.matrices['unmatched'].append(matrix)

        self.matrices['correction'] = []
        for matrix_str in correction_matches:
            matrix = self.parse_matrix(matrix_str)
            if matrix is not None:
                self.matrices['correction'].append(matrix)

        return len(self.matrices['unmatched']) + len(self.matrices['correction']) > 0

    def extract_alignment_info(self):
        """Extract alignment parameters and couch shifts"""
        if not self.ini_content:
            raise ValueError("No INI content loaded")

        # Alignment date/time
        align_info = re.search(r'\[ALIGNMENT\.(\d+); ([\d:]+)\]', self.ini_content)
        if align_info:
            self.alignment_info['date'] = align_info.group(1)
            self.alignment_info['time'] = align_info.group(2)

        # Clipbox alignment
        clip_match = re.search(r'Align\.clip1=(.+)', self.ini_content)
        if clip_match:
            values = [float(x.strip()) for x in clip_match.group(1).split(',')]
            self.alignment_info['clipbox'] = {
                'lateral': values[0],
                'longitudinal': values[1],
                'vertical': values[2],
                'rotation': values[3],
                'pitch': values[4],
                'roll': values[5]
            }

        # Mask alignment
        mask_match = re.search(r'Align\.mask1=(.+)', self.ini_content)
        if mask_match:
            values = [float(x.strip()) for x in mask_match.group(1).split(',')]
            self.alignment_info['mask'] = {
                'lateral': values[0],
                'longitudinal': values[1],
                'vertical': values[2],
                'rotation': values[3],
                'pitch': values[4],
                'roll': values[5]
            }

        # Couch shifts
        couch_lat = re.search(r'CouchShiftLat=(.+)', self.ini_content)
        couch_long = re.search(r'CouchShiftLong=(.+)', self.ini_content)
        couch_height = re.search(r'CouchShiftHeight=(.+)', self.ini_content)

        if couch_lat and couch_long and couch_height:
            self.alignment_info['couch_shifts'] = {
                'lateral': float(couch_lat.group(1).strip()),
                'longitudinal': float(couch_long.group(1).strip()),
                'vertical': float(couch_height.group(1).strip())
            }

        # Isocenter
        isoc_match = re.search(r'IsocX=(.+?)\nIsocY=(.+?)\nIsocZ=(.+?)\n', self.ini_content)
        if isoc_match:
            self.alignment_info['isocenter'] = {
                'x': float(isoc_match.group(1).strip()),
                'y': float(isoc_match.group(2).strip()),
                'z': float(isoc_match.group(3).strip())
            }

        # Registration protocol
        reg_protocol = re.search(r'RegistrationProtocol=(.+)', self.ini_content)
        if reg_protocol:
            self.alignment_info['registration_protocol'] = reg_protocol.group(1)

        return True

    def print_results(self):
        """Print extracted matrices and alignment information"""
        print("\n" + "="*70)
        print("ELEKTA XVI REGISTRATION DATA")
        print("="*70)

        if 'date' in self.alignment_info:
            print(f"\nAlignment Date: {self.alignment_info['date']}")
            print(f"Alignment Time: {self.alignment_info['time']}")

        if 'registration_protocol' in self.alignment_info:
            print(f"Registration Protocol: {self.alignment_info['registration_protocol']}")

        # Print alignment parameters
        if 'clipbox' in self.alignment_info:
            cb = self.alignment_info['clipbox']
            print("\nClipbox Alignment:")
            print(f"  Translation (L/L/V): {cb['lateral']:.2f}, {cb['longitudinal']:.2f}, {cb['vertical']:.2f} cm")
            print(f"  Rotation (R/P/R):    {cb['rotation']:.1f}°, {cb['pitch']:.1f}°, {cb['roll']:.1f}°")

        if 'mask' in self.alignment_info:
            m = self.alignment_info['mask']
            print("\nMask Alignment:")
            print(f"  Translation (L/L/V): {m['lateral']:.2f}, {m['longitudinal']:.2f}, {m['vertical']:.2f} cm")
            print(f"  Rotation (R/P/R):    {m['rotation']:.1f}°, {m['pitch']:.1f}°, {m['roll']:.1f}°")

        if 'couch_shifts' in self.alignment_info:
            cs = self.alignment_info['couch_shifts']
            print("\nCouch Shifts (applied):")
            print(f"  Lateral:      {cs['lateral']:.2f} cm")
            print(f"  Longitudinal: {cs['longitudinal']:.2f} cm")
            print(f"  Vertical:     {cs['vertical']:.2f} cm")

        if 'isocenter' in self.alignment_info:
            iso = self.alignment_info['isocenter']
            print("\nReference Isocenter:")
            print(f"  X: {iso['x']:.3f} cm")
            print(f"  Y: {iso['y']:.3f} cm")
            print(f"  Z: {iso['z']:.3f} cm")

        # Print transformation matrices
        print("\n" + "="*70)
        print("4x4 TRANSFORMATION MATRICES")
        print("="*70)

        for i, matrix in enumerate(self.matrices.get('unmatched', []), 1):
            print(f"\nOnlineToRefTransform_Unmatched #{i}:")
            print(matrix)

        for i, matrix in enumerate(self.matrices.get('correction', []), 1):
            print(f"\nOnlineToRefTransform_Correction #{i}:")
            print(matrix)

        print("\n" + "="*70)

    def get_correction_matrix(self, index=0):
        """
        Get the correction transformation matrix

        Parameters:
        -----------
        index : int
            Index of correction matrix (default 0 for first/only matrix)

        Returns:
        --------
        numpy.ndarray : 4x4 transformation matrix
        """
        if 'correction' not in self.matrices or len(self.matrices['correction']) == 0:
            raise ValueError("No correction matrices found")

        if index >= len(self.matrices['correction']):
            raise IndexError(f"Correction matrix index {index} out of range")

        return self.matrices['correction'][index]

    def extract_all(self):
        """Convenience method to extract everything"""
        self.read_dicom()
        self.extract_zip()
        self.extract_matrices()
        self.extract_alignment_info()
        return True


def main():
    if len(sys.argv) != 2:
        print("Usage: python extract_elekta_rps_matrices.py <rps_dicom_file>")
        sys.exit(1)

    dicom_file = sys.argv[1]

    try:
        extractor = ElektaRPSExtractor(dicom_file)
        extractor.extract_all()
        extractor.print_results()

        # Example: Access specific matrix
        print("\n" + "="*70)
        print("EXAMPLE: Accessing correction matrix programmatically")
        print("="*70)
        correction_matrix = extractor.get_correction_matrix(0)
        print("Correction matrix (4x4):")
        print(correction_matrix)

    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
