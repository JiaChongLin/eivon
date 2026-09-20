from scripts.stress_leases import run_stress


def test_concurrent_claims_are_unique_and_stale_leases_are_fenced(tmp_path):
    report = run_stress(tmp_path, count=96, workers=8)

    assert report["claims"] == report["runs"] == 96
    assert report["unique_claims"] == report["runs"]
    assert report["duplicate_claims"] == 0
    assert report["errors"] == []
    assert report["statuses_after_claim"] == {"running": 96}
    assert report["fencing"] == {
        "stale_claim_rejected": True,
        "old_heartbeat_rejected": True,
        "old_finish_rejected": True,
        "stale_run_terminal_status": "failed",
    }
