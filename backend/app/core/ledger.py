"""Append-only carbon debt ledger (in-memory book; persisted by the service layer)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from .hashchain import GENESIS_HASH, compute_hash
from .units import ZERO, q_g


class EventType:
    DEBT_INCURRED = "DEBT_INCURRED"
    DEFERRAL_RECORDED = "DEFERRAL_RECORDED"
    CREDIT_VERIFIED = "CREDIT_VERIFIED"
    CREDIT_DENIED = "CREDIT_DENIED"
    DEBT_CLEARED = "DEBT_CLEARED"


class DuplicateLedgerEvent(ValueError):
    pass


@dataclass
class LedgerRecord:
    seq: int
    event_id: str
    event_type: str
    job_id: str | None
    sim_time: str
    recorded_at: str
    energy_kwh: Decimal | None
    intensity_actual: Decimal | None
    intensity_baseline: Decimal | None
    amount_g: Decimal
    balance_before_g: Decimal
    balance_after_g: Decimal
    reference_event_id: str | None
    idem_key: str
    details: dict[str, Any]
    prev_hash: str
    hash: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LedgerBook:
    """Balance-carrying, idempotent, hash-chained ledger.

    Balance policy:
      * DEBT_INCURRED adds the debt.
      * CREDIT_VERIFIED subtracts min(credit, outstanding). Any surplus is recorded
        but NOT banked: past green work cannot pre-pay future emergencies.
      * The balance therefore never goes below zero; when it reaches zero from a
        positive value a DEBT_CLEARED event is appended and priority inversion ends.
    """

    last_seq: int = 0
    last_hash: str = GENESIS_HASH
    balance_g: Decimal = ZERO
    total_debt_g: Decimal = ZERO
    total_credit_applied_g: Decimal = ZERO
    total_credit_earned_g: Decimal = ZERO
    idem_keys: set[str] = field(default_factory=set)
    new_records: list[LedgerRecord] = field(default_factory=list)

    def append(
        self,
        *,
        event_type: str,
        idem_key: str,
        sim_time: str,
        recorded_at: str,
        job_id: str | None = None,
        amount_g: Decimal = ZERO,
        energy_kwh: Decimal | None = None,
        intensity_actual: Decimal | None = None,
        intensity_baseline: Decimal | None = None,
        reference_event_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> LedgerRecord:
        if idem_key in self.idem_keys:
            raise DuplicateLedgerEvent(f"ledger event {idem_key} already recorded")
        before = self.balance_g
        amount = q_g(amount_g)
        if amount == ZERO:
            amount = abs(amount)  # normalise -0.000 so stored values read naturally
        after = q_g(before + amount)
        if after < ZERO:
            raise ValueError("ledger balance may not become negative (over-crediting)")
        seq = self.last_seq + 1
        record = LedgerRecord(
            seq=seq,
            event_id=f"LE-{seq:06d}",
            event_type=event_type,
            job_id=job_id,
            sim_time=sim_time,
            recorded_at=recorded_at,
            energy_kwh=energy_kwh,
            intensity_actual=intensity_actual,
            intensity_baseline=intensity_baseline,
            amount_g=amount,
            balance_before_g=before,
            balance_after_g=after,
            reference_event_id=reference_event_id,
            idem_key=idem_key,
            details=details or {},
            prev_hash=self.last_hash,
        )
        record.hash = compute_hash(record.as_dict())
        self.last_seq = seq
        self.last_hash = record.hash
        self.balance_g = after
        self.idem_keys.add(idem_key)
        if event_type == EventType.DEBT_INCURRED:
            self.total_debt_g = q_g(self.total_debt_g + amount)
        elif event_type == EventType.CREDIT_VERIFIED:
            self.total_credit_applied_g = q_g(self.total_credit_applied_g - amount)
            self.total_credit_earned_g = q_g(
                self.total_credit_earned_g + Decimal(str(record.details.get("credit_earned_g", "0")))
            )
        self.new_records.append(record)
        return record
