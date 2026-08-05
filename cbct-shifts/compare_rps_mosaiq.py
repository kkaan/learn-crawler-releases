#!/usr/bin/env python3
"""
Compare Mosaiq CBCT shift records with Elekta XVI RPS DICOM data.

Parses the Mosaiq tab-delimited log and RPS DICOM files, matches them by
date/time, and prints a side-by-side comparison to determine the coordinate
mapping between the two systems.
"""

import csv
import io
import re
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pydicom

# ---------------------------------------------------------------------------
# Import ElektaRPSExtractor from the repo root
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from extract_elekta_rps_matrices import ElektaRPSExtractor


# ===================================================================
# SECTION A -- Parse Mosaiq log
# ===================================================================

def parse_direction_value(text):
    """Parse a directional string like 'Sup 0.1 cm' into a signed float.

    Sign convention (Mosaiq):
      Translations: Sup=+, Inf=−, Lft=+, Rht=−, Ant=+, Pos=−
      Rotations:    CW=+, CCW=−
    Returns None for empty/missing values.
    """
    if not text or not text.strip():
        return None

    text = text.strip()
    m = re.match(r'(Sup|Inf|Lft|Rht|Ant|Pos|CW|CCW)\s+([\d.]+)\s*(cm|deg\.?)?', text)
    if not m:
        return None

    direction, magnitude = m.group(1), float(m.group(2))
    negative_dirs = {'Inf', 'Rht', 'Pos', 'CCW'}
    return -magnitude if direction in negative_dirs else magnitude


def parse_mosaiq_log(filepath):
    """Read the Mosaiq CBCT shifts TSV and return a list of record dicts."""
    records = []

    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f, delimiter='\t', quotechar='"')
        header = next(reader)  # skip header row

        # Collect all rows first (multi-line quoted Comments span rows)
        rows = list(reader)

    # The TSV has multi-line Comments fields. csv.reader handles quoted
    # newlines, but each "logical row" may map to one record. We identify
    # records by the Date/Time column (index 1) being non-empty.
    for row in rows:
        # Skip rows that are continuations of a previous multi-line field
        if len(row) < 12 or not row[1].strip():
            continue

        try:
            dt = datetime.strptime(row[1].strip(), "%d/%m/%Y %I:%M %p")
        except ValueError:
            continue

        rec = {
            'datetime': dt,
            'type': row[4].strip() if len(row) > 4 else '',
            'sup': parse_direction_value(row[11]) if len(row) > 11 else None,
            'lat': parse_direction_value(row[12]) if len(row) > 12 else None,
            'ant': parse_direction_value(row[13]) if len(row) > 13 else None,
            'cor_b': parse_direction_value(row[15]) if len(row) > 15 else None,
            'sag_b': parse_direction_value(row[16]) if len(row) > 16 else None,
            'trans_b': parse_direction_value(row[17]) if len(row) > 17 else None,
        }

        # Parse magnitude (scalar, no direction)
        if len(row) > 14 and row[14].strip():
            try:
                rec['mag'] = float(row[14].strip())
            except ValueError:
                rec['mag'] = None
        else:
            rec['mag'] = None

        # Flag records with no shift data
        rec['has_shifts'] = any(
            rec[k] is not None for k in ['sup', 'lat', 'ant']
        )

        records.append(rec)

    return records


# ===================================================================
# SECTION B -- Extract RPS data
# ===================================================================

def find_rps_files(base_path):
    """Glob for RPS DICOM files and extract FX/CBCT labels from path."""
    pattern = "**/Registration file/*.RPS.dcm"
    rps_files = sorted(base_path.glob(pattern))

    results = []
    for p in rps_files:
        # Path looks like: .../PAT01/FX1/CBCT/CBCT1/Registration file/xxx.RPS.dcm
        parts = p.parts
        fx_label = cbct_label = None
        for i, part in enumerate(parts):
            if part.startswith('FX'):
                fx_label = part
            if part.startswith('CBCT') and part != 'CBCT':
                cbct_label = part
        results.append({
            'path': p,
            'fx': fx_label,
            'cbct': cbct_label,
        })
    return results


