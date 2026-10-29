"""Farm Cash Flow, Working Capital Intelligence, and Crop Budgets API Endpoints.

Provides audited recording of actual cash movements, outstanding obligations (payables/receivables),
working capital summaries, and crop-cycle budget comparisons with strict tenant isolation.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.src.config import settings
from apps.api.src.infrastructure.database import get_db
from apps.api.src.security.dependencies import require_permission, verify_farm_access
from apps.api.src.security.models import Permission, UserIdentity
from apps.api.src.services.finance_service import FinanceService


router = APIRouter(prefix="/finance", tags=["Farm Cash Flow & Finance"])


import math
from pydantic import BaseModel, Field, model_validator


# ============================================================================
# Request / Response Schemas
# ============================================================================

class CashTransactionCreateRequest(BaseModel):
    """Payload to record an actual cash movement (receipt or disbursement)."""
    entry_type: str = Field(description="Transaction type: CASH_IN or CASH_OUT")
    category: str = Field(description="Cash movement category")
    amount: float = Field(gt=0, description="Cash amount in currency units")
    currency: str = Field(default="INR", description="Currency symbol/code (defaults to INR)")
    payment_date: Optional[str] = Field(default=None, description="ISO timestamp of financial settlement")
    payment_method: str = Field(default="BANK_TRANSFER", description="BANK_TRANSFER, CASH, CHEQUE, UPI_WIRE, MOBILE_MONEY")
    reference_number: Optional[str] = Field(default=None, description="Bank transfer ref, cheque #, or gateway txn id")
    payer_payee: Optional[str] = Field(default=None, description="Name of paying buyer or recipient vendor")
    expense_id: Optional[str] = Field(default=None, description="Linked FarmExpenseORM.expense_id if paying an invoice")
    harvest_id: Optional[str] = Field(default=None, description="Linked HarvestRecordORM.harvest_id if collecting sale revenue")
    pond_id: Optional[str] = Field(default=None, description="Attributable pond ID (if applicable)")
    batch_id: Optional[str] = Field(default=None, description="Attributable batch ID (if applicable)")
    idempotency_key: Optional[str] = Field(default=None, description="Client idempotency key to prevent double posting")
    notes: Optional[str] = Field(default=None, description="Audit notes or transaction details")

    @model_validator(mode="after")
    def validate_single_linkage_and_amount(self) -> "CashTransactionCreateRequest":
        if math.isnan(self.amount) or math.isinf(self.amount) or self.amount <= 0:
            raise ValueError("Amount must be a positive finite number.")
        if self.expense_id and self.harvest_id:
            raise ValueError("A single cash transaction cannot link to both an expense and a harvest simultaneously.")
        return self


class CashTransactionVoidRequest(BaseModel):
    """Payload to non-destructively void a completed cash transaction."""
    void_reason: str = Field(min_length=3, description="Mandatory audit justification for voiding the cash movement")


class BudgetCreateRequest(BaseModel):
    """Payload to set a crop-cycle expenditure budget target."""
    category: str = Field(description="Operational category: SEED_PL, FEED, CHEMICAL_AND_TREATMENT, ELECTRICITY_ENERGY, LABOUR, MAINTENANCE_REPAIR, OTHER, FARM_OVERHEAD")
    budgeted_amount: float = Field(gt=0, description="Target budget amount in currency units")
    currency: str = Field(default="INR", description="Currency symbol/code (defaults to INR)")
    batch_id: Optional[str] = Field(default=None, description="Target batch ID (if batch-specific)")
    pond_id: Optional[str] = Field(default=None, description="Target pond ID (if pond-specific)")
    cycle_label: Optional[str] = Field(default=None, description="Label for the cycle or season (e.g. 'Cycle 2026-Q1')")
    notes: Optional[str] = Field(default=None, description="Budget planning assumptions or notes")

    @model_validator(mode="after")
    def validate_budget_amount(self) -> "BudgetCreateRequest":
        if math.isnan(self.budgeted_amount) or math.isinf(self.budgeted_amount) or self.budgeted_amount <= 0:
            raise ValueError("Budgeted amount must be a positive finite number.")
        return self


class CashBalanceSnapshotRequest(BaseModel):
    """Payload to record a verified bank or cash opening balance."""
    opening_balance: float = Field(ge=0, description="Verified cash balance on hand / in bank")
    closing_balance: Optional[float] = Field(default=None, description="Optional closing balance")
    balance_date: Optional[str] = Field(default=None, description="ISO timestamp of balance verification")
    currency: str = Field(default="INR", description="Currency symbol/code (defaults to INR)")
    bank_account_name: Optional[str] = Field(default=None, description="Bank account or treasury wallet label")
    notes: Optional[str] = Field(default=None, description="Audit reconciliation notes")

    @model_validator(mode="after")
    def validate_snapshot_amounts(self) -> "CashBalanceSnapshotRequest":
        if math.isnan(self.opening_balance) or math.isinf(self.opening_balance) or self.opening_balance < 0:
            raise ValueError("Opening balance must be a non-negative finite number.")
        if self.closing_balance is not None and (math.isnan(self.closing_balance) or math.isinf(self.closing_balance) or self.closing_balance < 0):
            raise ValueError("Closing balance must be a non-negative finite number.")
        return self


# ============================================================================
# Endpoints
# ============================================================================

@router.post("/cash-transactions", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def record_cash_transaction(
    req: CashTransactionCreateRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Record an actual cash inflow receipt or disbursement payment with traceability."""
    verify_farm_access(user, farm_id)
    service = FinanceService(session)
    data = req.model_dump()
    data["farm_id"] = farm_id
    data["recorded_by"] = user.username
    try:
        return service.record_cash_transaction(data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/cash-transactions", response_model=Dict[str, Any])
async def list_cash_transactions(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    entry_type: Optional[str] = Query(default=None, description="Filter by CASH_IN or CASH_OUT"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
    status_filter: Optional[str] = Query(default="COMPLETED", alias="status", description="Filter: COMPLETED, VOIDED, ALL"),
    start_date: Optional[str] = Query(default=None, description="Start date ISO filter"),
    end_date: Optional[str] = Query(default=None, description="End date ISO filter"),
    pond_id: Optional[str] = Query(default=None, description="Filter by pond ID"),
    batch_id: Optional[str] = Query(default=None, description="Filter by batch ID"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """List actual cash movements with filtering and pagination."""
    verify_farm_access(user, farm_id)
    service = FinanceService(session)

    try:
        s_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00")) if start_date else None
        e_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00")) if end_date else None
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date filter format. Please provide valid ISO-8601 timestamps.",
        )
    st = None if status_filter and status_filter.upper() == "ALL" else status_filter

    return service.list_cash_transactions(
        farm_id=farm_id,
        entry_type=entry_type,
        category=category,
        status=st,
        start_date=s_dt,
        end_date=e_dt,
        pond_id=pond_id,
        batch_id=batch_id,
        limit=limit,
        offset=offset,
    )


@router.post("/cash-transactions/{transaction_id}/void", response_model=Dict[str, Any])
async def void_cash_transaction(
    transaction_id: str,
    req: CashTransactionVoidRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Non-destructively void a completed cash transaction preserving the audit trail."""
    verify_farm_access(user, farm_id)
    service = FinanceService(session)
    try:
        return service.void_cash_transaction(
            transaction_id=transaction_id,
            farm_id=farm_id,
            void_reason=req.void_reason,
            recorded_by=user.username,
        )
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/obligations/payables", response_model=Dict[str, Any])
async def get_outstanding_payables(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    pond_id: Optional[str] = Query(default=None, description="Optional pond filter"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve verified accounts payable obligations from unpaid active expense accruals."""
    verify_farm_access(user, farm_id)
    service = FinanceService(session)
    return service.get_outstanding_payables(farm_id=farm_id, pond_id=pond_id)


@router.get("/obligations/receivables", response_model=Dict[str, Any])
async def get_outstanding_receivables(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    pond_id: Optional[str] = Query(default=None, description="Optional pond filter"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve verified commercial receivables from uncollected harvest sales."""
    verify_farm_access(user, farm_id)
    service = FinanceService(session)
    return service.get_outstanding_receivables(farm_id=farm_id, pond_id=pond_id)


@router.get("/working-capital/summary", response_model=Dict[str, Any])
async def get_working_capital_summary(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    start_date: Optional[str] = Query(default=None, description="Start date ISO filter"),
    end_date: Optional[str] = Query(default=None, description="End date ISO filter"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve working capital summary, cash movements, obligations, and liquid cash position."""
    verify_farm_access(user, farm_id)
    service = FinanceService(session)

    try:
        s_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00")) if start_date else None
        e_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00")) if end_date else None
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date filter format. Please provide valid ISO-8601 timestamps.",
        )

    return service.get_working_capital_summary(
        farm_id=farm_id,
        start_date=s_dt,
        end_date=e_dt,
    )


@router.post("/budgets", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def record_crop_budget(
    req: BudgetCreateRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Create or update a crop-cycle expenditure budget target."""
    verify_farm_access(user, farm_id)
    service = FinanceService(session)
    data = req.model_dump()
    data["farm_id"] = farm_id
    data["created_by"] = user.username
    try:
        return service.record_budget(data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/budgets", response_model=Dict[str, Any])
async def list_budgets_vs_actuals(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    batch_id: Optional[str] = Query(default=None, description="Filter by batch ID"),
    pond_id: Optional[str] = Query(default=None, description="Filter by pond ID"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Compare configured budgets against attributable recorded actual costs."""
    verify_farm_access(user, farm_id)
    service = FinanceService(session)
    return service.list_budgets_vs_actuals(
        farm_id=farm_id,
        batch_id=batch_id,
        pond_id=pond_id,
    )


@router.post("/cash-balance", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def record_cash_balance_snapshot(
    req: CashBalanceSnapshotRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Record a verified bank or cash on hand balance snapshot."""
    verify_farm_access(user, farm_id)
    service = FinanceService(session)
    data = req.model_dump()
    data["farm_id"] = farm_id
    data["verified_by"] = user.username
    try:
        return service.record_balance_snapshot(data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/cash-balance", response_model=Optional[Dict[str, Any]])
async def get_latest_cash_balance(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db),
) -> Optional[Dict[str, Any]]:
    """Get latest verified cash balance snapshot."""
    verify_farm_access(user, farm_id)
    service = FinanceService(session)
    return service.get_latest_balance_snapshot(farm_id=farm_id)

