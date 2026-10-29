"""Feed Inventory Management Service for Aqua OS.

Coordinates feed catalog, stock receipts, authorized stock adjustments,
traceable balance calculations, and low-stock warnings.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from apps.api.src.infrastructure.repositories.sql_feed_inventory_repository import (
    SQLFeedInventoryRepository,
)


class FeedInventoryService:
    """Application domain service for farm feed inventory management."""

    def __init__(self, session: Session):
        self._session = session
        self._repo = SQLFeedInventoryRepository(session)

    # -------------------------------------------------------------------------
    # Product Catalog
    # -------------------------------------------------------------------------

    def create_product(
        self,
        farm_id: str,
        product_name: str,
        brand: Optional[str] = None,
        feed_type: Optional[str] = None,
        pellet_size: Optional[str] = None,
        unit_of_measure: str = "kg",
        reorder_threshold_kg: float = 100.0,
        notes: Optional[str] = None,
        product_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new feed product in catalog."""
        return self._repo.create_product(
            farm_id=farm_id,
            product_name=product_name,
            brand=brand,
            feed_type=feed_type,
            pellet_size=pellet_size,
            unit_of_measure=unit_of_measure,
            reorder_threshold_kg=reorder_threshold_kg,
            notes=notes,
            product_id=product_id,
        )

    def get_product(self, farm_id: str, product_id: str) -> Optional[Dict[str, Any]]:
        """Get feed product by ID."""
        return self._repo.get_product(farm_id=farm_id, product_id=product_id)

    def list_products(self, farm_id: str, active_only: bool = False) -> List[Dict[str, Any]]:
        """List products for farm."""
        return self._repo.list_products(farm_id=farm_id, active_only=active_only)

    def update_product(
        self, farm_id: str, product_id: str, updates: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Update product attributes."""
        return self._repo.update_product(farm_id=farm_id, product_id=product_id, updates=updates)

    # -------------------------------------------------------------------------
    # Stock Balances & Summaries
    # -------------------------------------------------------------------------

    def get_product_balance(self, farm_id: str, product_id: str) -> Dict[str, Any]:
        """Get detailed inventory balance and valuation for a single product."""
        return self._repo.get_product_balance(farm_id=farm_id, product_id=product_id)

    def get_farm_inventory_summary(self, farm_id: str) -> Dict[str, Any]:
        """Get farm-level inventory summary and low stock alerts."""
        return self._repo.get_farm_inventory_summary(farm_id=farm_id)

    # -------------------------------------------------------------------------
    # Receipts & Adjustments
    # -------------------------------------------------------------------------

    def receive_stock(
        self,
        farm_id: str,
        product_id: str,
        quantity_kg: float,
        unit_price: Optional[float] = None,
        total_cost: Optional[float] = None,
        supplier: Optional[str] = None,
        invoice_number: Optional[str] = None,
        notes: Optional[str] = None,
        recorded_by: str = "operator",
        timestamp: Optional[datetime] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record stock received from purchase."""
        return self._repo.record_receipt(
            farm_id=farm_id,
            product_id=product_id,
            quantity_kg=quantity_kg,
            unit_price=unit_price,
            total_cost=total_cost,
            supplier=supplier,
            invoice_number=invoice_number,
            notes=notes,
            recorded_by=recorded_by,
            timestamp=timestamp,
            idempotency_key=idempotency_key,
        )

    def adjust_stock(
        self,
        farm_id: str,
        product_id: str,
        adjustment_type: str,
        quantity_kg: float,
        reason: str,
        notes: Optional[str] = None,
        recorded_by: str = "operator",
        timestamp: Optional[datetime] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record authorized stock adjustment."""
        return self._repo.record_adjustment(
            farm_id=farm_id,
            product_id=product_id,
            adjustment_type=adjustment_type,
            quantity_kg=quantity_kg,
            reason=reason,
            notes=notes,
            recorded_by=recorded_by,
            timestamp=timestamp,
            idempotency_key=idempotency_key,
        )

    # -------------------------------------------------------------------------
    # Ledger History
    # -------------------------------------------------------------------------

    def list_transactions(
        self,
        farm_id: str,
        product_id: Optional[str] = None,
        transaction_type: Optional[str] = None,
        pond_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List audit transactions from the feed inventory ledger."""
        return self._repo.list_transactions(
            farm_id=farm_id,
            product_id=product_id,
            transaction_type=transaction_type,
            pond_id=pond_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )

