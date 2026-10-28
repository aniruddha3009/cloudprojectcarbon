from decimal import Decimal

import pytest

from app.core.hashchain import GENESIS_HASH, canonical_json, compute_hash, verify_chain
from app.core.ledger import DuplicateLedgerEvent, EventType, LedgerBook


def build_book() -> LedgerBook:
    book = LedgerBook()
    common = {"sim_time": "2026-01-01T07:00:00Z", "recorded_at": "2026-01-01T07:00:00Z"}
    book.append(event_type=EventType.DEFERRAL_RECORDED, idem_key="DEFERRAL:J-2", job_id="J-2",
                intensity_baseline=Decimal("620.00"), **common)
    book.append(event_type=EventType.DEBT_INCURRED, idem_key="DEBT:J-1", job_id="J-1",
                amount_g=Decimal("400"), **common)
    book.append(event_type=EventType.CREDIT_VERIFIED, idem_key="CREDIT:J-2", job_id="J-2",
                amount_g=Decimal("-250"), reference_event_id="LE-000001",
                details={"credit_earned_g": "250.000"}, **common)
    return book


def records(book: LedgerBook) -> list[dict]:
    return [r.as_dict() for r in book.new_records]


def test_chain_links_and_verifies():
    book = build_book()
    recs = records(book)
    assert recs[0]["prev_hash"] == GENESIS_HASH
    assert all(recs[i]["prev_hash"] == recs[i - 1]["hash"] for i in range(1, len(recs)))
    result = verify_chain(recs)
    assert result.ok and result.checked == 3 and result.head_hash == recs[-1]["hash"]
    assert book.balance_g == Decimal("150.000")
    assert book.total_debt_g == Decimal("400.000") and book.total_credit_applied_g == Decimal("250.000")


def test_hash_is_deterministic_and_canonical():
    rec = records(build_book())[1]
    assert compute_hash(rec) == rec["hash"]
    assert canonical_json(rec) == canonical_json(dict(reversed(list(rec.items()))))


@pytest.mark.parametrize("mutate", [
    lambda r: r[1].__setitem__("amount_g", Decimal("100.000")),
    lambda r: r[1].__setitem__("job_id", "J-9"),
    lambda r: r[2]["details"].__setitem__("credit_earned_g", "999"),
    lambda r: r.pop(1),
    lambda r: r.insert(0, r.pop(2)),
])
def test_tampering_detected(mutate):
    recs = records(build_book())
    mutate(recs)
    assert not verify_chain(recs).ok


def test_truncation_detected_with_trusted_head():
    recs = records(build_book())
    head = recs[-1]["hash"]
    assert verify_chain(recs[:-1]).ok  # undetectable without a checkpoint …
    assert not verify_chain(recs[:-1], expected_head=head).ok  # … detected against the trusted head


def test_duplicate_events_rejected():
    book = build_book()
    with pytest.raises(DuplicateLedgerEvent):
        book.append(event_type=EventType.DEBT_INCURRED, idem_key="DEBT:J-1", sim_time="x", recorded_at="x",
                    amount_g=Decimal("1"))


def test_balance_cannot_go_negative():
    book = LedgerBook()
    with pytest.raises(ValueError):
        book.append(event_type=EventType.CREDIT_VERIFIED, idem_key="CREDIT:J", sim_time="x", recorded_at="x",
                    amount_g=Decimal("-1"))


def test_duplicate_idem_key_in_records_detected():
    recs = records(build_book())
    recs[2]["idem_key"] = "DEBT:J-1"
    recs[2]["hash"] = compute_hash(recs[2])
    result = verify_chain(recs)
    assert not result.ok and any("duplicate" in p for p in result.problems)
