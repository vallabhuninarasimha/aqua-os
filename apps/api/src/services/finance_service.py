"""Application service coordinating farm cash flow, working capital, and crop budgets."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from apps.api.src.infrastructure.repositories.sql_finance_repository import SQLFinanceRepository


class FinanceService:
    """Service orchestrating actual cash movements, payment obligations, working capital, and budgets."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = SQLFinanceRepository(session)

    def record_cash_transaction(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Record an actual cash inflow receipt or outflow disbursement."""
        return self._repo.record_cash_transaction(data)

    def void_cash_transaction(
        self,
        transaction_id: str,
        farm_id: str,
        void_reason: str,
        recorded_by: str,
    ) -> Dict[str, Any]:
        """Void an active cash transaction preserving the audit trail."""
        return self._repo.void_cash_transaction(
            transaction_id=transaction_id,
            farm_id=farm_id,
            void_reason=void_reason,
            recorded_by=recorded_by,
        )

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
    ) -> Dict[str, Any]:
        """List cash transactions with filtering and pagination."""
        items, total_count = self._repo.list_cash_transactions(
            farm_id=farm_id,
            entry_type=entry_type,
            category=category,
            status=status,
            start_date=start_date,
            end_date=end_date,
            pond_id=pond_id,
            batch_id=batch_id,
            limit=limit,
            offset=offset,
        )
        return {
            "items": items,
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
        }

    def get_outstanding_payables(
        self, farm_id: str, pond_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get verified accounts payable from unpaid expense obligations."""
        return self._repo.get_outstanding_payables(farm_id=farm_id, pond_id=pond_id)

    def get_outstanding_receivables(
        self, farm_id: str, pond_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get verified commercial receivables from uncollected harvest sales."""
        return self._repo.get_outstanding_receivables(farm_id=farm_id, pond_id=pond_id)

    def get_working_capital_summary(
        self,
        farm_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Aggregate actual cash movements, working capital, and liquid cash position."""
        return self._repo.get_working_capital_summary(
            farm_id=farm_id,
            start_date=start_date,
            end_date=end_date,
        )

    def record_budget(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Record or update crop-cycle budget target."""
        return self._repo.record_budget(data)

    def list_budgets_vs_actuals(
        self,
        farm_id: str,
        batch_id: Optional[str] = None,
        pond_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Compare configured budgets against attributable recorded actual costs."""
        return self._repo.list_budgets_vs_actuals(
            farm_id=farm_id,
            batch_id=batch_id,
            pond_id=pond_id,
        )

    def record_balance_snapshot(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Record a verified bank or cash on hand opening balance."""
        return self._repo.record_balance_snapshot(data)

    def get_latest_balance_snapshot(self, farm_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve latest verified cash balance snapshot."""
        return self._repo.get_latest_balance_snapshot(farm_id=farm_id)

