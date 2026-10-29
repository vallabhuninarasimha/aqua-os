"""Farm Expense & Purchase Ledger API Endpoints.

Provides audited recording, non-destructive correction, reversal, and querying of farm expenses
with strict tenant isolation and double-counting safeguards.
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
from apps.api.src.services.expense_service import ExpenseService


router = APIRouter(prefix="/expenses", tags=["Farm Expenses"])


# ============================================================================
# Request / Response Schemas
# ============================================================================

class ExpenseCreateRequest(BaseModel):
    """Payload to record an operating or production purchase/expense."""
    category: str = Field(description="Expense category: SEED_PL, CHEMICAL_AND_TREATMENT, ELECTRICITY_ENERGY, LABOUR, MAINTENANCE_REPAIR, FEED, OTHER")
    amount: float = Field(gt=0, description="Expense amount in currency units")
    currency: str = Field(default="USD", description="Currency symbol/code")
    transaction_date: Optional[str] = Field(default=None, description="ISO timestamp of financial transaction")
    pond_id: Optional[str] = Field(default=None, description="Attributable pond ID (if applicable)")
    batch_id: Optional[str] = Field(default=None, description="Attributable batch ID (if applicable)")
    supplier: Optional[str] = Field(default=None, description="Vendor or supplier company name")
    invoice_number: Optional[str] = Field(default=None, description="Vendor invoice or receipt reference number")
    payment_method: Optional[str] = Field(default=None, description="Payment method: BANK_TRANSFER, CASH, CHEQUE, CREDIT")
    idempotency_key: Optional[str] = Field(default=None, description="Client-generated key to prevent duplicate submissions")
    notes: Optional[str] = Field(default=None, description="Audit notes or descriptive details")


class ExpenseCorrectionRequest(BaseModel):
    """Payload to perform an audited correction of an active expense."""
    correction_reason: str = Field(min_length=3, description="Mandatory audit justification for correcting the expense")
    category: Optional[str] = None
    amount: Optional[float] = Field(default=None, gt=0)
    currency: Optional[str] = None
    transaction_date: Optional[str] = None
    pond_id: Optional[str] = None
    batch_id: Optional[str] = None
    supplier: Optional[str] = None
    invoice_number: Optional[str] = None
    payment_method: Optional[str] = None
    notes: Optional[str] = None


class ExpenseReversalRequest(BaseModel):
    """Payload to reverse an active expense record."""
    reversal_reason: str = Field(min_length=3, description="Mandatory audit justification for reversing the expense")


# ============================================================================
# Endpoints
# ============================================================================

@router.post("", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def record_farm_expense(
    req: ExpenseCreateRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Record an audited production or operating expense with duplicate detection."""
    verify_farm_access(user, farm_id)
    service = ExpenseService(session)
    data = req.model_dump()
    data["farm_id"] = farm_id
    data["recorded_by"] = user.username
    try:
        return service.record_expense(data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("", response_model=Dict[str, Any])
async def list_farm_expenses(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    pond_id: Optional[str] = Query(default=None, description="Filter by pond ID"),
    batch_id: Optional[str] = Query(default=None, description="Filter by batch ID"),
    category: Optional[str] = Query(default=None, description="Filter by expense category"),
    status_filter: Optional[str] = Query(default="ACTIVE", alias="status", description="Filter by status: ACTIVE, CORRECTED, REVERSED, ALL"),
    start_date: Optional[str] = Query(default=None, description="Start date ISO filter"),
    end_date: Optional[str] = Query(default=None, description="End date ISO filter"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """List farm expense ledger entries matching criteria with pagination."""
    verify_farm_access(user, farm_id)
    service = ExpenseService(session)

    try:
        s_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00")) if start_date else None
        e_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00")) if end_date else None
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date filter format. Please provide valid ISO-8601 timestamps (e.g. 2026-10-11T00:00:00Z).",
        )
    st = None if status_filter and status_filter.upper() == "ALL" else status_filter

    return service.list_expenses(
        farm_id=farm_id,
        pond_id=pond_id,
        batch_id=batch_id,
        category=category,
        status=st,
        start_date=s_dt,
        end_date=e_dt,
        limit=limit,
        offset=offset,
    )


@router.get("/summary", response_model=Dict[str, Any])
async def get_farm_expense_summary(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    pond_id: Optional[str] = Query(default=None, description="Filter by pond ID"),
    start_date: Optional[str] = Query(default=None, description="Start date filter"),
    end_date: Optional[str] = Query(default=None, description="End date filter"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Aggregate expense summary by category and attributable vs farm-wide overhead distribution."""
    verify_farm_access(user, farm_id)
    service = ExpenseService(session)

    try:
        s_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00")) if start_date else None
        e_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00")) if end_date else None
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date filter format. Please provide valid ISO-8601 timestamps.",
        )

    return service.get_expense_summary(
        farm_id=farm_id,
        pond_id=pond_id,
        start_date=s_dt,
        end_date=e_dt,
    )


@router.get("/batches/{batch_id}", response_model=List[Dict[str, Any]])
async def get_batch_attributed_expenses(
    batch_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Retrieve all active expenses genuinely attributed to a specific production batch."""
    verify_farm_access(user, farm_id)
    service = ExpenseService(session)
    return service.get_batch_expenses(farm_id=farm_id, batch_id=batch_id)


@router.get("/{expense_id}", response_model=Dict[str, Any])
async def get_farm_expense(
    expense_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieve details of a single expense record."""
    verify_farm_access(user, farm_id)
    service = ExpenseService(session)
    exp = service.get_expense(expense_id=expense_id, farm_id=farm_id)
    if not exp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Expense '{expense_id}' not found.")
    return exp


@router.post("/{expense_id}/correct", response_model=Dict[str, Any])
async def correct_farm_expense(
    expense_id: str,
    req: ExpenseCorrectionRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Perform an audited, non-destructive correction of an active expense."""
    verify_farm_access(user, farm_id)
    service = ExpenseService(session)
    try:
        return service.correct_expense(
            expense_id=expense_id,
            farm_id=farm_id,
            correction_data=req.model_dump(exclude_unset=True),
            recorded_by=user.username,
        )
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{expense_id}/reverse", response_model=Dict[str, Any])
async def reverse_farm_expense(
    expense_id: str,
    req: ExpenseReversalRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Perform an audited, non-destructive reversal of an active expense."""
    verify_farm_access(user, farm_id)
    service = ExpenseService(session)
    try:
        return service.reverse_expense(
            expense_id=expense_id,
            farm_id=farm_id,
            reversal_reason=req.reversal_reason,
            recorded_by=user.username,
        )
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

