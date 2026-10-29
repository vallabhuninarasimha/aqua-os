"""SQL Repository for Farm Cash Flow, Working Capital Intelligence, and Crop Cycle Budgets."""

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from apps.api.src.infrastructure.models import (
    CashBalanceSnapshotORM,
    CropCycleBudgetORM,
    FarmCashTransactionORM,
    FarmExpenseORM,
    FeedingLogORM,
    HarvestRecordORM,
    PondORM,
    StockingBatchORM,
)


VALID_CASH_IN_CATEGORIES = {
    "HARVEST_SALE_RECEIPT",
    "CUSTOMER_ADVANCE",
    "EQUITY_INJECTION",
    "LOAN_PROCEEDS",
    "SUBSIDY_GRANT",
    "OTHER_INFLOW",
}

VALID_CASH_OUT_CATEGORIES = {
    "EXPENSE_PAYMENT",
    "FEED_PURCHASE_PAYMENT",
    "VENDOR_ADVANCE",
    "LOAN_REPAYMENT",
    "OWNER_DRAW_DIVIDEND",
    "TAX_DUTY",
    "OTHER_OUTFLOW",
}

VALID_BUDGET_CATEGORIES = {
    "SEED_PL",
    "FEED",
    "CHEMICAL_AND_TREATMENT",
    "ELECTRICITY_ENERGY",
    "LABOUR",
    "MAINTENANCE_REPAIR",
    "OTHER",
    "FARM_OVERHEAD",
}


