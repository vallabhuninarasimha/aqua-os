"""Repository for recording and auditing farm expenses with tenant isolation and double-counting safeguards."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from apps.api.src.infrastructure.models import FarmExpenseORM, PondORM, StockingBatchORM


VALID_EXPENSE_CATEGORIES = {
    "SEED_PL",
    "CHEMICAL_AND_TREATMENT",
    "ELECTRICITY_ENERGY",
    "LABOUR",
    "MAINTENANCE_REPAIR",
    "FEED",
    "OTHER",
}


class SQLExpenseRepository:
    """Repository handling farm expense ledger entries, audited corrections, and batch attributions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _to_dict(self, e: FarmExpenseORM) -> Dict[str, Any]:
        return {
            "id": e.id,
            "expense_id": e.expense_id,
            "farm_id": e.farm_id,
            "pond_id": e.pond_id,
            "batch_id": e.batch_id,
            "category": e.category,
            "amount": e.amount,
            "currency": e.currency,
            "transaction_date": e.transaction_date.isoformat() if e.transaction_date else None,
            "supplier": e.supplier,
            "invoice_number": e.invoice_number,
            "payment_method": e.payment_method,
            "idempotency_key": e.idempotency_key,
            "status": e.status,
            "correction_type": e.correction_type,
            "corrected_expense_id": e.corrected_expense_id,
            "correction_reason": e.correction_reason,
            "notes": e.notes,
            "recorded_by": e.recorded_by,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "updated_at": e.updated_at.isoformat() if e.updated_at else None,
        }

    def record_expense(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Record a validated farm expense with duplicate safeguards and tenant isolation."""
        farm_id = data.get("farm_id")
        if not farm_id:
            raise ValueError("farm_id is required.")

        category = str(data.get("category", "")).upper()
        if category not in VALID_EXPENSE_CATEGORIES:
            raise ValueError(f"Invalid category '{category}'. Must be one of {sorted(VALID_EXPENSE_CATEGORIES)}")

        amount = float(data.get("amount", 0.0))
        if amount <= 0:
            raise ValueError("Expense amount must be strictly greater than 0.")

        # Idempotency safeguard (farm-scoped)
        idem_key = data.get("idempotency_key")
        if idem_key and str(idem_key).strip():
            idem_key = str(idem_key).strip()
            existing = (
                self._session.query(FarmExpenseORM)
                .filter(FarmExpenseORM.farm_id == farm_id, FarmExpenseORM.idempotency_key == idem_key)
                .first()
            )
            if existing:
                return self._to_dict(existing)
        else:
            idem_key = None

        # Duplicate invoice detection (case-insensitive, trimmed, active only)
        inv_no = data.get("invoice_number")
        supplier = data.get("supplier")
        clean_inv = str(inv_no).strip() if inv_no and str(inv_no).strip() else None
        clean_sup = str(supplier).strip() if supplier and str(supplier).strip() else None
        if clean_inv and clean_sup:
            dup = (
                self._session.query(FarmExpenseORM)
                .filter(
                    FarmExpenseORM.farm_id == farm_id,
                    func.lower(FarmExpenseORM.invoice_number) == clean_inv.lower(),
                    func.lower(FarmExpenseORM.supplier) == clean_sup.lower(),
                    FarmExpenseORM.status == "ACTIVE",
                )
                .first()
            )
            if dup:
                raise ValueError(
                    f"Duplicate expense detected: active invoice '{clean_inv}' from supplier '{clean_sup}' "
                    f"is already recorded as {dup.expense_id}."
                )

        # Attribution validation against tenant farm
        pond_id = data.get("pond_id")
        batch_id = data.get("batch_id")

        if pond_id:
            pond = (
                self._session.query(PondORM)
                .filter(PondORM.farm_id == farm_id, PondORM.pond_id == pond_id)
                .first()
            )
            if not pond:
                raise ValueError(f"Pond '{pond_id}' not found for farm '{farm_id}'.")

        if batch_id:
            # Prevent feed expense double-counting against feeding logs
            if category == "FEED":
                raise ValueError(
                    "Direct FEED purchase expenses cannot be attributed to an individual batch. "
                    "Batch feed costs are derived from physical daily feeding logs and feed inventory stock receipts to prevent double-counting."
                )

            batch = (
                self._session.query(StockingBatchORM)
                .filter(StockingBatchORM.batch_id == batch_id)
                .first()
            )
            if not batch:
                raise ValueError(f"Batch '{batch_id}' not found.")
            if batch.farm_id != farm_id:
                raise ValueError(f"Batch '{batch_id}' belongs to farm '{batch.farm_id}', not '{farm_id}'.")
            if pond_id and batch.pond_id != pond_id:
                raise ValueError(f"Batch '{batch_id}' belongs to pond '{batch.pond_id}', not '{pond_id}'.")
            if not pond_id:
                pond_id = batch.pond_id

        # Parse transaction date
        tx_dt = data.get("transaction_date")
        if isinstance(tx_dt, str):
            tx_dt = datetime.fromisoformat(tx_dt.replace("Z", "+00:00"))
        elif not isinstance(tx_dt, datetime):
            tx_dt = datetime.now(timezone.utc)
        if tx_dt.tzinfo is None:
            tx_dt = tx_dt.replace(tzinfo=timezone.utc)

        expense_id = data.get("expense_id") or f"exp-{uuid.uuid4().hex[:8]}"

        notes = (data.get("notes") or "").strip()
        if category == "FEED":
            feed_warning = "[FEED INVENTORY ADVISORY]: Direct expense entry for feed. Note: feed inventory stock receipts are the primary ledger for batch consumption costing."
            notes = f"{feed_warning} {notes}".strip()

        orm_expense = FarmExpenseORM(
            expense_id=expense_id,
            farm_id=farm_id,
            pond_id=pond_id,
            batch_id=batch_id,
            category=category,
            amount=round(amount, 2),
            currency=data.get("currency", "USD"),
            transaction_date=tx_dt,
            supplier=clean_sup,
            invoice_number=clean_inv,
            payment_method=data.get("payment_method"),
            idempotency_key=idem_key,
            status="ACTIVE",
            correction_type="ORIGINAL",
            notes=notes if notes else None,
            recorded_by=data.get("recorded_by", "system"),
        )

        try:
            self._session.add(orm_expense)
            self._session.commit()
            self._session.refresh(orm_expense)
            return self._to_dict(orm_expense)
        except Exception:
            self._session.rollback()
            raise

    def correct_expense(
        self,
        expense_id: str,
        farm_id: str,
        correction_data: Dict[str, Any],
        recorded_by: str,
    ) -> Dict[str, Any]:
        """Perform an audited, non-destructive correction of an active expense."""
        original = (
            self._session.query(FarmExpenseORM)
            .filter(FarmExpenseORM.expense_id == expense_id, FarmExpenseORM.farm_id == farm_id)
            .first()
        )
        if not original:
            raise ValueError(f"Expense '{expense_id}' not found.")
        if original.status != "ACTIVE":
            raise ValueError(f"Cannot correct inactive expense '{expense_id}' (status: {original.status}).")

        reason = correction_data.get("correction_reason")
        if not reason or not str(reason).strip():
            raise ValueError("correction_reason is required for audited expense corrections.")

        # Validate category if modified
        new_category = str(correction_data.get("category", original.category)).upper()
        if new_category not in VALID_EXPENSE_CATEGORIES:
            raise ValueError(f"Invalid category '{new_category}'.")

        new_amount = float(correction_data.get("amount", original.amount))
        if new_amount <= 0:
            raise ValueError("Corrected amount must be greater than 0.")

        # Validate batch and pond attribution if modified
        new_batch_id = correction_data.get("batch_id", original.batch_id)
        new_pond_id = correction_data.get("pond_id", original.pond_id)

        if new_pond_id:
            pond = (
                self._session.query(PondORM)
                .filter(PondORM.farm_id == farm_id, PondORM.pond_id == new_pond_id)
                .first()
            )
            if not pond:
                raise ValueError(f"Pond '{new_pond_id}' not found for farm '{farm_id}'.")

        if new_batch_id:
            if new_category == "FEED":
                raise ValueError(
                    "Direct FEED purchase expenses cannot be attributed to an individual batch. "
                    "Batch feed costs are derived from physical daily feeding logs and feed inventory stock receipts to prevent double-counting."
                )
            batch = (
                self._session.query(StockingBatchORM)
                .filter(StockingBatchORM.batch_id == new_batch_id)
                .first()
            )
            if not batch or batch.farm_id != farm_id:
                raise ValueError(f"Batch '{new_batch_id}' is invalid for this farm.")
            if not new_pond_id:
                new_pond_id = batch.pond_id
            elif batch.pond_id != new_pond_id:
                raise ValueError(f"Batch '{new_batch_id}' belongs to pond '{batch.pond_id}', not '{new_pond_id}'.")

        # Duplicate invoice check for corrected invoice/supplier against other active expenses
        new_inv = correction_data.get("invoice_number", original.invoice_number)
        new_sup = correction_data.get("supplier", original.supplier)
        clean_inv = str(new_inv).strip() if new_inv and str(new_inv).strip() else None
        clean_sup = str(new_sup).strip() if new_sup and str(new_sup).strip() else None
        if clean_inv and clean_sup:
            dup = (
                self._session.query(FarmExpenseORM)
                .filter(
                    FarmExpenseORM.farm_id == farm_id,
                    FarmExpenseORM.expense_id != original.expense_id,
                    func.lower(FarmExpenseORM.invoice_number) == clean_inv.lower(),
                    func.lower(FarmExpenseORM.supplier) == clean_sup.lower(),
                    FarmExpenseORM.status == "ACTIVE",
                )
                .first()
            )
            if dup:
                raise ValueError(
                    f"Duplicate invoice detected: active invoice '{clean_inv}' from supplier '{clean_sup}' "
                    f"is already in use by active expense {dup.expense_id}."
                )

        # Parse transaction date if modified
        tx_dt = correction_data.get("transaction_date")
        if tx_dt:
            if isinstance(tx_dt, str):
                tx_dt = datetime.fromisoformat(tx_dt.replace("Z", "+00:00"))
            if tx_dt.tzinfo is None:
                tx_dt = tx_dt.replace(tzinfo=timezone.utc)
        else:
            tx_dt = original.transaction_date

        # Update original to CORRECTED state
        original.status = "CORRECTED"
        original.correction_reason = str(reason).strip()
        original.updated_at = datetime.now(timezone.utc)

        new_expense_id = f"exp-{uuid.uuid4().hex[:8]}"
        corrected_record = FarmExpenseORM(
            expense_id=new_expense_id,
            farm_id=farm_id,
            pond_id=new_pond_id,
            batch_id=new_batch_id,
            category=new_category,
            amount=round(new_amount, 2),
            currency=correction_data.get("currency", original.currency),
            transaction_date=tx_dt,
            supplier=clean_sup,
            invoice_number=clean_inv,
            payment_method=correction_data.get("payment_method", original.payment_method),
            status="ACTIVE",
            correction_type="CORRECTION",
            corrected_expense_id=original.expense_id,
            correction_reason=str(reason).strip(),
            notes=correction_data.get("notes", original.notes),
            recorded_by=recorded_by,
        )

        try:
            self._session.add(corrected_record)
            self._session.commit()
            self._session.refresh(corrected_record)
            return self._to_dict(corrected_record)
        except Exception:
            self._session.rollback()
            raise

    def reverse_expense(
        self,
        expense_id: str,
        farm_id: str,
        reversal_reason: str,
        recorded_by: str,
    ) -> Dict[str, Any]:
        """Perform an audited, non-destructive reversal of an active expense."""
        if not reversal_reason or not str(reversal_reason).strip():
            raise ValueError("reversal_reason is required for audited expense reversals.")

        original = (
            self._session.query(FarmExpenseORM)
            .filter(FarmExpenseORM.expense_id == expense_id, FarmExpenseORM.farm_id == farm_id)
            .first()
        )
        if not original:
            raise ValueError(f"Expense '{expense_id}' not found.")
        if original.status != "ACTIVE":
            raise ValueError(f"Cannot reverse inactive expense '{expense_id}' (status: {original.status}).")

        # Mark original as REVERSED
        original.status = "REVERSED"
        original.correction_reason = str(reversal_reason).strip()
        original.updated_at = datetime.now(timezone.utc)

        # Create an offsetting ledger record for financial auditing
        offset_record = FarmExpenseORM(
            expense_id=f"exp-{uuid.uuid4().hex[:8]}",
            farm_id=farm_id,
            pond_id=original.pond_id,
            batch_id=original.batch_id,
            category=original.category,
            amount=-original.amount,
            currency=original.currency,
            transaction_date=datetime.now(timezone.utc),
            supplier=original.supplier,
            invoice_number=original.invoice_number,
            payment_method=original.payment_method,
            status="REVERSED",
            correction_type="REVERSAL",
            corrected_expense_id=original.expense_id,
            correction_reason=str(reversal_reason).strip(),
            notes=f"Reversal offset for {original.expense_id}: {str(reversal_reason).strip()}",
            recorded_by=recorded_by,
        )

        try:
            self._session.add(offset_record)
            self._session.commit()
            self._session.refresh(original)
            return self._to_dict(original)
        except Exception:
            self._session.rollback()
            raise

    def get_expense(self, expense_id: str, farm_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve single expense verifying farm isolation."""
        e = (
            self._session.query(FarmExpenseORM)
            .filter(FarmExpenseORM.expense_id == expense_id, FarmExpenseORM.farm_id == farm_id)
            .first()
        )
        return self._to_dict(e) if e else None

    def list_expenses(
        self,
        farm_id: str,
        pond_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = "ACTIVE",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List expenses matching filters with pagination."""
        query = self._session.query(FarmExpenseORM).filter(FarmExpenseORM.farm_id == farm_id)

        if pond_id:
            query = query.filter(FarmExpenseORM.pond_id == pond_id)
        if batch_id:
            query = query.filter(FarmExpenseORM.batch_id == batch_id)
        if category:
            query = query.filter(FarmExpenseORM.category == category.upper())
        if status:
            query = query.filter(FarmExpenseORM.status == status.upper())
        if start_date:
            query = query.filter(FarmExpenseORM.transaction_date >= start_date)
        if end_date:
            query = query.filter(FarmExpenseORM.transaction_date <= end_date)

        total_count = query.count()
        records = (
            query.order_by(FarmExpenseORM.transaction_date.desc(), FarmExpenseORM.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [self._to_dict(r) for r in records], total_count

    def get_batch_expenses(self, farm_id: str, batch_id: str) -> List[Dict[str, Any]]:
        """Retrieve all active expenses genuinely attributed to a batch."""
        records = (
            self._session.query(FarmExpenseORM)
            .filter(
                FarmExpenseORM.farm_id == farm_id,
                FarmExpenseORM.batch_id == batch_id,
                FarmExpenseORM.status == "ACTIVE",
            )
            .order_by(FarmExpenseORM.transaction_date.asc())
            .all()
        )
        return [self._to_dict(r) for r in records]

    def get_farm_expense_summary(
        self,
        farm_id: str,
        pond_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Aggregate total expenses, category breakdowns, and attributable vs farm-wide distribution."""
        query = self._session.query(FarmExpenseORM).filter(
            FarmExpenseORM.farm_id == farm_id,
            FarmExpenseORM.status == "ACTIVE",
        )
        if pond_id:
            query = query.filter(FarmExpenseORM.pond_id == pond_id)
        if start_date:
            query = query.filter(FarmExpenseORM.transaction_date >= start_date)
        if end_date:
            query = query.filter(FarmExpenseORM.transaction_date <= end_date)

        records = query.all()

        total_amount = sum(r.amount for r in records)
        attributed_amount = sum(r.amount for r in records if r.batch_id is not None)
        unattributed_amount = sum(r.amount for r in records if r.batch_id is None)
        pond_overhead_amount = sum(r.amount for r in records if r.batch_id is None and r.pond_id is not None)
        general_farm_overhead_amount = sum(r.amount for r in records if r.batch_id is None and r.pond_id is None)

        by_category: Dict[str, Dict[str, Any]] = {}
        for cat in sorted(VALID_EXPENSE_CATEGORIES):
            cat_recs = [r for r in records if r.category == cat]
            by_category[cat] = {
                "category": cat,
                "total_amount": round(sum(r.amount for r in cat_recs), 2),
                "count": len(cat_recs),
            }

        return {
            "farm_id": farm_id,
            "pond_id": pond_id,
            "total_expenses_amount": round(total_amount, 2),
            "attributed_batch_expenses_amount": round(attributed_amount, 2),
            "unattributed_farm_wide_amount": round(unattributed_amount, 2),
            "pond_overhead_amount": round(pond_overhead_amount, 2),
            "general_farm_overhead_amount": round(general_farm_overhead_amount, 2),
            "expenses_count": len(records),
            "by_category": by_category,
            "currency": "USD",
            "as_of": datetime.now(timezone.utc).isoformat(),
        }

