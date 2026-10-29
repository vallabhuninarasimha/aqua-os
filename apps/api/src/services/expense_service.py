"""Application service coordinating farm expense management, audited corrections, and batch attribution."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from apps.api.src.infrastructure.repositories.sql_expense_repository import SQLExpenseRepository


class ExpenseService:
    """Service managing farm expense ledger, double-counting safeguards, and financial reporting."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = SQLExpenseRepository(session)

    def record_expense(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Record an expense entry with duplicate detection and batch attribution validation."""
        return self._repo.record_expense(data)

    def correct_expense(
        self,
        expense_id: str,
        farm_id: str,
        correction_data: Dict[str, Any],
        recorded_by: str,
    ) -> Dict[str, Any]:
        """Correct an active expense preserving the historical audit trail."""
        return self._repo.correct_expense(
            expense_id=expense_id,
            farm_id=farm_id,
            correction_data=correction_data,
            recorded_by=recorded_by,
        )

    def reverse_expense(
        self,
        expense_id: str,
        farm_id: str,
        reversal_reason: str,
        recorded_by: str,
    ) -> Dict[str, Any]:
        """Reverse an active expense using an audited offsetting ledger entry."""
        return self._repo.reverse_expense(
            expense_id=expense_id,
            farm_id=farm_id,
            reversal_reason=reversal_reason,
            recorded_by=recorded_by,
        )

    def get_expense(self, expense_id: str, farm_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve single expense record."""
        return self._repo.get_expense(expense_id=expense_id, farm_id=farm_id)

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
    ) -> Dict[str, Any]:
        """List expenses matching filters with pagination."""
        items, total_count = self._repo.list_expenses(
            farm_id=farm_id,
            pond_id=pond_id,
            batch_id=batch_id,
            category=category,
            status=status,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )
        return {
            "items": items,
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
        }

    def get_expense_summary(
        self,
        farm_id: str,
        pond_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Aggregate total expenses, category distribution, and attributable vs farm-wide overhead."""
        return self._repo.get_farm_expense_summary(
            farm_id=farm_id,
            pond_id=pond_id,
            start_date=start_date,
            end_date=end_date,
        )

    def get_batch_expenses(self, farm_id: str, batch_id: str) -> List[Dict[str, Any]]:
        """Retrieve all active expenses attributed to a specific batch."""
        return self._repo.get_batch_expenses(farm_id=farm_id, batch_id=batch_id)

