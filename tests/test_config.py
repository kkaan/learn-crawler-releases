"""Tests for learn_upload.config."""

import pytest

from learn_upload.config import check_patient_mrn, make_anon_id, validate_config


def _valid_config(**overrides) -> dict:
    cfg = {
        "anon_id": "PAT01",
        "redcap_id": "LEARN_001",
        "patient_mrn": "258413",
        "site_name": "Prostate",
        "source_path": r"C:\data\patient_12345678",
        "output_path": r"C:\out",
    }
    cfg.update(overrides)
    return cfg


class TestMakeAnonId:
    def test_pads_to_two_digits(self):
        assert make_anon_id(1) == "PAT01"
        assert make_anon_id(12) == "PAT12"


class TestValidateConfig:
    def test_accepts_a_complete_config(self):
        assert validate_config(_valid_config()) is None

    def test_requires_redcap_id(self):
        error = validate_config(_valid_config(redcap_id=""))
        assert error == "REDCap ID is required."

    def test_accepts_any_redcap_id_format(self):
        assert validate_config(_valid_config(redcap_id="42")) is None

    @pytest.mark.parametrize(
        "field, expected",
        [
            ("anon_id", "Anonymised ID is required."),
            ("site_name", "Site Name is required."),
            ("source_path", "Source Path is required."),
            ("output_path", "Output Path is required."),
        ],
    )
    def test_requires_each_mandatory_field(self, field, expected):
        assert validate_config(_valid_config(**{field: ""})) == expected

    def test_rejects_malformed_anon_id(self):
        error = validate_config(_valid_config(anon_id="PATIENT1"))
        assert error == "Anon ID must match PATxx format (e.g. PAT01)."

    def test_tolerates_missing_keys(self):
        assert validate_config({}) == "Anonymised ID is required."


class TestValidateConfigMrn:
    def test_requires_patient_mrn(self):
        assert validate_config(_valid_config(patient_mrn="")) == "Patient MRN is required."


class TestCheckPatientMrn:
    def test_match_when_entered_equals_the_only_export_id(self):
        check = check_patient_mrn("258413", {"258413": ["img_1.1"]})
        assert check.status == "match"
        assert check.export_id == "258413"

    def test_mismatch_when_entered_differs(self):
        check = check_patient_mrn("258431", {"258413": ["img_1.1"]})
        assert check.status == "mismatch"
        assert check.entered == "258431"
        assert check.export_id == "258413"

    def test_not_found_when_export_yields_no_id(self):
        check = check_patient_mrn("258413", {})
        assert check.status == "not_found"
        assert check.export_id is None

    def test_conflicting_when_export_sessions_disagree(self):
        check = check_patient_mrn("258413", {"258413": ["img_1.1"], "999999": ["img_1.2"]})
        assert check.status == "conflicting_export"
        assert sorted(check.export_ids) == ["258413", "999999"]
        assert check.export_id is None

    def test_ignores_surrounding_whitespace(self):
        assert check_patient_mrn(" 258413 ", {"258413": ["img_1.1"]}).status == "match"

    def test_is_case_insensitive_for_alphanumeric_ids(self):
        assert check_patient_mrn("ab123", {"AB123": ["img_1.1"]}).status == "match"
