"""Recompute archived API coverage and disagreements without credentials or requests.

This is an evidence audit, not a new evaluation or an accuracy improvement.
It uses only the standard library and never imports the API settings/adapter.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = {"recyclable", "hazardous", "kitchen", "other"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def index_unique(rows):
    indexed = {row["id"]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError("Duplicate image IDs in archived evidence.")
    return indexed


def failure_kind(result):
    metadata = result.get("metadata", {})
    if metadata.get("transport_error_type"):
        return "transport_failure", "typed_transport_diagnostic"
    # Older records predate exception-type capture. Preserve that limitation.
    error = result.get("error") or ""
    if error.startswith(("无法连接 API", "API 超时")):
        return "transport_failure", "archived_user_message_only"
    if metadata.get("http_status"):
        return "http_failure", "http_status"
    if metadata.get("validation_error_type"):
        return "output_validation_failure", "validation_diagnostic"
    return "other_failure", "unclassified"


def validate_record(row, record):
    result = record["result"]
    if row["id"] != record["id"] or result["source_sha256"] != row["sha256"]:
        raise ValueError("Image identity/hash mismatch: " + row["id"])
    if set(record["expected_categories"]) != set(row["categories"]):
        raise ValueError("Archived reference mismatch: " + row["id"])
    if result["status"] not in {"success", "error", "not_configured"}:
        raise ValueError("Unexpected archived status: " + row["id"])
    if not set(row["categories"]) <= CATEGORIES:
        raise ValueError("Unknown reference category: " + row["id"])
    if any(item.get("category") not in CATEGORIES | {None} for item in result["items"]):
        raise ValueError("Unknown prediction category: " + row["id"])
    return result


def exact_match(row, result):
    predicted = {item["category"] for item in result["items"] if item["category"] is not None}
    return result["status"] == "success" and set(row["categories"]) == predicted


def audit_records(manifest, api_records, local_records, review_issues):
    expected = index_unique(manifest)
    api = index_unique(api_records)
    local = index_unique(local_records)
    issues = index_unique(review_issues)
    if not set(api) <= set(expected) or set(local) != set(expected):
        raise ValueError("Archived predictions do not align with the frozen image set.")
    if not set(issues) <= set(expected):
        raise ValueError("Review issue is outside the frozen image set.")

    rows = []
    for image_id, row in expected.items():
        local_result = validate_record(row, local[image_id])
        entry = {"id": image_id, "reference_categories": sorted(row["categories"]),
                 "local_exact_match": exact_match(row, local_result)}
        if image_id not in api:
            entry.update(outcome="not_attempted", api_exact_match=None)
            rows.append(entry)
            continue
        result = validate_record(row, api[image_id])
        success = result["status"] == "success"
        matched = exact_match(row, result)
        metadata = result.get("metadata", {})
        entry.update(api_exact_match=matched, api_status=result["status"],
                     elapsed_seconds=result.get("elapsed_seconds"),
                     usage_returned=bool(metadata.get("usage")),
                     transport_error_type=metadata.get("transport_error_type"))
        if success:
            entry["outcome"] = "success_match" if matched else "success_disagreement"
            entry["predicted_categories"] = sorted({item["category"] for item in result["items"]
                                                     if item["category"] is not None})
            entry["normalization_actions"] = len(metadata.get("normalization", []))
            if image_id in issues:
                entry["review_issue_kind"] = issues[image_id]["kind"]
                entry["review_is_not_relabeling"] = True
        else:
            entry["outcome"], entry["failure_evidence"] = failure_kind(result)
        rows.append(entry)

    counts = Counter(row["outcome"] for row in rows)
    attempted = [row for row in rows if row["outcome"] != "not_attempted"]
    success = [row for row in attempted if row["api_status"] == "success"]
    disagreements = [row for row in success if not row["api_exact_match"]]
    return {
        "audit_kind": "offline_recomputation_of_historical_evidence",
        "generation_calls_made": 0,
        "reference_labels_changed": False,
        "new_model_quality_claimed": False,
        "planned_images": len(manifest),
        "attempted_images": len(attempted),
        "successful_images": len(success),
        "outcomes": dict(sorted(counts.items())),
        "same_attempted_subset": {
            "images": len(attempted),
            "api_exact_matches": sum(row["api_exact_match"] for row in attempted),
            "local_exact_matches": sum(row["local_exact_match"] for row in attempted),
            "failed_requests_count_as_incorrect": True,
        },
        "same_successful_subset_diagnostic_only": {
            "images": len(success),
            "api_exact_matches": sum(row["api_exact_match"] for row in success),
            "local_exact_matches": sum(row["local_exact_match"] for row in success),
        },
        "successful_disagreements_with_existing_reference_or_scope_issues":
            sum("review_issue_kind" in row for row in disagreements),
        "successful_disagreements_without_existing_review":
            sum("review_issue_kind" not in row for row in disagreements),
        "limits": [
            "Successful category-set agreement is not instance-level recognition accuracy.",
            "An ambiguity tag does not prove the model is right or alter its score.",
            "No instance-level ground truth exists here; missed/hallucinated objects cannot be counted reliably.",
            "Transport failures do not identify which hop failed or imply zero billing.",
            "Historical images already reviewed are regression evidence, not a fresh holdout.",
        ],
        "records": rows,
    }


def audit_project(root):
    holdout = root / "evidence/v0.5.0/astra-holdout"
    freeze_path = holdout / "freeze.json"
    freeze = read_json(freeze_path)
    api_paths = sorted(path for path in (holdout / "api").glob("commons-*.json")
                       if not path.name.endswith(".started.json"))
    local_path = root / freeze["local_prediction_file"]
    review_path = holdout / "quality-review.json"
    report = audit_records(freeze["images"], [read_json(path) for path in api_paths],
                           read_json(local_path)["records"], read_json(review_path)["issues"])
    report["source_sha256"] = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [freeze_path, local_path, review_path, *api_paths]
    }
    # Also verify the local baseline is exactly the artifact named in the freeze.
    if report["source_sha256"][freeze["local_prediction_file"]] != freeze["local_predictions_sha256"]:
        raise ValueError("Archived local baseline changed after the API freeze.")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional new JSON file; never overwrite existing evidence.")
    args = parser.parse_args()
    report = audit_project(ROOT)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(rendered)
        print("Offline audit written; 0 generation requests.")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
