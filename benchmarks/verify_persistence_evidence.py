"""Verify the committed scan-axis-persistence holdout evidence without scan data."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence"
FAMILIES = ("ring", "streak")
SEEDS = (104729, 130363, 169087)
BOOTSTRAP_REPETITIONS = 10_000
BOOTSTRAP_SEED = 20260720
BONFERRONI_COVERAGE = 0.975
EXPECTED_RESULT_SHA256 = "d473dd6574d8e670d8300418983334255b67fb62a3eceb51bc9ae33bbf8320c1"
EXPECTED_RECORDS_SHA256 = "b6897747fec7fbf27c7f23e6de273ac959ce2beb67e09f8be0ea7131bd03f5be"
EXPECTED_INDEPENDENT_SHA256 = "602fff22fefab9ff2a2ab4c745f0fd5341c2ce143521327d4bdf88277782a750"
EXPECTED_SELECTION_SHA256 = "951939a1073a4828922d525b880d305449240032529646072c26e22fff955376"
EXPECTED_EXCLUSIONS_SHA256 = "ed5084b05f7073de3ce6f68ee1287a9c298a562f93785accfd326515a600e0f0"
EXPECTED_CROP_MANIFEST_SHA256 = "6a2c362782a17aa81ef966d90291e31bd9131c744279532087090a6e2312fb49"
EXPECTED_ACQUISITION_SHA256 = "35ec5a3a182ec1805f3c9a0698447f3e2ee0bac479b73f647a9223603478929d"
EXPECTED_PREREGISTRATION_SHA256 = "608ee3e3fc67ab555ce3984ffd86c0a5bde51717e4abacbd0c8dcd7beec32d7c"
EXPECTED_CERTIFICATE_FILE_SHA256 = (
    "8ebc37aa06e6fee52695c6ad297b23d559e0e3bacc6de742b48679651a680f91"
)
EXPECTED_CERTIFICATE_SHA256 = "ef125249c32eb74f0853877976a382108b58ae85dbf9a4c527ea337b3e611a8f"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bootstrap_interval(values: list[float], family: str) -> list[float]:
    offset = int.from_bytes(hashlib.sha256(family.encode()).digest()[:4], "big")
    rng = random.Random((BOOTSTRAP_SEED + offset) % (2**32))
    means = sorted(
        math.fsum(values[rng.randrange(len(values))] for _ in values) / len(values)
        for _ in range(BOOTSTRAP_REPETITIONS)
    )
    tail = (1.0 - BONFERRONI_COVERAGE) / 2.0

    def quantile(probability: float) -> float:
        position = probability * (len(means) - 1)
        lower = math.floor(position)
        upper = math.ceil(position)
        fraction = position - lower
        return means[lower] * (1.0 - fraction) + means[upper] * fraction

    return [quantile(tail), quantile(1.0 - tail)]


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def verify_persistence_evidence(
    *,
    result_path: Path,
    records_path: Path,
    independent_path: Path,
    selection_path: Path,
    exclusions_path: Path,
    crop_manifest_path: Path,
    acquisition_path: Path,
    preregistration_path: Path,
    certificate_path: Path,
) -> dict[str, Any]:
    """Reconstruct the primary statistics and validate every committed hash link."""

    result = json.loads(result_path.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
    independent = json.loads(independent_path.read_text(encoding="utf-8"))
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    crop_manifest = json.loads(crop_manifest_path.read_text(encoding="utf-8"))
    acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
    certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    expected_file_hashes = {
        result_path: EXPECTED_RESULT_SHA256,
        records_path: EXPECTED_RECORDS_SHA256,
        independent_path: EXPECTED_INDEPENDENT_SHA256,
        selection_path: EXPECTED_SELECTION_SHA256,
        exclusions_path: EXPECTED_EXCLUSIONS_SHA256,
        crop_manifest_path: EXPECTED_CROP_MANIFEST_SHA256,
        acquisition_path: EXPECTED_ACQUISITION_SHA256,
        preregistration_path: EXPECTED_PREREGISTRATION_SHA256,
        certificate_path: EXPECTED_CERTIFICATE_FILE_SHA256,
    }
    for path, expected in expected_file_hashes.items():
        _require(sha256_file(path) == expected, f"SHA-256 mismatch: {path.name}", errors)

    _require(
        result.get("schema") == "layerlens-persistence-holdout-v1",
        "result schema changed",
        errors,
    )
    _require(
        result.get("candidate_commit") == "415131c2fdcf2dbd2e9e45efefbfa5ed003ef147",
        "candidate commit changed",
        errors,
    )
    parameters = result.get("parameters", {})
    _require(parameters.get("families") == list(FAMILIES), "families changed", errors)
    _require(parameters.get("seeds") == list(SEEDS), "seeds changed", errors)
    _require(parameters.get("severity") == 0.2, "severity changed", errors)
    _require(
        parameters.get("bootstrap_repetitions") == BOOTSTRAP_REPETITIONS,
        "bootstrap repetition count changed",
        errors,
    )
    _require(parameters.get("bootstrap_seed") == BOOTSTRAP_SEED, "bootstrap seed changed", errors)
    _require(
        parameters.get("bonferroni_coverage") == BONFERRONI_COVERAGE,
        "bootstrap coverage changed",
        errors,
    )

    sample_ids = [str(value) for value in result.get("sample_ids", [])]
    selected_ids = [str(entry["sample"]) for entry in selection.get("samples", [])]
    crop_ids = [str(entry["sample"]) for entry in crop_manifest.get("samples", [])]
    acquisition_ids = [str(entry["sample"]) for entry in acquisition.get("samples", [])]
    _require(
        len(sample_ids) == 24 and len(set(sample_ids)) == 24,
        "sample design is not 24 unique cubes",
        errors,
    )
    _require(
        sample_ids == selected_ids == crop_ids == acquisition_ids,
        "selection, acquisition, crop, and result orders differ",
        errors,
    )
    _require(acquisition.get("state") == "ready", "acquisition was not complete", errors)
    _require(
        acquisition.get("total_bytes") == 1_412_450_473,
        "acquisition byte total changed",
        errors,
    )
    _require(
        crop_manifest.get("source_manifest_sha256") == EXPECTED_SELECTION_SHA256,
        "crop manifest does not point to the frozen selection",
        errors,
    )
    _require(
        crop_manifest.get("crop_size") == 64 and crop_manifest.get("search_step") == 32,
        "crop contract changed",
        errors,
    )

    expected_keys = {
        (sample, family, seed) for sample in sample_ids for family in FAMILIES for seed in SEEDS
    }
    actual_keys = {(str(row["sample"]), str(row["family"]), int(row["seed"])) for row in rows}
    _require(len(rows) == 144 and actual_keys == expected_keys, "record design changed", errors)
    _require(
        sha256_file(records_path) == result.get("records_sha256"),
        "result-to-records hash link failed",
        errors,
    )
    provenance = result.get("provenance", {})
    _require(
        provenance.get("selection_sha256") == sha256_file(selection_path),
        "selection provenance changed",
        errors,
    )
    _require(
        provenance.get("exclusions_sha256") == sha256_file(exclusions_path),
        "exclusion provenance changed",
        errors,
    )
    _require(
        provenance.get("crop_manifest_sha256") == sha256_file(crop_manifest_path),
        "crop provenance changed",
        errors,
    )

    reconstructed: dict[str, list[float]] = {}
    independent_intervals: dict[str, list[float]] = {}
    for family in FAMILIES:
        values: list[float] = []
        for sample in sorted(sample_ids):
            selected = [row for row in rows if row["family"] == family and row["sample"] == sample]
            _require(len(selected) == len(SEEDS), f"wrong seed count: {sample}/{family}", errors)
            for row in selected:
                delta = float(row["corrupted_persistence"]) - float(row["clean_persistence"])
                _require(
                    math.isclose(
                        delta,
                        float(row["persistence_delta"]),
                        rel_tol=0.0,
                        abs_tol=1e-15,
                    ),
                    f"delta arithmetic mismatch: {sample}/{family}",
                    errors,
                )
            values.append(
                math.fsum(float(row["persistence_delta"]) for row in selected) / len(SEEDS)
            )
        reconstructed[family] = values
        reported = result["results"][family]
        _require(all(value > 0.0 for value in values), f"{family} is not 24/24 positive", errors)
        _require(
            reported.get("positive_cube_fraction") == 1.0, f"{family} fraction changed", errors
        )
        _require(reported.get("passed") is True, f"{family} primary gate failed", errors)
        _require(
            reported["bootstrap_bonferroni_ci"][0] > 0.0,
            f"{family} primary lower endpoint is not positive",
            errors,
        )
        reported_values = [float(value) for value in reported["cube_mean_persistence_deltas"]]
        _require(
            len(values) == len(reported_values)
            and all(
                math.isclose(a, b, rel_tol=0.0, abs_tol=1e-15)
                for a, b in zip(values, reported_values, strict=True)
            ),
            f"{family} cube means changed",
            errors,
        )
        interval = _bootstrap_interval(values, family)
        independent_intervals[family] = interval
        expected_interval = independent["independent_bootstrap"][family]["pure_python_interval"]
        _require(
            all(
                math.isclose(a, float(b), rel_tol=0.0, abs_tol=1e-15)
                for a, b in zip(interval, expected_interval, strict=True)
            ),
            f"{family} independent bootstrap changed",
            errors,
        )
        _require(interval[0] > 0.0, f"{family} independent lower endpoint failed", errors)

    legacy = result.get("legacy_preservation", {})
    _require(
        legacy.get("passed") is True
        and legacy.get("comparisons") == 168
        and legacy.get("errors") == [],
        "legacy preservation failed",
        errors,
    )
    _require(result.get("decision", {}).get("passed") is True, "primary decision failed", errors)
    _require(independent.get("integrity_passed") is True, "independent verifier failed", errors)
    _require(independent.get("errors") == [], "independent verifier reported errors", errors)
    _require(
        independent.get("source_result_sha256") == sha256_file(result_path),
        "independent result hash link failed",
        errors,
    )
    _require(
        independent.get("source_records_sha256") == sha256_file(records_path),
        "independent records hash link failed",
        errors,
    )
    for metric in ("numpy_finite_difference_box", "scipy_gaussian_derivative_box"):
        for family in FAMILIES:
            check = independent["alternate_metrics"][metric][family]
            _require(
                check.get("positive_cube_fraction") == 1.0,
                f"{metric}/{family} is not 24/24 positive",
                errors,
            )
            _require(
                check.get("bonferroni_t_lower", 0.0) > 0.0,
                f"{metric}/{family} lower endpoint is not positive",
                errors,
            )

    claim = certificate.get("claim", {})
    _require(
        certificate.get("schema_version") == 1
        and certificate.get("certificate_type") == "proof-carrying-claim",
        "claim certificate schema changed",
        errors,
    )
    _require(
        certificate.get("certificate_sha256") == EXPECTED_CERTIFICATE_SHA256,
        "claim certificate content digest changed",
        errors,
    )
    _require(
        claim.get("claim_id") == "C-persistence-holdout"
        and claim.get("state") == "replicated"
        and claim.get("target_state") == "verified"
        and claim.get("target_satisfied") is True,
        "claim certificate is not replicated and verified",
        errors,
    )
    certificate_data_hashes = {
        str(entry.get("sha256")) for entry in certificate.get("digests", {}).get("data", [])
    }
    for expected_hash in (
        EXPECTED_RESULT_SHA256,
        EXPECTED_RECORDS_SHA256,
        EXPECTED_INDEPENDENT_SHA256,
        EXPECTED_PREREGISTRATION_SHA256,
    ):
        _require(
            expected_hash in certificate_data_hashes,
            f"claim certificate does not bind evidence {expected_hash}",
            errors,
        )
    verification_by_kind = {
        str(entry.get("kind")): entry
        for entry in certificate.get("verification", {}).get("evidence", [])
    }
    for kind in ("independent_verifier", "clean_reproduction"):
        verification = verification_by_kind.get(kind, {})
        _require(verification.get("exit_code") == 0, f"{kind} did not pass", errors)
        policy = verification.get("escrow_policy", verification.get("reproduction_policy", {}))
        _require(
            policy.get("network") is False and policy.get("subprocess") is False,
            f"{kind} isolation policy changed",
            errors,
        )

    return {
        "schema": "layerlens-persistence-evidence-verification-v1",
        "passed": not errors,
        "errors": errors,
        "candidate_commit": result.get("candidate_commit"),
        "cubes": len(sample_ids),
        "legacy_comparisons": legacy.get("comparisons"),
        "means": {
            family: math.fsum(values) / len(values) for family, values in reconstructed.items()
        },
        "independent_bootstrap_intervals": independent_intervals,
        "interpretation_limit": result.get("interpretation_limit"),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--result",
        type=Path,
        default=EVIDENCE / "persistence_holdout_report.json",
    )
    parser.add_argument(
        "--records",
        type=Path,
        default=EVIDENCE / "persistence_holdout_records.jsonl",
    )
    parser.add_argument(
        "--independent",
        type=Path,
        default=EVIDENCE / "persistence_holdout_independent_verification.json",
    )
    parser.add_argument(
        "--selection",
        type=Path,
        default=EVIDENCE / "persistence_holdout_selection.json",
    )
    parser.add_argument(
        "--exclusions",
        type=Path,
        default=EVIDENCE / "persistence_holdout_exclusions.txt",
    )
    parser.add_argument(
        "--crop-manifest",
        type=Path,
        default=EVIDENCE / "persistence_holdout_crop_manifest.json",
    )
    parser.add_argument(
        "--acquisition",
        type=Path,
        default=EVIDENCE / "persistence_holdout_acquisition_manifest.json",
    )
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=EVIDENCE / "persistence_holdout_preregistration.md",
    )
    parser.add_argument(
        "--certificate",
        type=Path,
        default=EVIDENCE / "persistence_holdout_claim_certificate.json",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    payload = verify_persistence_evidence(
        result_path=args.result,
        records_path=args.records,
        independent_path=args.independent,
        selection_path=args.selection,
        exclusions_path=args.exclusions,
        crop_manifest_path=args.crop_manifest,
        acquisition_path=args.acquisition,
        preregistration_path=args.preregistration,
        certificate_path=args.certificate,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    raise SystemExit(0 if payload["passed"] else 1)


if __name__ == "__main__":
    main()
