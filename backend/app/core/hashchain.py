"""SHA-256 hash chain over canonical ledger records.

hash_n = SHA256( canonical_json( {HASHED_FIELDS of record n} ) )
where the hashed fields include ``prev_hash`` = hash_{n-1} (GENESIS_HASH for n = 1).

Canonical JSON: keys sorted, separators (",", ":"), ASCII only; Decimals are
serialised as their exact quantised string (e.g. "123.450"), None as null.

A hash chain detects modification, insertion, deletion and reordering of
records *relative to a trusted chain head*. Anyone who can rewrite the whole
database can also recompute every hash, so the head hash must be checkpointed
somewhere the attacker cannot reach (see docs/ALGORITHMS.md).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Mapping

GENESIS_HASH = "0" * 64

HASHED_FIELDS: tuple[str, ...] = (
    "seq",
    "event_id",
    "event_type",
    "job_id",
    "sim_time",
    "recorded_at",
    "energy_kwh",
    "intensity_actual",
    "intensity_baseline",
    "amount_g",
    "balance_before_g",
    "balance_after_g",
    "reference_event_id",
    "idem_key",
    "details",
    "prev_hash",
)


def _normalise(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(k): _normalise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(v) for v in value]
    if isinstance(value, float):
        # Floats are not allowed in hashed data; normalise defensively via repr.
        return repr(value)
    return value


def canonical_json(record: Mapping[str, Any]) -> str:
    payload = {name: _normalise(record.get(name)) for name in HASHED_FIELDS}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_hash(record: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(record).encode("ascii")).hexdigest()


@dataclass
class VerifyResult:
    ok: bool
    checked: int
    head_hash: str
    first_bad_seq: int | None = None
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": "VERIFIED" if self.ok else "TAMPERED",
            "checked": self.checked,
            "head_hash": self.head_hash,
            "first_bad_seq": self.first_bad_seq,
            "problems": self.problems,
        }


def verify_chain(records: Iterable[Mapping[str, Any]], expected_head: str | None = None) -> VerifyResult:
    """Verify ordering, linkage, hashes, balance continuity and duplicates."""
    prev_hash = GENESIS_HASH
    prev_balance: Decimal | None = None
    seen_idem: set[str] = set()
    problems: list[str] = []
    first_bad: int | None = None
    count = 0

    def flag(seq: int, msg: str) -> None:
        nonlocal first_bad
        problems.append(f"seq {seq}: {msg}")
        if first_bad is None:
            first_bad = seq

    for expected_seq, rec in enumerate(records, start=1):
        count += 1
        seq = int(rec["seq"])
        if seq != expected_seq:
            flag(seq, f"sequence gap or reorder (expected {expected_seq})")
        if rec["prev_hash"] != prev_hash:
            flag(seq, "prev_hash does not match previous record's hash")
        recomputed = compute_hash(rec)
        if recomputed != rec["hash"]:
            flag(seq, "stored hash does not match recomputed hash (record modified)")
        before = Decimal(str(rec["balance_before_g"]))
        after = Decimal(str(rec["balance_after_g"]))
        if prev_balance is not None and before != prev_balance:
            flag(seq, "balance_before does not equal previous balance_after")
        if before + Decimal(str(rec["amount_g"])) != after:
            flag(seq, "balance_before + amount != balance_after")
        if rec["idem_key"] in seen_idem:
            flag(seq, f"duplicate ledger event {rec['idem_key']}")
        seen_idem.add(rec["idem_key"])
        prev_hash = rec["hash"]
        prev_balance = after

    if expected_head is not None and expected_head != prev_hash:
        problems.append("chain head does not match the trusted checkpoint (records removed or rewritten)")
        if first_bad is None:
            first_bad = count
    return VerifyResult(ok=not problems, checked=count, head_hash=prev_hash, first_bad_seq=first_bad, problems=problems)