class SQLFinanceRepository:
    """Repository handling actual cash receipts, disbursements, obligations, and crop budgets."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _cash_tx_to_dict(self, tx: FarmCashTransactionORM) -> Dict[str, Any]:
        return {
            "id": tx.id,
            "transaction_id": tx.transaction_id,
            "farm_id": tx.farm_id,
            "entry_type": tx.entry_type,
            "category": tx.category,
            "amount": tx.amount,
            "currency": tx.currency,
            "payment_date": tx.payment_date.isoformat() if tx.payment_date else None,
            "payment_method": tx.payment_method,
            "reference_number": tx.reference_number,
            "payer_payee": tx.payer_payee,
            "expense_id": tx.expense_id,
            "harvest_id": tx.harvest_id,
            "batch_id": tx.batch_id,
            "pond_id": tx.pond_id,
            "idempotency_key": tx.idempotency_key,
            "status": tx.status,
            "void_reason": tx.void_reason,
            "notes": tx.notes,
            "recorded_by": tx.recorded_by,
            "created_at": tx.created_at.isoformat() if tx.created_at else None,
            "updated_at": tx.updated_at.isoformat() if tx.updated_at else None,
        }

    def _budget_to_dict(self, b: CropCycleBudgetORM) -> Dict[str, Any]:
        return {
            "id": b.id,
            "budget_id": b.budget_id,
            "farm_id": b.farm_id,
            "batch_id": b.batch_id,
            "pond_id": b.pond_id,
            "cycle_label": b.cycle_label,
            "category": b.category,
            "budgeted_amount": b.budgeted_amount,
            "currency": b.currency,
            "notes": b.notes,
            "created_by": b.created_by,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "updated_at": b.updated_at.isoformat() if b.updated_at else None,
        }

    # =========================================================================
    # 1. CASH LEDGER: RECORDING & AUDIT
    # =========================================================================

    def record_cash_transaction(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Record an actual cash receipt or disbursement with strict idempotency and linkage verification."""
        farm_id = data.get("farm_id")
        if not farm_id:
            raise ValueError("farm_id is required.")

        entry_type = str(data.get("entry_type", "")).upper()
        if entry_type not in ("CASH_IN", "CASH_OUT"):
            raise ValueError(f"Invalid entry_type '{entry_type}'. Must be 'CASH_IN' or 'CASH_OUT'.")

        category = str(data.get("category", "")).upper()
        if entry_type == "CASH_IN" and category not in VALID_CASH_IN_CATEGORIES:
            raise ValueError(f"Invalid CASH_IN category '{category}'. Must be one of {sorted(VALID_CASH_IN_CATEGORIES)}")
        if entry_type == "CASH_OUT" and category not in VALID_CASH_OUT_CATEGORIES:
            raise ValueError(f"Invalid CASH_OUT category '{category}'. Must be one of {sorted(VALID_CASH_OUT_CATEGORIES)}")

        amount = float(data.get("amount", 0.0))
        if math.isnan(amount) or math.isinf(amount) or amount <= 0:
            raise ValueError("Cash transaction amount must be a positive finite number.")

        expense_id = data.get("expense_id")
        harvest_id = data.get("harvest_id")
        if expense_id and harvest_id:
            raise ValueError("A single cash transaction cannot link to both an expense and a harvest simultaneously.")

        # Idempotency safeguard (farm-scoped)
        idem_key = data.get("idempotency_key")
        if idem_key and str(idem_key).strip():
            idem_key = str(idem_key).strip()
            existing = (
                self._session.query(FarmCashTransactionORM)
                .filter(
                    FarmCashTransactionORM.farm_id == farm_id,
                    FarmCashTransactionORM.idempotency_key == idem_key,
                )
                .first()
            )
            if existing:
                return self._cash_tx_to_dict(existing)
        else:
            idem_key = None

        pond_id = data.get("pond_id")
        batch_id = data.get("batch_id")
        payer_payee = data.get("payer_payee")
        tx_currency = str(data.get("currency", "")).strip().upper() if data.get("currency") else None

        # Linkage validation: Expense Payment
        if expense_id:
            if entry_type != "CASH_OUT":
                raise ValueError("An expense commitment can only be linked to a CASH_OUT disbursement.")
            exp = (
                self._session.query(FarmExpenseORM)
                .filter(FarmExpenseORM.farm_id == farm_id, FarmExpenseORM.expense_id == expense_id)
                .first()
            )
            if not exp:
                raise ValueError(f"Linked expense '{expense_id}' not found for farm '{farm_id}'.")

            # Follow correction chain forward if targeting a corrected predecessor
            if exp.status == "CORRECTED":
                active_replacement = (
                    self._session.query(FarmExpenseORM)
                    .filter(
                        FarmExpenseORM.farm_id == farm_id,
                        FarmExpenseORM.corrected_expense_id == exp.expense_id,
                        FarmExpenseORM.status == "ACTIVE",
                    )
                    .first()
                )
                if active_replacement:
                    exp = active_replacement
                    expense_id = exp.expense_id
                else:
                    raise ValueError(f"Cannot pay corrected expense '{expense_id}' without an active replacement record.")
            elif exp.status != "ACTIVE":
                raise ValueError(f"Cannot pay inactive/voided expense '{expense_id}' (status: {exp.status}).")

            # Currency matching with linked invoice
            if exp.currency:
                if not tx_currency:
                    tx_currency = exp.currency
                elif tx_currency != exp.currency:
                    raise ValueError(
                        f"Currency mismatch: Linked expense is in '{exp.currency}', but payment currency was '{tx_currency}'."
                    )

            # Trace complete correction lineage to prevent paying more than outstanding balance across revisions
            lineage_ids = {exp.expense_id}
            curr_pred = exp.corrected_expense_id
            while curr_pred:
                lineage_ids.add(curr_pred)
                pred_orm = (
                    self._session.query(FarmExpenseORM)
                    .filter(FarmExpenseORM.farm_id == farm_id, FarmExpenseORM.expense_id == curr_pred)
                    .first()
                )
                if pred_orm and pred_orm.corrected_expense_id and pred_orm.corrected_expense_id not in lineage_ids:
                    curr_pred = pred_orm.corrected_expense_id
                else:
                    break

            prior_payments = (
                self._session.query(func.coalesce(func.sum(FarmCashTransactionORM.amount), 0.0))
                .filter(
                    FarmCashTransactionORM.farm_id == farm_id,
                    FarmCashTransactionORM.expense_id.in_(list(lineage_ids)),
                    FarmCashTransactionORM.entry_type == "CASH_OUT",
                    FarmCashTransactionORM.status == "COMPLETED",
                )
                .scalar()
            )
            remaining_payable = round(max(0.0, exp.amount - prior_payments), 2)
            if round(amount, 2) > remaining_payable + 0.01:
                curr_sym = tx_currency or "INR"
                raise ValueError(
                    f"Payment amount {curr_sym} {amount:.2f} exceeds remaining payable {curr_sym} {remaining_payable:.2f} "
                    f"for expense invoice '{exp.invoice_number or exp.expense_id}' (Total: {exp.amount:.2f}, Paid: {prior_payments:.2f})."
                )

            if pond_id and exp.pond_id and pond_id != exp.pond_id:
                raise ValueError(f"Specified pond '{pond_id}' does not match expense pond '{exp.pond_id}'.")
            if batch_id and exp.batch_id and batch_id != exp.batch_id:
                raise ValueError(f"Specified batch '{batch_id}' does not match expense batch '{exp.batch_id}'.")
            if not pond_id:
                pond_id = exp.pond_id
            if not batch_id:
                batch_id = exp.batch_id
            if not payer_payee:
                payer_payee = exp.supplier

        # Linkage validation: Harvest Revenue Collection
        if harvest_id:
            if entry_type != "CASH_IN":
                raise ValueError("Harvest commercial sales can only be linked to a CASH_IN receipt.")
            hrv = (
                self._session.query(HarvestRecordORM)
                .filter(HarvestRecordORM.farm_id == farm_id, HarvestRecordORM.harvest_id == harvest_id)
                .first()
            )
            if not hrv:
                raise ValueError(f"Linked harvest '{harvest_id}' not found for farm '{farm_id}'.")

            if hrv.total_revenue is None or hrv.total_revenue <= 0:
                raise ValueError(f"Harvest '{harvest_id}' has no recorded commercial revenue to collect against.")

            prior_collections = (
                self._session.query(func.coalesce(func.sum(FarmCashTransactionORM.amount), 0.0))
                .filter(
                    FarmCashTransactionORM.farm_id == farm_id,
                    FarmCashTransactionORM.harvest_id == harvest_id,
                    FarmCashTransactionORM.entry_type == "CASH_IN",
                    FarmCashTransactionORM.status == "COMPLETED",
                )
                .scalar()
            )
            remaining_receivable = round(max(0.0, hrv.total_revenue - prior_collections), 2)
            if round(amount, 2) > remaining_receivable + 0.01:
                curr_sym = tx_currency or "INR"
                raise ValueError(
                    f"Receipt amount {curr_sym} {amount:.2f} exceeds remaining receivable {curr_sym} {remaining_receivable:.2f} "
                    f"for harvest '{harvest_id}' (Total Sales: {hrv.total_revenue:.2f}, Collected: {prior_collections:.2f})."
                )

            if pond_id and hrv.pond_id and pond_id != hrv.pond_id:
                raise ValueError(f"Specified pond '{pond_id}' does not match harvest pond '{hrv.pond_id}'.")
            if batch_id and hrv.batch_id and batch_id != hrv.batch_id:
                raise ValueError(f"Specified batch '{batch_id}' does not match harvest batch '{hrv.batch_id}'.")
            if not pond_id:
                pond_id = hrv.pond_id
            if not batch_id:
                batch_id = hrv.batch_id
            if not payer_payee:
                payer_payee = hrv.buyer

        # Attribution validation against tenant farm
        if pond_id:
            pond = (
                self._session.query(PondORM)
                .filter(PondORM.farm_id == farm_id, PondORM.pond_id == pond_id)
                .first()
            )
            if not pond:
                raise ValueError(f"Pond '{pond_id}' not found for farm '{farm_id}'.")

        if batch_id:
            batch = (
                self._session.query(StockingBatchORM)
                .filter(StockingBatchORM.batch_id == batch_id)
                .first()
            )
            if not batch or batch.farm_id != farm_id:
                raise ValueError(f"Batch '{batch_id}' is invalid for this farm.")
            if pond_id and batch.pond_id != pond_id:
                raise ValueError(f"Batch '{batch_id}' belongs to pond '{batch.pond_id}', not '{pond_id}'.")

        if not tx_currency:
            tx_currency = "INR"

        # Parse payment date
        p_dt = data.get("payment_date")
        if isinstance(p_dt, str):
            p_dt = datetime.fromisoformat(p_dt.replace("Z", "+00:00"))
        elif not isinstance(p_dt, datetime):
            p_dt = datetime.now(timezone.utc)
        if p_dt.tzinfo is None:
            p_dt = p_dt.replace(tzinfo=timezone.utc)

        tx_id = data.get("transaction_id") or f"csh-{uuid.uuid4().hex[:8]}"

        orm_tx = FarmCashTransactionORM(
            transaction_id=tx_id,
            farm_id=farm_id,
            entry_type=entry_type,
            category=category,
            amount=round(amount, 2),
            currency=tx_currency,
            payment_date=p_dt,
            payment_method=data.get("payment_method", "BANK_TRANSFER"),
            reference_number=str(data["reference_number"]).strip() if data.get("reference_number") else None,
            payer_payee=str(payer_payee).strip() if payer_payee else None,
            expense_id=expense_id,
            harvest_id=harvest_id,
            batch_id=batch_id,
            pond_id=pond_id,
            idempotency_key=idem_key,
            status="COMPLETED",
            notes=str(data["notes"]).strip() if data.get("notes") else None,
            recorded_by=data.get("recorded_by", "system"),
        )

        try:
            self._session.add(orm_tx)
            self._session.commit()
            self._session.refresh(orm_tx)
            return self._cash_tx_to_dict(orm_tx)
        except Exception:
            self._session.rollback()
            raise

    def void_cash_transaction(
        self,
        transaction_id: str,
        farm_id: str,
        void_reason: str,
        recorded_by: str,
    ) -> Dict[str, Any]:
        """Non-destructively void a completed cash transaction preserving the audit trail."""
        if not void_reason or not str(void_reason).strip():
            raise ValueError("void_reason is required for audited cash transaction voiding.")

        tx = (
            self._session.query(FarmCashTransactionORM)
            .filter(
                FarmCashTransactionORM.transaction_id == transaction_id,
                FarmCashTransactionORM.farm_id == farm_id,
            )
            .first()
        )
        if not tx:
            raise ValueError(f"Cash transaction '{transaction_id}' not found.")
        if tx.status != "COMPLETED":
            raise ValueError(f"Cannot void transaction '{transaction_id}' with status '{tx.status}'.")

        tx.status = "VOIDED"
        tx.void_reason = str(void_reason).strip()
        tx.updated_at = datetime.now(timezone.utc)

        try:
            self._session.commit()
            self._session.refresh(tx)
            return self._cash_tx_to_dict(tx)
        except Exception:
            self._session.rollback()
            raise

    def list_cash_transactions(
        self,
        farm_id: str,
        entry_type: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = "COMPLETED",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        pond_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """List cash transactions matching filters with pagination."""
        query = self._session.query(FarmCashTransactionORM).filter(
            FarmCashTransactionORM.farm_id == farm_id
        )

        if entry_type and entry_type.upper() in ("CASH_IN", "CASH_OUT"):
            query = query.filter(FarmCashTransactionORM.entry_type == entry_type.upper())
        if category:
            query = query.filter(FarmCashTransactionORM.category == category.upper())
        if status:
            query = query.filter(FarmCashTransactionORM.status == status.upper())
        if start_date:
            query = query.filter(FarmCashTransactionORM.payment_date >= start_date)
        if end_date:
            query = query.filter(FarmCashTransactionORM.payment_date <= end_date)
        if pond_id:
            query = query.filter(FarmCashTransactionORM.pond_id == pond_id)
        if batch_id:
            query = query.filter(FarmCashTransactionORM.batch_id == batch_id)

        total_count = query.count()
        records = (
            query.order_by(
                FarmCashTransactionORM.payment_date.desc(),
                FarmCashTransactionORM.id.desc(),
            )
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [self._cash_tx_to_dict(r) for r in records], total_count

    # =========================================================================
    # 2. OUTSTANDING OBLIGATIONS (PAYABLES & RECEIVABLES)
    # =========================================================================

    def get_outstanding_payables(
        self, farm_id: str, pond_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Compute verified accounts payable from active expense accruals minus documented cash payments."""
        exp_query = self._session.query(FarmExpenseORM).filter(
            FarmExpenseORM.farm_id == farm_id,
            FarmExpenseORM.status == "ACTIVE",
        )
        if pond_id:
            exp_query = exp_query.filter(FarmExpenseORM.pond_id == pond_id)

        expenses = exp_query.order_by(FarmExpenseORM.transaction_date.desc()).all()

        # Map correction lineage: predecessor -> active replacement
        corr_records = (
            self._session.query(FarmExpenseORM.expense_id, FarmExpenseORM.corrected_expense_id)
            .filter(
                FarmExpenseORM.farm_id == farm_id,
                FarmExpenseORM.corrected_expense_id.isnot(None),
            )
            .all()
        )
        pred_to_succ: Dict[str, str] = {
            pred_id: eid for eid, pred_id in corr_records if pred_id
        }
        active_ids = {e.expense_id for e in expenses}

        def resolve_active(curr_id: str) -> Optional[str]:
            visited = set()
            while curr_id in pred_to_succ and curr_id not in visited:
                visited.add(curr_id)
                succ = pred_to_succ[curr_id]
                if succ in active_ids:
                    return succ
                curr_id = succ
            return curr_id if curr_id in active_ids else None

        # Gather all completed cash disbursements linked to expenses for this farm
        disbursements = (
            self._session.query(FarmCashTransactionORM)
            .filter(
                FarmCashTransactionORM.farm_id == farm_id,
                FarmCashTransactionORM.entry_type == "CASH_OUT",
                FarmCashTransactionORM.status == "COMPLETED",
                FarmCashTransactionORM.expense_id.isnot(None),
            )
            .all()
        )
        paid_by_expense: Dict[str, float] = {}
        for d in disbursements:
            target_id = d.expense_id
            if target_id not in active_ids:
                mapped = resolve_active(target_id)
                if mapped:
                    target_id = mapped
            paid_by_expense[target_id] = paid_by_expense.get(target_id, 0.0) + d.amount

        items: List[Dict[str, Any]] = []
        by_currency: Dict[str, Dict[str, Any]] = {}
        unpaid_count = 0

        for e in expenses:
            curr = e.currency or "INR"
            paid = round(paid_by_expense.get(e.expense_id, 0.0), 2)
            outstanding = round(max(0.0, e.amount - paid), 2)

            if paid == 0:
                payment_status = "UNPAID"
                unpaid_count += 1
            elif paid < e.amount:
                payment_status = "PARTIALLY_PAID"
                unpaid_count += 1
            else:
                payment_status = "PAID"

            if curr not in by_currency:
                by_currency[curr] = {
                    "total_expense_accruals": 0.0,
                    "total_cash_paid": 0.0,
                    "total_outstanding_payables": 0.0,
                    "invoices_count": 0,
                    "unpaid_count": 0,
                }
            by_currency[curr]["total_expense_accruals"] = round(by_currency[curr]["total_expense_accruals"] + e.amount, 2)
            by_currency[curr]["total_cash_paid"] = round(by_currency[curr]["total_cash_paid"] + min(e.amount, paid), 2)
            by_currency[curr]["total_outstanding_payables"] = round(by_currency[curr]["total_outstanding_payables"] + outstanding, 2)
            by_currency[curr]["invoices_count"] += 1
            if outstanding > 0.005:
                by_currency[curr]["unpaid_count"] += 1

            items.append({
                "expense_id": e.expense_id,
                "farm_id": e.farm_id,
                "pond_id": e.pond_id,
                "batch_id": e.batch_id,
                "category": e.category,
                "supplier": e.supplier,
                "invoice_number": e.invoice_number,
                "invoice_date": e.transaction_date.isoformat() if e.transaction_date else None,
                "invoice_amount": e.amount,
                "amount_paid": paid,
                "outstanding_payable": outstanding,
                "payment_status": payment_status,
                "currency": curr,
            })

        currencies_present = sorted(list(by_currency.keys()))
        if len(currencies_present) == 1:
            prim_curr = currencies_present[0]
            summary_accruals = by_currency[prim_curr]["total_expense_accruals"]
            summary_paid = by_currency[prim_curr]["total_cash_paid"]
            summary_outstanding = by_currency[prim_curr]["total_outstanding_payables"]
            multi_curr = False
            rep_currency = prim_curr
        elif len(currencies_present) == 0:
            summary_accruals = 0.0
            summary_paid = 0.0
            summary_outstanding = 0.0
            multi_curr = False
            rep_currency = "INR"
        else:
            summary_accruals = None
            summary_paid = None
            summary_outstanding = None
            multi_curr = True
            rep_currency = "MULTI"

        return {
            "farm_id": farm_id,
            "pond_id": pond_id,
            "currency": rep_currency,
            "multi_currency": multi_curr,
            "currencies_present": currencies_present,
            "by_currency": by_currency,
            "total_expense_accruals": summary_accruals,
            "total_cash_paid": summary_paid,
            "total_outstanding_payables": summary_outstanding,
            "unpaid_obligations_count": unpaid_count,
            "total_invoices_count": len(expenses),
            "items": items,
            "as_of": datetime.now(timezone.utc).isoformat(),
        }

    def get_outstanding_receivables(
        self, farm_id: str, pond_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Compute verified commercial receivables from recorded harvest sales minus documented cash collections."""
        hrv_query = self._session.query(HarvestRecordORM).filter(
            HarvestRecordORM.farm_id == farm_id,
            HarvestRecordORM.total_revenue.isnot(None),
            HarvestRecordORM.total_revenue > 0,
        )
        if pond_id:
            hrv_query = hrv_query.filter(HarvestRecordORM.pond_id == pond_id)

        harvests = hrv_query.order_by(HarvestRecordORM.harvest_date.desc()).all()

        collections = (
            self._session.query(FarmCashTransactionORM)
            .filter(
                FarmCashTransactionORM.farm_id == farm_id,
                FarmCashTransactionORM.entry_type == "CASH_IN",
                FarmCashTransactionORM.status == "COMPLETED",
                FarmCashTransactionORM.harvest_id.isnot(None),
            )
            .all()
        )
        collected_by_harvest: Dict[str, float] = {}
        harvest_currencies: Dict[str, str] = {}
        for c in collections:
            collected_by_harvest[c.harvest_id] = collected_by_harvest.get(c.harvest_id, 0.0) + c.amount
            if c.harvest_id and c.currency:
                harvest_currencies[c.harvest_id] = c.currency

        items: List[Dict[str, Any]] = []
        by_currency: Dict[str, Dict[str, Any]] = {}
        uncollected_count = 0

        for h in harvests:
            rev = h.total_revenue or 0.0
            collected = round(collected_by_harvest.get(h.harvest_id, 0.0), 2)
            outstanding = round(max(0.0, rev - collected), 2)
            curr = harvest_currencies.get(h.harvest_id, "INR")

            if collected == 0:
                coll_status = "UNCOLLECTED"
                uncollected_count += 1
            elif collected < rev:
                coll_status = "PARTIALLY_COLLECTED"
                uncollected_count += 1
            else:
                coll_status = "COLLECTED"

            if curr not in by_currency:
                by_currency[curr] = {
                    "total_commercial_revenue": 0.0,
                    "total_cash_collected": 0.0,
                    "total_outstanding_receivables": 0.0,
                    "total_harvest_sales_count": 0,
                    "uncollected_sales_count": 0,
                }
            by_currency[curr]["total_commercial_revenue"] = round(by_currency[curr]["total_commercial_revenue"] + rev, 2)
            by_currency[curr]["total_cash_collected"] = round(by_currency[curr]["total_cash_collected"] + min(rev, collected), 2)
            by_currency[curr]["total_outstanding_receivables"] = round(by_currency[curr]["total_outstanding_receivables"] + outstanding, 2)
            by_currency[curr]["total_harvest_sales_count"] += 1
            if outstanding > 0.005:
                by_currency[curr]["uncollected_sales_count"] += 1

            items.append({
                "harvest_id": h.harvest_id,
                "farm_id": h.farm_id,
                "pond_id": h.pond_id,
                "batch_id": h.batch_id,
                "harvest_type": h.harvest_type,
                "harvest_date": h.harvest_date.isoformat() if h.harvest_date else None,
                "buyer": h.buyer,
                "yield_kg": h.harvested_weight_kg,
                "total_revenue": rev,
                "amount_collected": collected,
                "outstanding_receivable": outstanding,
                "collection_status": coll_status,
                "currency": curr,
            })

        currencies_present = sorted(list(by_currency.keys()))
        if len(currencies_present) == 1:
            prim_curr = currencies_present[0]
            summary_rev = by_currency[prim_curr]["total_commercial_revenue"]
            summary_collected = by_currency[prim_curr]["total_cash_collected"]
            summary_outstanding = by_currency[prim_curr]["total_outstanding_receivables"]
            multi_curr = False
            rep_currency = prim_curr
        elif len(currencies_present) == 0:
            summary_rev = 0.0
            summary_collected = 0.0
            summary_outstanding = 0.0
            multi_curr = False
            rep_currency = "INR"
        else:
            summary_rev = None
            summary_collected = None
            summary_outstanding = None
            multi_curr = True
            rep_currency = "MULTI"

        return {
            "farm_id": farm_id,
            "pond_id": pond_id,
            "currency": rep_currency,
            "multi_currency": multi_curr,
            "currencies_present": currencies_present,
            "by_currency": by_currency,
            "total_commercial_revenue": summary_rev,
            "total_cash_collected": summary_collected,
            "total_outstanding_receivables": summary_outstanding,
            "uncollected_sales_count": uncollected_count,
            "total_harvest_sales_count": len(harvests),
            "items": items,
            "as_of": datetime.now(timezone.utc).isoformat(),
        }

    # =========================================================================
    # 3. WORKING CAPITAL & CASH FLOW SUMMARY
    # =========================================================================

    def get_working_capital_summary(
        self,
        farm_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Aggregate actual cash movements, outstanding obligations, and liquid cash position without cross-currency contamination."""
        tx_query = self._session.query(FarmCashTransactionORM).filter(
            FarmCashTransactionORM.farm_id == farm_id,
            FarmCashTransactionORM.status == "COMPLETED",
        )
        if start_date:
            tx_query = tx_query.filter(FarmCashTransactionORM.payment_date >= start_date)
        if end_date:
            tx_query = tx_query.filter(FarmCashTransactionORM.payment_date <= end_date)

        transactions = tx_query.all()
        inflows = [t for t in transactions if t.entry_type == "CASH_IN"]
        outflows = [t for t in transactions if t.entry_type == "CASH_OUT"]

        currencies_present = sorted(list(set(t.currency or "INR" for t in transactions)))

        cash_flow_by_currency: Dict[str, Dict[str, Any]] = {}
        for curr in currencies_present:
            inflows_curr = sum(t.amount for t in inflows if (t.currency or "INR") == curr)
            outflows_curr = sum(t.amount for t in outflows if (t.currency or "INR") == curr)
            net_curr = inflows_curr - outflows_curr
            inflow_cats: Dict[str, float] = {}
            for cat in sorted(VALID_CASH_IN_CATEGORIES):
                inflow_cats[cat] = round(sum(t.amount for t in inflows if (t.currency or "INR") == curr and t.category == cat), 2)
            outflow_cats: Dict[str, float] = {}
            for cat in sorted(VALID_CASH_OUT_CATEGORIES):
                outflow_cats[cat] = round(sum(t.amount for t in outflows if (t.currency or "INR") == curr and t.category == cat), 2)

            cash_flow_by_currency[curr] = {
                "total_cash_inflow": round(inflows_curr, 2),
                "total_cash_outflow": round(outflows_curr, 2),
                "net_cash_flow": round(net_curr, 2),
                "inflow_transactions_count": len([t for t in inflows if (t.currency or "INR") == curr]),
                "outflow_transactions_count": len([t for t in outflows if (t.currency or "INR") == curr]),
                "inflows_by_category": inflow_cats,
                "outflows_by_category": outflow_cats,
            }

        if len(currencies_present) == 1:
            prim_curr = currencies_present[0]
            total_inflow = cash_flow_by_currency[prim_curr]["total_cash_inflow"]
            total_outflow = cash_flow_by_currency[prim_curr]["total_cash_outflow"]
            net_cash_flow = cash_flow_by_currency[prim_curr]["net_cash_flow"]
            multi_curr = False
            rep_currency = prim_curr
        elif len(currencies_present) == 0:
            total_inflow = 0.0
            total_outflow = 0.0
            net_cash_flow = 0.0
            multi_curr = False
            rep_currency = "INR"
        else:
            total_inflow = None
            total_outflow = None
            net_cash_flow = None
            multi_curr = True
            rep_currency = "MULTI"

        payables_summary = self.get_outstanding_payables(farm_id)
        receivables_summary = self.get_outstanding_receivables(farm_id)

        # Liquid cash balance inspection
        latest_snapshot = (
            self._session.query(CashBalanceSnapshotORM)
            .filter(CashBalanceSnapshotORM.farm_id == farm_id)
            .order_by(CashBalanceSnapshotORM.balance_date.desc(), CashBalanceSnapshotORM.id.desc())
            .first()
        )

        available_cash = None
        cash_balance_status = "CASH_BALANCE_NOT_RECORDED"
        balance_metadata = None

        if latest_snapshot:
            snap_curr = latest_snapshot.currency or "INR"
            # Reconcile cash movements since snapshot strictly within the SAME currency
            subsequent_inflows = (
                self._session.query(func.coalesce(func.sum(FarmCashTransactionORM.amount), 0.0))
                .filter(
                    FarmCashTransactionORM.farm_id == farm_id,
                    FarmCashTransactionORM.status == "COMPLETED",
                    FarmCashTransactionORM.entry_type == "CASH_IN",
                    FarmCashTransactionORM.currency == snap_curr,
                    FarmCashTransactionORM.payment_date >= latest_snapshot.balance_date,
                )
                .scalar()
            )
            subsequent_outflows = (
                self._session.query(func.coalesce(func.sum(FarmCashTransactionORM.amount), 0.0))
                .filter(
                    FarmCashTransactionORM.farm_id == farm_id,
                    FarmCashTransactionORM.status == "COMPLETED",
                    FarmCashTransactionORM.entry_type == "CASH_OUT",
                    FarmCashTransactionORM.currency == snap_curr,
                    FarmCashTransactionORM.payment_date >= latest_snapshot.balance_date,
                )
                .scalar()
            )
            available_cash = round(
                latest_snapshot.opening_balance + subsequent_inflows - subsequent_outflows, 2
            )
            cash_balance_status = "VERIFIED_RECORDED"
            balance_metadata = {
                "snapshot_id": latest_snapshot.snapshot_id,
                "snapshot_date": latest_snapshot.balance_date.isoformat(),
                "opening_balance": latest_snapshot.opening_balance,
                "currency": snap_curr,
                "bank_account_name": latest_snapshot.bank_account_name,
                "verified_by": latest_snapshot.verified_by,
                "notes": latest_snapshot.notes,
            }

        return {
            "farm_id": farm_id,
            "period": {
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
            },
            "cash_flow": {
                "total_cash_inflow": total_inflow,
                "total_cash_outflow": total_outflow,
                "net_cash_flow": net_cash_flow,
                "currency": rep_currency,
                "multi_currency": multi_curr,
                "currencies_present": currencies_present,
                "inflow_transactions_count": len(inflows),
                "outflow_transactions_count": len(outflows),
                "by_currency": cash_flow_by_currency,
            },
            "liquid_cash_position": {
                "available_cash": available_cash,
                "cash_balance_status": cash_balance_status,
                "currency": latest_snapshot.currency if latest_snapshot else "INR",
                "snapshot_details": balance_metadata,
            },
            "obligations": {
                "outstanding_accounts_payable": payables_summary["total_outstanding_payables"],
                "unpaid_bills_count": payables_summary["unpaid_obligations_count"],
                "payables_by_currency": payables_summary.get("by_currency", {}),
                "outstanding_accounts_receivable": receivables_summary["total_outstanding_receivables"],
                "uncollected_sales_count": receivables_summary["uncollected_sales_count"],
                "receivables_by_currency": receivables_summary.get("by_currency", {}),
                "net_working_capital_position": (
                    round(
                        receivables_summary["total_outstanding_receivables"]
                        - payables_summary["total_outstanding_payables"],
                        2,
                    )
                    if receivables_summary["total_outstanding_receivables"] is not None
                    and payables_summary["total_outstanding_payables"] is not None
                    else None
                ),
            },
            "advisory_notice": (
                "Figures reflect actual cash movements and documented obligations without synthetic estimations. "
                "Unpaid invoices remain documented payables; unverified cash balances are strictly labeled CASH_BALANCE_NOT_RECORDED."
            ),
            "as_of": datetime.now(timezone.utc).isoformat(),
        }

    # =========================================================================
    # 4. CROP-CYCLE BUDGETS VS RECORDED ACTUALS
    # =========================================================================

    def record_budget(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create or update a crop-cycle expenditure budget entry."""
        farm_id = data.get("farm_id")
        if not farm_id:
            raise ValueError("farm_id is required.")

        category = str(data.get("category", "")).upper()
        if category not in VALID_BUDGET_CATEGORIES:
            raise ValueError(f"Invalid budget category '{category}'. Must be one of {sorted(VALID_BUDGET_CATEGORIES)}")

        amount = float(data.get("budgeted_amount", 0.0))
        if math.isnan(amount) or math.isinf(amount) or amount <= 0:
            raise ValueError("Budgeted amount must be a positive finite number.")

        batch_id = data.get("batch_id")
        pond_id = data.get("pond_id")

        if pond_id:
            pond = (
                self._session.query(PondORM)
                .filter(PondORM.farm_id == farm_id, PondORM.pond_id == pond_id)
                .first()
            )
            if not pond:
                raise ValueError(f"Pond '{pond_id}' not found for farm '{farm_id}'.")

        if batch_id:
            batch = (
                self._session.query(StockingBatchORM)
                .filter(StockingBatchORM.batch_id == batch_id)
                .first()
            )
            if not batch or batch.farm_id != farm_id:
                raise ValueError(f"Batch '{batch_id}' is invalid for this farm.")
            if pond_id and batch.pond_id != pond_id:
                raise ValueError(f"Batch '{batch_id}' belongs to pond '{batch.pond_id}', not '{pond_id}'.")
            if not pond_id:
                pond_id = batch.pond_id

        budget_id = data.get("budget_id") or f"bdg-{uuid.uuid4().hex[:8]}"

        orm_budget = CropCycleBudgetORM(
            budget_id=budget_id,
            farm_id=farm_id,
            batch_id=batch_id,
            pond_id=pond_id,
            cycle_label=data.get("cycle_label") or (batch_id or pond_id or "Farm-Wide Cycle"),
            category=category,
            budgeted_amount=round(amount, 2),
            currency=str(data.get("currency", "INR")).strip().upper(),
            notes=str(data["notes"]).strip() if data.get("notes") else None,
            created_by=data.get("created_by", "system"),
        )

        try:
            self._session.add(orm_budget)
            self._session.commit()
            self._session.refresh(orm_budget)
            return self._budget_to_dict(orm_budget)
        except Exception:
            self._session.rollback()
            raise

    def list_budgets_vs_actuals(
        self,
        farm_id: str,
        batch_id: Optional[str] = None,
        pond_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Compare configured budgets against attributable recorded actual costs without fabrication."""
        b_query = self._session.query(CropCycleBudgetORM).filter(
            CropCycleBudgetORM.farm_id == farm_id
        )
        if batch_id:
            b_query = b_query.filter(CropCycleBudgetORM.batch_id == batch_id)
        if pond_id:
            b_query = b_query.filter(CropCycleBudgetORM.pond_id == pond_id)

        budgets = b_query.order_by(CropCycleBudgetORM.category.asc()).all()

        # Gather recorded active expenses for this scope
        exp_query = self._session.query(FarmExpenseORM).filter(
            FarmExpenseORM.farm_id == farm_id,
            FarmExpenseORM.status == "ACTIVE",
        )
        if batch_id:
            exp_query = exp_query.filter(FarmExpenseORM.batch_id == batch_id)
        elif pond_id:
            exp_query = exp_query.filter(FarmExpenseORM.pond_id == pond_id)
        expenses = exp_query.all()

        items: List[Dict[str, Any]] = []
        currencies_present = sorted(list(set(b.currency or "INR" for b in budgets)))

        total_budget = 0.0
        total_actual = 0.0

        for b in budgets:
            b_curr = b.currency or "INR"
            total_budget += b.budgeted_amount

            # Resolve actual recorded cost for this budget category strictly matching budget currency
            actual_cost = 0.0
            data_confidence = "RECORDED_ACTUALS"
            confidence_notice = None

            if b.category == "FEED":
                # For FEED, actual comes from feeding log consumption valuation
                if b.batch_id:
                    from apps.api.src.infrastructure.repositories.sql_feed_inventory_repository import (
                        SQLFeedInventoryRepository,
                    )
                    from apps.api.src.infrastructure.repositories.sql_pond_records_repository import (
                        SQLPondRecordsRepository,
                    )
                    pond_repo = SQLPondRecordsRepository(self._session)
                    inv_repo = SQLFeedInventoryRepository(self._session)
                    f_logs = pond_repo.list_feeding_logs(batch_id=b.batch_id)
                    feed_costs_by_product = inv_repo.get_feed_costs_by_product(farm_id)
                    calc_feed = 0.0
                    missing_cost_count = 0
                    total_logs = len(f_logs)
                    for flog in f_logs:
                        c_kg = feed_costs_by_product.get(flog.product_id)
                        if c_kg is not None:
                            calc_feed += flog.feed_kg * c_kg
                        else:
                            missing_cost_count += 1
                    actual_cost = round(calc_feed, 2)
                    if total_logs == 0:
                        data_confidence = "NO_FEEDING_LOGS"
                        confidence_notice = "No physical feeding logs recorded for this batch yet."
                    elif missing_cost_count > 0:
                        data_confidence = "INCOMPLETE_FEED_VALUATION"
                        confidence_notice = f"Valuation partial: {missing_cost_count} of {total_logs} feeding logs lack product unit costs in inventory."
                    else:
                        data_confidence = "RECORDED_ACTUALS"
                        confidence_notice = "Feed valuation derived from verified feeding logs and inventory cost per kg."
                elif b.pond_id:
                    # Look up active batch in pond
                    active_batch = (
                        self._session.query(StockingBatchORM)
                        .filter(StockingBatchORM.farm_id == farm_id, StockingBatchORM.pond_id == b.pond_id, StockingBatchORM.status == "ACTIVE")
                        .order_by(StockingBatchORM.stocking_date.desc())
                        .first()
                    )
                    if active_batch:
                        from apps.api.src.infrastructure.repositories.sql_feed_inventory_repository import (
                            SQLFeedInventoryRepository,
                        )
                        from apps.api.src.infrastructure.repositories.sql_pond_records_repository import (
                            SQLPondRecordsRepository,
                        )
                        pond_repo = SQLPondRecordsRepository(self._session)
                        inv_repo = SQLFeedInventoryRepository(self._session)
                        f_logs = pond_repo.list_feeding_logs(batch_id=active_batch.batch_id)
                        feed_costs_by_product = inv_repo.get_feed_costs_by_product(farm_id)
                        calc_feed = 0.0
                        missing_cost_count = 0
                        total_logs = len(f_logs)
                        for flog in f_logs:
                            c_kg = feed_costs_by_product.get(flog.product_id)
                            if c_kg is not None:
                                calc_feed += flog.feed_kg * c_kg
                            else:
                                missing_cost_count += 1
                        actual_cost = round(calc_feed, 2)
                        if total_logs == 0:
                            data_confidence = "NO_FEEDING_LOGS"
                            confidence_notice = "No physical feeding logs recorded for active batch in pond."
                        elif missing_cost_count > 0:
                            data_confidence = "INCOMPLETE_FEED_VALUATION"
                            confidence_notice = f"Valuation partial: {missing_cost_count} of {total_logs} feeding logs lack product unit costs in inventory."
                        else:
                            data_confidence = "RECORDED_ACTUALS"
                            confidence_notice = f"Valued physical consumption from active batch '{active_batch.batch_id}'."
                    else:
                        actual_cost = 0.0
                        data_confidence = "NO_ACTIVE_BATCH"
                        confidence_notice = f"No active stocking batch currently found in pond '{b.pond_id}'."
                else:
                    # Farm-wide feed purchases
                    matched = [e.amount for e in expenses if e.category == "FEED" and (e.currency or "INR") == b_curr]
                    actual_cost = round(sum(matched), 2)
                    confidence_notice = "Farm-wide feed budget tracks warehouse purchase expenses; individual batch/pond budgets track valued feeding logs."
            elif b.category == "FARM_OVERHEAD":
                # General overhead expenses (batch_id is None)
                matched = [e.amount for e in expenses if e.batch_id is None and (e.currency or "INR") == b_curr]
                actual_cost = round(sum(matched), 2)
                confidence_notice = "Overhead reflects unattributed farm-wide operational expenses."
            else:
                # Direct expenses matching category and currency
                if b.batch_id:
                    matched = [e.amount for e in expenses if e.category == b.category and e.batch_id == b.batch_id and (e.currency or "INR") == b_curr]
                elif b.pond_id:
                    matched = [e.amount for e in expenses if e.category == b.category and e.pond_id == b.pond_id and (e.currency or "INR") == b_curr]
                else:
                    matched = [e.amount for e in expenses if e.category == b.category and (e.currency or "INR") == b_curr]
                actual_cost = round(sum(matched), 2)
                confidence_notice = "Attributable recorded expense vouchers."

            total_actual += actual_cost
            variance = round(b.budgeted_amount - actual_cost, 2)
            utilization = round((actual_cost / b.budgeted_amount) * 100, 1) if b.budgeted_amount > 0 else 0.0

            if actual_cost == 0:
                budget_status = "NO_EXPENSES_YET"
            elif variance >= 0:
                budget_status = "UNDER_BUDGET" if utilization < 95.0 else "ON_TRACK"
            else:
                budget_status = "OVER_BUDGET"

            items.append({
                "budget_id": b.budget_id,
                "category": b.category,
                "cycle_label": b.cycle_label,
                "batch_id": b.batch_id,
                "pond_id": b.pond_id,
                "budgeted_amount": b.budgeted_amount,
                "actual_recorded_cost": actual_cost,
                "variance": variance,
                "utilization_pct": utilization,
                "status": budget_status,
                "confidence_label": data_confidence,
                "confidence_notice": confidence_notice,
                "currency": b_curr,
                "notes": b.notes,
            })

        net_variance = round(total_budget - total_actual, 2)
        overall_utilization = round((total_actual / total_budget) * 100, 1) if total_budget > 0 else 0.0

        if len(currencies_present) == 1:
            rep_currency = currencies_present[0]
            multi_curr = False
        elif len(currencies_present) == 0:
            rep_currency = "INR"
            multi_curr = False
        else:
            rep_currency = "MULTI"
            multi_curr = True

        return {
            "farm_id": farm_id,
            "batch_id": batch_id,
            "pond_id": pond_id,
            "currency": rep_currency,
            "multi_currency": multi_curr,
            "currencies_present": currencies_present,
            "total_budgeted_amount": round(total_budget, 2) if not multi_curr else None,
            "total_actual_recorded_amount": round(total_actual, 2) if not multi_curr else None,
            "net_variance": net_variance if not multi_curr else None,
            "overall_utilization_pct": overall_utilization if not multi_curr else None,
            "budget_items_count": len(items),
            "items": items,
            "as_of": datetime.now(timezone.utc).isoformat(),
        }

    # =========================================================================
    # 5. CASH BALANCE SNAPSHOT RECORDING
    # =========================================================================

    def record_balance_snapshot(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Record a verified bank or cash on hand opening/closing balance snapshot."""
        farm_id = data.get("farm_id")
        if not farm_id:
            raise ValueError("farm_id is required.")

        opening_balance = float(data.get("opening_balance", 0.0))
        if math.isnan(opening_balance) or math.isinf(opening_balance) or opening_balance < 0:
            raise ValueError("Opening balance must be a non-negative finite number.")

        closing_balance = None
        if data.get("closing_balance") is not None:
            cb = float(data["closing_balance"])
            if math.isnan(cb) or math.isinf(cb) or cb < 0:
                raise ValueError("Closing balance must be a non-negative finite number.")
            closing_balance = round(cb, 2)

        b_dt = data.get("balance_date")
        if isinstance(b_dt, str):
            b_dt = datetime.fromisoformat(b_dt.replace("Z", "+00:00"))
        elif not isinstance(b_dt, datetime):
            b_dt = datetime.now(timezone.utc)
        if b_dt.tzinfo is None:
            b_dt = b_dt.replace(tzinfo=timezone.utc)

        snapshot_id = f"bal-{uuid.uuid4().hex[:8]}"

        orm_snap = CashBalanceSnapshotORM(
            snapshot_id=snapshot_id,
            farm_id=farm_id,
            balance_date=b_dt,
            opening_balance=round(opening_balance, 2),
            closing_balance=closing_balance,
            currency=str(data.get("currency", "INR")).strip().upper(),
            bank_account_name=str(data["bank_account_name"]).strip() if data.get("bank_account_name") else None,
            verified_by=str(data.get("verified_by", "auditor")).strip(),
            notes=str(data["notes"]).strip() if data.get("notes") else None,
        )

        try:
            self._session.add(orm_snap)
            self._session.commit()
            self._session.refresh(orm_snap)
            return {
                "snapshot_id": orm_snap.snapshot_id,
                "farm_id": orm_snap.farm_id,
                "balance_date": orm_snap.balance_date.isoformat(),
                "opening_balance": orm_snap.opening_balance,
                "closing_balance": orm_snap.closing_balance,
                "currency": orm_snap.currency,
                "bank_account_name": orm_snap.bank_account_name,
                "verified_by": orm_snap.verified_by,
                "notes": orm_snap.notes,
            }
        except Exception:
            self._session.rollback()
            raise

    def get_latest_balance_snapshot(self, farm_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve latest verified cash balance snapshot."""
        s = (
            self._session.query(CashBalanceSnapshotORM)
            .filter(CashBalanceSnapshotORM.farm_id == farm_id)
            .order_by(CashBalanceSnapshotORM.balance_date.desc(), CashBalanceSnapshotORM.id.desc())
            .first()
        )
        if not s:
            return None
        return {
            "snapshot_id": s.snapshot_id,
            "farm_id": s.farm_id,
            "balance_date": s.balance_date.isoformat(),
            "opening_balance": s.opening_balance,
            "closing_balance": s.closing_balance,
            "currency": s.currency,
            "bank_account_name": s.bank_account_name,
            "verified_by": s.verified_by,
            "notes": s.notes,
        }

