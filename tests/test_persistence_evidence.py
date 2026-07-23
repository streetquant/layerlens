from __future__ import annotations

from benchmarks.verify_persistence_evidence import EVIDENCE, verify_persistence_evidence


def test_committed_persistence_holdout_evidence() -> None:
    result = verify_persistence_evidence(
        result_path=EVIDENCE / "persistence_holdout_report.json",
        records_path=EVIDENCE / "persistence_holdout_records.jsonl",
        independent_path=EVIDENCE / "persistence_holdout_independent_verification.json",
        selection_path=EVIDENCE / "persistence_holdout_selection.json",
        exclusions_path=EVIDENCE / "persistence_holdout_exclusions.txt",
        crop_manifest_path=EVIDENCE / "persistence_holdout_crop_manifest.json",
        acquisition_path=EVIDENCE / "persistence_holdout_acquisition_manifest.json",
        preregistration_path=EVIDENCE / "persistence_holdout_preregistration.md",
        certificate_path=EVIDENCE / "persistence_holdout_claim_certificate.json",
    )

    assert result["passed"] is True
    assert result["errors"] == []
    assert result["cubes"] == 24
    assert result["legacy_comparisons"] == 168
