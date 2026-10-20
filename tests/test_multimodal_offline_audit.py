"""Evidence audits must not inflate scores or contact model services."""
from copy import deepcopy
from pathlib import Path
import socket

import pytest

from scripts.audit_multimodal_offline import audit_project, audit_records


def fixture_records():
    manifest = [
        {"id": "one", "sha256": "hash-one", "categories": ["other"]},
        {"id": "two", "sha256": "hash-two", "categories": []},
        {"id": "three", "sha256": "hash-three", "categories": []},
    ]
    local = [{"id": row["id"], "expected_categories": row["categories"], "result": {
        "source_sha256": row["sha256"], "status": "success",
        "items": [{"category": category} for category in row["categories"]]}}
        for row in manifest]
    api = deepcopy(local[:2])
    api[0]["result"]["items"] = [{"category": "recyclable"}]
    api[1]["result"].update(status="error", error="无法连接 API，请检查网络与 HTTPS 端点。")
    return manifest, api, local


def test_failed_empty_reference_and_unsubmitted_are_not_successes():
    manifest, api, local = fixture_records()
    report = audit_records(manifest, api, local, [{"id": "one", "kind": "scope ambiguity"}])
    assert report["attempted_images"] == 2
    assert report["successful_images"] == 1
    assert report["same_attempted_subset"]["api_exact_matches"] == 0
    assert report["outcomes"] == {"not_attempted": 1, "success_disagreement": 1, "transport_failure": 1}
    assert report["successful_disagreements_with_existing_reference_or_scope_issues"] == 1
    assert report["records"][1]["failure_evidence"] == "archived_user_message_only"
    assert report["records"][2]["api_exact_match"] is None


def test_reject_changed_hash_or_duplicate_records():
    manifest, api, local = fixture_records()
    api[0]["result"]["source_sha256"] = "changed"
    with pytest.raises(ValueError, match="hash mismatch"):
        audit_records(manifest, api, local, [])
    manifest, api, local = fixture_records()
    with pytest.raises(ValueError, match="Duplicate"):
        audit_records(manifest, api + [api[0]], local, [])


def test_real_archived_evidence_reproduces_counts_without_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline audit must never open a network socket.")
    monkeypatch.setattr(socket, "socket", forbidden)
    root = Path(__file__).resolve().parents[1]
    report = audit_project(root)
    assert report["planned_images"] == 40
    assert report["attempted_images"] == 38
    assert report["successful_images"] == 33
    assert report["outcomes"] == {"not_attempted": 2, "success_disagreement": 5,
                                  "success_match": 28, "transport_failure": 5}
    assert report["same_attempted_subset"]["local_exact_matches"] == 32
    assert report["same_successful_subset_diagnostic_only"]["local_exact_matches"] == 28
    assert report["successful_disagreements_with_existing_reference_or_scope_issues"] == 5
    assert report["generation_calls_made"] == 0
