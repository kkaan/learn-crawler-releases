# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for learn_upload GUI."""

a = Analysis(
    ["learn_upload/__main__.py"],
    pathex=["cbct-shifts", "scripts"],
    binaries=[],
    datas=[],
    hiddenimports=[
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "pydicom",
        "numpy",
        "report_patient_details",
        "compare_rps_mosaiq",
        "extract_elekta_rps_matrices",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "scipy",
        "pandas",
        "tkinter",
        "PIL",
        "IPython",
        "notebook",
        "sphinx",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="learn_upload",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
)