def extract_rps_data(rps_path):
    """Extract all relevant data from an RPS DICOM file."""
    # Use ElektaRPSExtractor but suppress its stdout prints
    extractor = ElektaRPSExtractor(str(rps_path))
    buf = io.StringIO()
    with redirect_stdout(buf):
        extractor.extract_all()

    data = {}

    # Alignment date/time from INI -- parse DateTime=YYYYMMDD; HH:MM:SS
    ini = extractor.ini_content or ''
    dt_match = re.search(r'DateTime=(\d{8});\s*(\d{2}:\d{2}:\d{2})', ini)
    if dt_match:
        data['ini_datetime'] = datetime.strptime(
            f"{dt_match.group(1)} {dt_match.group(2)}", "%Y%m%d %H:%M:%S"
        )
    else:
        data['ini_datetime'] = None

    # DICOM ContentDate/ContentTime as backup
    dcm = extractor.dcm
    if hasattr(dcm, 'ContentDate') and hasattr(dcm, 'ContentTime'):
        cd = dcm.ContentDate  # YYYYMMDD
        ct = dcm.ContentTime  # HHMMSS.ffffff
        ct_clean = ct.split('.')[0]  # drop fractional seconds
        data['dicom_datetime'] = datetime.strptime(
            f"{cd} {ct_clean}", "%Y%m%d %H%M%S"
        )
    else:
        data['dicom_datetime'] = None

    # Alignment info from extractor
    ai = extractor.alignment_info

    # Couch shifts
    data['couch_shifts'] = ai.get('couch_shifts', {})

    # Clipbox alignment
    data['clipbox'] = ai.get('clipbox', {})

    # Mask alignment
    data['mask'] = ai.get('mask', {})

    # Correction matrix
    data['correction_matrices'] = extractor.matrices.get('correction', [])

    # Raw INI content for debugging
    data['ini_content'] = extractor.ini_content

    return data


# ===================================================================
# SECTION C -- Match by date/time
# ===================================================================

def match_records(mosaiq_records, rps_records, tolerance_min=15):
    """Match RPS records to Mosaiq records by date + closest time."""
    tolerance = timedelta(minutes=tolerance_min)
    matches = []

    for rps in rps_records:
        rps_dt = rps['data']['ini_datetime'] or rps['data']['dicom_datetime']
        if rps_dt is None:
            continue

        best_match = None
        best_delta = None

        for mq in mosaiq_records:
            if not mq['has_shifts']:
                continue
            if mq['datetime'].date() != rps_dt.date():
                continue
            delta = abs(mq['datetime'] - rps_dt)
            if delta <= tolerance and (best_delta is None or delta < best_delta):
                best_match = mq
                best_delta = delta

        matches.append({
            'rps': rps,
            'mosaiq': best_match,
            'rps_datetime': rps_dt,
            'time_delta': best_delta,
        })

    return matches


# ===================================================================
# SECTION D -- Comparison output
# ===================================================================

def unwrap_angle(deg):
    """Unwrap angle from [0,360) to [-180,180). e.g. 359.8 -> -0.2."""
    if deg is None:
        return None
    if deg > 180:
        return deg - 360
    return deg


def fmt(val, width=8):
    """Format a float or None for table display."""
    if val is None:
        return ' ' * width
    return f"{val:>{width}.3f}"


