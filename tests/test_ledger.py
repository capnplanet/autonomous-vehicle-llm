from autonomy.ledger import CommandLedger


def test_command_ledger_nonce_tracking_and_events(tmp_path):
    db_path = tmp_path / "ledger.db"
    ledger = CommandLedger(str(db_path))

    assert ledger.get_last_ack_nonce("veh-1") is None
    ledger.update_last_ack_nonce("veh-1", 10)
    assert ledger.get_last_ack_nonce("veh-1") == 10

    ledger.append_command_event(
        vehicle_id="veh-1",
        command_id="cmd-1",
        idempotency_key="idem-1",
        status="ack_ok",
        detail="ok",
    )


def test_command_ledger_idempotency_ttl(tmp_path):
    db_path = tmp_path / "ledger.db"
    ledger = CommandLedger(str(db_path))

    key = "idem-123"
    assert ledger.is_duplicate_idempotency_key(key) is False
    ledger.mark_idempotency_key(key, ttl_s=60)
    assert ledger.is_duplicate_idempotency_key(key) is True
