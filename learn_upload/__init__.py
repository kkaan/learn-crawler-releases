"""
learn_upload — Automation tools for the LEARN data transfer pipeline.

Transfers Elekta XVI CBCT patient data from GC (GenesisCare) to
USYD RDS/research/PRJ-LEARN, replacing manual steps with Python scripts.

DICOM Anonymisation Approach
----------------------------
This package uses raw pydicom for DICOM anonymisation rather than dedicated
anonymisation libraries (deid, dicognito, dicom-anonymizer). Rationale:

1. We must PRESERVE original DICOM UIDs to maintain referential integrity
   between CT, structure set, and plan files. Most anonymisation libraries
   replace UIDs by default to break linkage — the opposite of what we need.
2. Our scope is narrow: ~10 specific tags to modify/clear per the LEARN SOP.
   A recipe-based system would require configuring exceptions for every tag
   we DON'T want touched.
3. pydicom is already a dependency — no additional packages needed.
4. Full control over edge cases in Elekta XVI exports.
"""

__version__ = "0.1.0"