def print_comparison(matches):
    """Print detailed comparison and mapping analysis."""
    print("=" * 90)
    print("MOSAIQ vs RPS SHIFT COMPARISON")
    print("=" * 90)

    all_diffs = []

    for m in matches:
        rps = m['rps']
        mq = m['mosaiq']
        rps_data = rps['data']
        cs = rps_data['couch_shifts']
        cb = rps_data['clipbox']
        mk = rps_data['mask']

        print(f"\n{'-' * 90}")
        print(f"  {rps['fx']}/{rps['cbct']}")
        print(f"  RPS datetime:    {m['rps_datetime']}")
        if mq:
            print(f"  Mosaiq datetime: {mq['datetime']}  (delta: {m['time_delta']})")
        else:
            print("  Mosaiq: NO MATCH")
            continue

        print()
        print(f"  {'Field':<22} {'Mosaiq':>10} {'CouchShift':>12} {'Clipbox':>12} {'Mask':>12}")
        print(f"  {'-' * 22} {'-' * 10} {'-' * 12} {'-' * 12} {'-' * 12}")

        # Translations
        row_data = [
            ('Sup/Long (Sup+)',    'sup', 'longitudinal', 'longitudinal', 'longitudinal'),
            ('Lat (Lft+)',         'lat', 'lateral',      'lateral',      'lateral'),
            ('Ant/Vert (Ant+)',    'ant', 'vertical',     'vertical',     'vertical'),
        ]

        for label, mq_key, cs_key, cb_key, mk_key in row_data:
            mq_val = mq.get(mq_key)
            cs_val = cs.get(cs_key)
            cb_val = cb.get(cb_key)
            mk_val = mk.get(mk_key)
            print(f"  {label:<22} {fmt(mq_val, 10)} {fmt(cs_val, 12)} {fmt(cb_val, 12)} {fmt(mk_val, 12)}")

        # Rotations — axes are permuted between Mosaiq and Clipbox:
        #   Mq Cor(B)   = CB roll     (same sign)
        #   Mq Sag(B)   = CB rotation (same sign)
        #   Mq Trans(B) = -CB pitch   (negated)
        rot_data = [
            ('Cor(B) = CB Roll',   'cor_b', 'roll',     'roll'),
            ('Sag(B) = CB Rot',    'sag_b', 'rotation', 'rotation'),
            ('Trans(B) = -CB Ptch','trans_b','pitch',    'pitch'),
        ]

        print()
        for label, mq_key, cb_key, mk_key in rot_data:
            mq_val = mq.get(mq_key)
            cb_val = unwrap_angle(cb.get(cb_key))
            mk_val = unwrap_angle(mk.get(mk_key))
            # Negate pitch for Trans mapping display
            neg = " (neg)" if cb_key == 'pitch' else ""
            print(f"  {label:<22} {fmt(mq_val, 10)} {'':>12} {fmt(cb_val, 12)}{neg} {fmt(mk_val, 12)}")

        # Collect differences for mapping analysis
        diff = {
            'label': f"{rps['fx']}/{rps['cbct']}",
            'mq': mq,
            'cs': cs,
            'cb': cb,
            'mk': mk,
        }
        all_diffs.append(diff)

    # ---------------------------------------------------------------
    # Summary table
    # ---------------------------------------------------------------
    print(f"\n\n{'=' * 90}")
    print("SUMMARY TABLE -- All Matches")
    print("=" * 90)

    header = (
        f"  {'FX/CBCT':<12}"
        f"  {'Mq Sup':>8} {'CS Long':>8} {'CB Long':>8} {'Mk Long':>8}"
        f"  {'Mq Lat':>8} {'CS Lat':>8} {'CB Lat':>8} {'Mk Lat':>8}"
        f"  {'Mq Ant':>8} {'CS Vert':>8} {'CB Vert':>8} {'Mk Vert':>8}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))

    for d in all_diffs:
        mq, cs, cb, mk = d['mq'], d['cs'], d['cb'], d['mk']
        print(
            f"  {d['label']:<12}"
            f"  {fmt(mq['sup'])} {fmt(cs.get('longitudinal'))} {fmt(cb.get('longitudinal'))} {fmt(mk.get('longitudinal'))}"
            f"  {fmt(mq['lat'])} {fmt(cs.get('lateral'))} {fmt(cb.get('lateral'))} {fmt(mk.get('lateral'))}"
            f"  {fmt(mq['ant'])} {fmt(cs.get('vertical'))} {fmt(cb.get('vertical'))} {fmt(mk.get('vertical'))}"
        )

    # ---------------------------------------------------------------
    # Rotation summary (axes paired by confirmed mapping)
    # ---------------------------------------------------------------
    print(f"\n  {'FX/CBCT':<12}"
          f"  {'Mq Cor':>8} {'CB Roll':>8}"
          f"  {'Mq Sag':>8} {'CB Rot':>8}"
          f"  {'Mq Trn':>8} {'-CB Pch':>8}")
    print("  " + "-" * 70)

    for d in all_diffs:
        mq, cb, mk = d['mq'], d['cb'], d['mk']
        neg_pitch = unwrap_angle(cb.get('pitch'))
        if neg_pitch is not None:
            neg_pitch = -neg_pitch
        print(
            f"  {d['label']:<12}"
            f"  {fmt(mq['cor_b'])} {fmt(unwrap_angle(cb.get('roll')))}"
            f"  {fmt(mq['sag_b'])} {fmt(unwrap_angle(cb.get('rotation')))}"
            f"  {fmt(mq['trans_b'])} {fmt(neg_pitch)}"
        )

    # ---------------------------------------------------------------
    # Mapping analysis
    # ---------------------------------------------------------------
    print(f"\n\n{'=' * 90}")
    print("MAPPING ANALYSIS")
    print("=" * 90)

    # Check each candidate mapping between Mosaiq and RPS fields
    axis_pairs = [
        # (mosaiq_key, rps_source, rps_key, description)
        ('sup', 'CouchShift', 'longitudinal', 'Mq Sup  <-> CS Longitudinal'),
        ('sup', 'Clipbox',    'longitudinal', 'Mq Sup  <-> CB Longitudinal'),
        ('sup', 'Mask',       'longitudinal', 'Mq Sup  <-> Mk Longitudinal'),
        ('lat', 'CouchShift', 'lateral',      'Mq Lat  <-> CS Lateral'),
        ('lat', 'Clipbox',    'lateral',       'Mq Lat  <-> CB Lateral'),
        ('lat', 'Mask',       'lateral',       'Mq Lat  <-> Mk Lateral'),
        ('ant', 'CouchShift', 'vertical',      'Mq Ant  <-> CS Vertical'),
        ('ant', 'Clipbox',    'vertical',       'Mq Ant  <-> CB Vertical'),
        ('ant', 'Mask',       'vertical',       'Mq Ant  <-> Mk Vertical'),
    ]

    # Confirmed cross-axis rotation mapping
    rot_pairs = [
        ('cor_b',   'Clipbox', 'roll',     'Mq Cor(B)   = CB Roll'),
        ('sag_b',   'Clipbox', 'rotation', 'Mq Sag(B)   = CB Rotation'),
        ('trans_b', 'Clipbox', 'neg_pitch','Mq Trans(B)  = -CB Pitch'),
    ]

    rotation_keys = {'rotation', 'pitch', 'roll', 'neg_pitch'}

    def analyse_pairs(pairs, all_diffs):
        for mq_key, rps_src, rps_key, desc in pairs:
            src_map = {'CouchShift': 'cs', 'Clipbox': 'cb', 'Mask': 'mk'}
            src = src_map[rps_src]
            is_rotation = rps_key in rotation_keys
            # Handle negated pitch: look up 'pitch' and negate
            negate = rps_key == 'neg_pitch'
            actual_key = 'pitch' if negate else rps_key

            mag_matches = 0
            sign_matches = 0
            sign_flips = 0
            total = 0

            for d in all_diffs:
                mq_val = d['mq'].get(mq_key)
                rps_val = d[src].get(actual_key)
                if is_rotation and rps_val is not None:
                    rps_val = unwrap_angle(rps_val)
                if negate and rps_val is not None:
                    rps_val = -rps_val
                if mq_val is None or rps_val is None:
                    continue
                total += 1
                if abs(abs(mq_val) - abs(rps_val)) < 0.05:
                    mag_matches += 1
                if abs(mq_val) > 0.001 and abs(rps_val) > 0.001:
                    if (mq_val > 0) == (rps_val > 0):
                        sign_matches += 1
                    else:
                        sign_flips += 1

            if total == 0:
                continue

            sign_info = ""
            if sign_matches > 0 and sign_flips == 0:
                sign_info = "SAME sign"
            elif sign_flips > 0 and sign_matches == 0:
                sign_info = "FLIPPED sign"
            elif sign_matches > 0 and sign_flips > 0:
                sign_info = f"MIXED ({sign_matches} same, {sign_flips} flip)"
            else:
                sign_info = "all zero"

            print(f"  {desc:<35}  mag={mag_matches}/{total}  {sign_info}")

    print("\n  Translations:")
    analyse_pairs(axis_pairs, all_diffs)
    print("\n  Rotations (confirmed cross-axis mapping):")
    analyse_pairs(rot_pairs, all_diffs)

    # ---------------------------------------------------------------
    # Confirmed mapping summary
    # ---------------------------------------------------------------
    print(f"\n\n{'=' * 90}")
    print("CONFIRMED 6-DOF MAPPING: Mosaiq <-> RPS Clipbox")
    print("=" * 90)
    print("""
  TRANSLATIONS (cm, Clipbox values direct; CouchShift values negated):
    Mosaiq Sup/Inf    =  Clipbox longitudinal  = -CouchShiftLong
    Mosaiq Lft/Rht    =  Clipbox lateral       = -CouchShiftLat
    Mosaiq Ant/Pos    =  Clipbox vertical      = -CouchShiftHeight

  ROTATIONS (deg, Clipbox values with angle unwrap >180 -> negative):
    Mosaiq Cor(B)     =  Clipbox roll           (same sign)
    Mosaiq Sag(B)     =  Clipbox rotation       (same sign)
    Mosaiq Trans(B)   = -Clipbox pitch          (negated)

  NOTE: Rotation axes are PERMUTED between Mosaiq and XVI Clipbox.
  NOTE: CouchPitch/CouchRoll/CouchYaw are unavailable in these RPS files.

  MATRIX INFO: Each RPS contains 2 matrices:
    - OnlineToRefTransformUnMatched:   fixed coord rotation (same for all fractions)
    - OnlineToRefTransformCorrection:  includes patient-specific correction
    The Clipbox INI values are sufficient; matrix decomposition is not needed.
""")


# ===================================================================
# Main
# ===================================================================

def main():
    script_dir = Path(__file__).resolve().parent
    mosaiq_path = script_dir / "CBCT-shifts-from-mosaiq.txt"
    pat_base = REPO_ROOT / "output" / "Prostate" / "Patient Images" / "PAT01"

    # --- A: Parse Mosaiq ---
    print("Parsing Mosaiq log...")
    mosaiq_records = parse_mosaiq_log(mosaiq_path)
    print(f"  Found {len(mosaiq_records)} Mosaiq records "
          f"({sum(1 for r in mosaiq_records if r['has_shifts'])} with shifts)")
    for r in mosaiq_records:
        shifts = (f"Sup={r['sup']}, Lat={r['lat']}, Ant={r['ant']}"
                  if r['has_shifts'] else "NO SHIFTS")
        print(f"    {r['datetime']}  {shifts}")

    # --- B: Find and extract RPS files ---
    print(f"\nSearching for RPS files under {pat_base} ...")
    rps_files = find_rps_files(pat_base)
    print(f"  Found {len(rps_files)} RPS files")

    for rf in rps_files:
        print(f"\n  Extracting {rf['fx']}/{rf['cbct']}: {rf['path'].name}")
        rf['data'] = extract_rps_data(rf['path'])
        d = rf['data']
        print(f"    INI datetime:   {d['ini_datetime']}")
        print(f"    DICOM datetime: {d['dicom_datetime']}")
        cs = d['couch_shifts']
        print(f"    CouchShift:     Lat={cs.get('lateral')}, "
              f"Long={cs.get('longitudinal')}, Vert={cs.get('vertical')}")
        cb = d['clipbox']
        print(f"    Clipbox:        Lat={cb.get('lateral')}, "
              f"Long={cb.get('longitudinal')}, Vert={cb.get('vertical')}, "
              f"Rot={cb.get('rotation')}, Pitch={cb.get('pitch')}, "
              f"Roll={cb.get('roll')}")

    # --- C: Match records ---
    print("\n\nMatching RPS records to Mosaiq records...")
    matches = match_records(mosaiq_records, rps_files)

    matched = sum(1 for m in matches if m['mosaiq'] is not None)
    print(f"  {matched}/{len(matches)} RPS files matched to Mosaiq records")

    # --- D: Print comparison ---
    print_comparison(matches)


if __name__ == "__main__":
    main()
