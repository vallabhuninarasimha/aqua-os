"""Feed Inventory Repository for Aqua OS.

Handles product catalog management, stock receipts, stock adjustments,
and atomic consumption deduction transactions with idempotency protection.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from apps.api.src.infrastructure.models import (
    FeedingLogORM,
    FeedInventoryTransactionORM,
    FeedProductORM,
)


class SQLFeedInventoryRepository:
    """SQLAlchemy implementation of feed product catalog and inventory ledger transactions."""

    def __init__(self, session: Session):
        self._session = session

    # =========================================================================
    # Feed Products Catalog
    # =========================================================================

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
        """Register a new feed product in the farm catalog."""
        if not product_name or not product_name.strip():
            raise ValueError("Product name cannot be empty.")
        if reorder_threshold_kg < 0:
            raise ValueError("Reorder threshold must be non-negative.")

        pid = product_id or f"prod-{uuid.uuid4().hex[:8]}"

        existing = (
            self._session.query(FeedProductORM)
            .filter(FeedProductORM.farm_id == farm_id, FeedProductORM.product_id == pid)
            .first()
        )
        if existing:
            raise ValueError(f"Product '{pid}' already exists on farm '{farm_id}'.")

        now = datetime.now(timezone.utc)
        orm = FeedProductORM(
            product_id=pid,
            farm_id=farm_id,
            product_name=product_name.strip(),
            brand=brand.strip() if brand else None,
            feed_type=feed_type.strip() if feed_type else None,
            pellet_size=pellet_size.strip() if pellet_size else None,
            unit_of_measure=unit_of_measure.strip() if unit_of_measure else "kg",
            reorder_threshold_kg=float(reorder_threshold_kg),
            is_active=True,
            notes=notes.strip() if notes else None,
            created_at=now,
            updated_at=now,
        )
        self._session.add(orm)
        self._session.commit()
        return self._product_to_dict(orm)

    def get_product(self, farm_id: str, product_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a feed product by ID."""
        orm = (
            self._session.query(FeedProductORM)
            .filter(FeedProductORM.farm_id == farm_id, FeedProductORM.product_id == product_id)
            .first()
        )
        return self._product_to_dict(orm) if orm else None

    def list_products(
        self,
        farm_id: str,
        active_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """List feed products registered for this farm."""
        query = self._session.query(FeedProductORM).filter(FeedProductORM.farm_id == farm_id)
        if active_only:
            query = query.filter(FeedProductORM.is_active == True)
        records = query.order_by(FeedProductORM.product_name.asc()).all()
        return [self._product_to_dict(r) for r in records]

    def update_product(
        self,
        farm_id: str,
        product_id: str,
        updates: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Update feed product catalog details."""
        orm = (
            self._session.query(FeedProductORM)
            .filter(FeedProductORM.farm_id == farm_id, FeedProductORM.product_id == product_id)
            .first()
        )
        if not orm:
            return None

        if "product_name" in updates and updates["product_name"]:
            orm.product_name = str(updates["product_name"]).strip()
        if "brand" in updates:
            orm.brand = str(updates["brand"]).strip() if updates["brand"] else None
        if "feed_type" in updates:
            orm.feed_type = str(updates["feed_type"]).strip() if updates["feed_type"] else None
        if "pellet_size" in updates:
            orm.pellet_size = str(updates["pellet_size"]).strip() if updates["pellet_size"] else None
        if "reorder_threshold_kg" in updates and updates["reorder_threshold_kg"] is not None:
            val = float(updates["reorder_threshold_kg"])
            if val < 0:
                raise ValueError("Reorder threshold must be non-negative.")
            orm.reorder_threshold_kg = val
        if "is_active" in updates and updates["is_active"] is not None:
            orm.is_active = bool(updates["is_active"])
        if "notes" in updates:
            orm.notes = str(updates["notes"]).strip() if updates["notes"] else None

        orm.updated_at = datetime.now(timezone.utc)
        self._session.commit()
        return self._product_to_dict(orm)

    # =========================================================================
    # Stock Balance & Reorder Calculation
    # =========================================================================

    def get_product_balance(self, farm_id: str, product_id: str) -> Dict[str, Any]:
        """Compute traceable inventory balance for a specific feed product."""
        product = self.get_product(farm_id, product_id)
        if not product:
            raise ValueError(f"Product '{product_id}' not found for farm '{farm_id}'.")

        # Sum quantities by transaction category
        txs = (
            self._session.query(
                FeedInventoryTransactionORM.transaction_type,
                func.sum(FeedInventoryTransactionORM.quantity_kg),
            )
            .filter(
                FeedInventoryTransactionORM.farm_id == farm_id,
                FeedInventoryTransactionORM.product_id == product_id,
            )
            .group_by(FeedInventoryTransactionORM.transaction_type)
            .all()
        )

        received_kg = 0.0
        consumed_kg = 0.0
        adjustment_kg = 0.0

        for t_type, total_qty in txs:
            qty = float(total_qty or 0.0)
            if t_type == "RECEIPT":
                received_kg += qty
            elif t_type == "CONSUMPTION":
                # Stored as negative quantity in ledger
                consumed_kg += abs(qty)
            else:
                # Adjustments: positive or negative
                adjustment_kg += qty

        available_balance_kg = round(received_kg - consumed_kg + adjustment_kg, 2)
        # Avoid negative floating noise
        if abs(available_balance_kg) < 1e-6:
            available_balance_kg = 0.0

        reorder_threshold = product.get("reorder_threshold_kg", 100.0) or 100.0
        is_low_stock = available_balance_kg <= reorder_threshold

        # Value calculation based on weighted or latest receipt prices
        receipt_txs = (
            self._session.query(
                FeedInventoryTransactionORM.quantity_kg,
                FeedInventoryTransactionORM.unit_price,
            )
            .filter(
                FeedInventoryTransactionORM.farm_id == farm_id,
                FeedInventoryTransactionORM.product_id == product_id,
                FeedInventoryTransactionORM.transaction_type == "RECEIPT",
                FeedInventoryTransactionORM.unit_price.isnot(None),
            )
            .all()
        )

        stock_value = None
        avg_cost_per_kg = None
        if receipt_txs:
            total_purchased_qty = sum(r[0] for r in receipt_txs if r[0] > 0)
            total_cost_sum = sum(r[0] * r[1] for r in receipt_txs if r[0] > 0 and r[1] is not None)
            if total_purchased_qty > 0:
                avg_cost_per_kg = round(total_cost_sum / total_purchased_qty, 2)
                stock_value = round(max(0.0, available_balance_kg) * avg_cost_per_kg, 2)

        return {
            "product_id": product_id,
            "product_name": product["product_name"],
            "brand": product.get("brand"),
            "feed_type": product.get("feed_type"),
            "pellet_size": product.get("pellet_size"),
            "unit_of_measure": product.get("unit_of_measure", "kg"),
            "total_received_kg": round(received_kg, 2),
            "total_consumed_kg": round(consumed_kg, 2),
            "total_adjusted_kg": round(adjustment_kg, 2),
            "available_balance_kg": available_balance_kg,
            "reorder_threshold_kg": reorder_threshold,
            "is_low_stock": is_low_stock,
            "avg_cost_per_kg": avg_cost_per_kg,
            "estimated_stock_value": stock_value,
            "is_active": product.get("is_active", True),
        }

    def get_farm_inventory_summary(self, farm_id: str) -> Dict[str, Any]:
        """Get inventory summary for all active and registered products on the farm."""
        products = self.list_products(farm_id, active_only=False)
        balances = [self.get_product_balance(farm_id, p["product_id"]) for p in products]

        total_stock_kg = round(sum(b["available_balance_kg"] for b in balances), 2)
        total_value = round(sum(b["estimated_stock_value"] or 0.0 for b in balances), 2)
        low_stock_count = sum(1 for b in balances if b["is_low_stock"] and b["is_active"])
        total_products_count = len(products)

        return {
            "farm_id": farm_id,
            "total_products_count": total_products_count,
            "total_stock_kg": total_stock_kg,
            "total_estimated_value": total_value if total_value > 0 else None,
            "low_stock_count": low_stock_count,
            "items": balances,
        }

    # =========================================================================
    # Stock Receipts (Purchases)
    # =========================================================================

    def record_receipt(
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
        """Record stock received from a supplier purchase."""
        if quantity_kg <= 0:
            raise ValueError("Received quantity must be strictly greater than 0 kg.")
        if unit_price is not None and unit_price < 0:
            raise ValueError("Unit price cannot be negative.")
        if total_cost is not None and total_cost < 0:
            raise ValueError("Total cost cannot be negative.")

        product = self.get_product(farm_id, product_id)
        if not product:
            raise ValueError(f"Feed product '{product_id}' not found for farm '{farm_id}'.")

        # Idempotency verification with farm-level scoping
        if idempotency_key:
            existing = (
                self._session.query(FeedInventoryTransactionORM)
                .filter(
                    FeedInventoryTransactionORM.farm_id == farm_id,
                    FeedInventoryTransactionORM.idempotency_key == idempotency_key,
                )
                .first()
            )
            if existing:
                return self._transaction_to_dict(existing)

        calculated_cost = total_cost
        if calculated_cost is None and unit_price is not None:
            calculated_cost = round(quantity_kg * unit_price, 2)

        tx_time = timestamp or datetime.now(timezone.utc)
        if isinstance(tx_time, str):
            tx_time = datetime.fromisoformat(tx_time.replace("Z", "+00:00"))
        if tx_time.tzinfo is None:
            tx_time = tx_time.replace(tzinfo=timezone.utc)

        tx_id = f"tx-rcpt-{uuid.uuid4().hex[:8]}"
        orm = FeedInventoryTransactionORM(
            transaction_id=tx_id,
            farm_id=farm_id,
            product_id=product_id,
            transaction_type="RECEIPT",
            quantity_kg=round(quantity_kg, 2),
            unit_of_measure=product.get("unit_of_measure", "kg"),
            unit_price=round(unit_price, 2) if unit_price is not None else None,
            total_cost=round(calculated_cost, 2) if calculated_cost is not None else None,
            supplier=supplier.strip() if supplier else None,
            invoice_number=invoice_number.strip() if invoice_number else None,
            feeding_log_id=None,
            pond_id=None,
            batch_id=None,
            reason="Stock Purchase Receipt",
            notes=notes.strip() if notes else None,
            idempotency_key=idempotency_key,
            recorded_by=recorded_by,
            timestamp=tx_time,
            created_at=datetime.now(timezone.utc),
        )

        self._session.add(orm)
        self._session.commit()
        return self._transaction_to_dict(orm)

    # =========================================================================
    # Stock Adjustments (Damage, Expiry, Correction)
    # =========================================================================

    def record_adjustment(
        self,
        farm_id: str,
        product_id: str,
        adjustment_type: str,  # ADJUSTMENT_DAMAGE, ADJUSTMENT_EXPIRED, ADJUSTMENT_CORRECTION, ADJUSTMENT_OTHER
        quantity_kg: float,  # for DAMAGE/EXPIRED: quantity damaged (subtracted); for CORRECTION: net change delta
        reason: str,
        notes: Optional[str] = None,
        recorded_by: str = "operator",
        timestamp: Optional[datetime] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record an authorized stock adjustment with mandatory reason and user audit trail."""
        valid_types = {
            "ADJUSTMENT_DAMAGE",
            "ADJUSTMENT_EXPIRED",
            "ADJUSTMENT_CORRECTION",
            "ADJUSTMENT_OTHER",
        }
        if adjustment_type not in valid_types:
            raise ValueError(f"Invalid adjustment type '{adjustment_type}'. Allowed: {', '.join(sorted(valid_types))}")

        if not reason or len(reason.strip()) < 3:
            raise ValueError("A clear, documented operational reason is strictly required for stock adjustments.")

        product = self.get_product(farm_id, product_id)
        if not product:
            raise ValueError(f"Feed product '{product_id}' not found for farm '{farm_id}'.")

        # Idempotency check with farm-level scoping
        if idempotency_key:
            existing = (
                self._session.query(FeedInventoryTransactionORM)
                .filter(
                    FeedInventoryTransactionORM.farm_id == farm_id,
                    FeedInventoryTransactionORM.idempotency_key == idempotency_key,
                )
                .first()
            )
            if existing:
                return self._transaction_to_dict(existing)

        # Check balance before negative adjustment
        balance_info = self.get_product_balance(farm_id, product_id)
        current_available = balance_info["available_balance_kg"]

        # Determine effective delta kg
        delta_kg = quantity_kg
        if adjustment_type in ("ADJUSTMENT_DAMAGE", "ADJUSTMENT_EXPIRED"):
            if quantity_kg <= 0:
                raise ValueError("Damage/expired quantity must be strictly greater than 0 kg.")
            delta_kg = -abs(quantity_kg)

        if delta_kg < 0 and (current_available + delta_kg) < -1e-6:
            raise ValueError(
                f"Adjustment exceeds available inventory. Current available: {current_available} kg, requested deduction: {abs(delta_kg)} kg."
            )

        tx_time = timestamp or datetime.now(timezone.utc)
        if isinstance(tx_time, str):
            tx_time = datetime.fromisoformat(tx_time.replace("Z", "+00:00"))
        if tx_time.tzinfo is None:
            tx_time = tx_time.replace(tzinfo=timezone.utc)

        tx_id = f"tx-adj-{uuid.uuid4().hex[:8]}"
        orm = FeedInventoryTransactionORM(
            transaction_id=tx_id,
            farm_id=farm_id,
            product_id=product_id,
            transaction_type=adjustment_type,
            quantity_kg=round(delta_kg, 2),
            unit_of_measure=product.get("unit_of_measure", "kg"),
            unit_price=None,
            total_cost=None,
            supplier=None,
            invoice_number=None,
            feeding_log_id=None,
            pond_id=None,
            batch_id=None,
            reason=reason.strip(),
            notes=notes.strip() if notes else None,
            idempotency_key=idempotency_key,
            recorded_by=recorded_by,
            timestamp=tx_time,
            created_at=datetime.now(timezone.utc),
        )

        self._session.add(orm)
        self._session.commit()
        return self._transaction_to_dict(orm)

    # =========================================================================
    # Consumption Integration with Feeding Log
    # =========================================================================

    def record_feeding_consumption(
        self,
        farm_id: str,
        product_id: str,
        feed_kg: float,
        feeding_log_id: int,
        pond_id: str,
        batch_id: Optional[str],
        recorded_by: str,
        timestamp: Optional[datetime] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atomically deduct stock for a feeding log event, preventing negative balance."""
        if feed_kg <= 0:
            raise ValueError("Consumption quantity must be strictly greater than 0 kg.")

        product = self.get_product(farm_id, product_id)
        if not product:
            raise ValueError(f"Feed product '{product_id}' not found for farm '{farm_id}'.")

        # Idempotency check with farm-level scoping: if feeding log is already deducted or key matches
        key = idempotency_key or f"feed-log-deduct-{farm_id}-{feeding_log_id}"
        existing = (
            self._session.query(FeedInventoryTransactionORM)
            .filter(
                FeedInventoryTransactionORM.farm_id == farm_id,
                (
                    (FeedInventoryTransactionORM.idempotency_key == key)
                    | (
                        (FeedInventoryTransactionORM.feeding_log_id == feeding_log_id)
                        & (FeedInventoryTransactionORM.transaction_type == "CONSUMPTION")
                    )
                ),
            )
            .first()
        )
        if existing:
            return self._transaction_to_dict(existing)

        # Check balance
        balance_info = self.get_product_balance(farm_id, product_id)
        available = balance_info["available_balance_kg"]
        if feed_kg > available + 1e-6:
            raise ValueError(
                f"Insufficient feed inventory for '{product['product_name']}'. Required: {feed_kg} kg, Available: {available} kg. Cannot permit negative stock."
            )

        tx_time = timestamp or datetime.now(timezone.utc)
        if isinstance(tx_time, str):
            tx_time = datetime.fromisoformat(tx_time.replace("Z", "+00:00"))
        if tx_time.tzinfo is None:
            tx_time = tx_time.replace(tzinfo=timezone.utc)

        tx_id = f"tx-feed-{uuid.uuid4().hex[:8]}"
        orm = FeedInventoryTransactionORM(
            transaction_id=tx_id,
            farm_id=farm_id,
            product_id=product_id,
            transaction_type="CONSUMPTION",
            quantity_kg=-round(feed_kg, 2),  # negative to indicate deduction
            unit_of_measure=product.get("unit_of_measure", "kg"),
            unit_price=balance_info.get("avg_cost_per_kg"),
            total_cost=round(feed_kg * balance_info["avg_cost_per_kg"], 2) if balance_info.get("avg_cost_per_kg") else None,
            supplier=None,
            invoice_number=None,
            feeding_log_id=feeding_log_id,
            pond_id=pond_id,
            batch_id=batch_id,
            reason=f"Pond ration consumption ({pond_id})",
            notes=f"Feeding log #{feeding_log_id}",
            idempotency_key=key,
            recorded_by=recorded_by,
            timestamp=tx_time,
            created_at=datetime.now(timezone.utc),
        )

        self._session.add(orm)
        self._session.commit()
        return self._transaction_to_dict(orm)

    # =========================================================================
    # Transaction History & Ledger Querying
    # =========================================================================

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
        """List audit transactions from the feed inventory ledger with filters."""
        query = self._session.query(FeedInventoryTransactionORM).filter(
            FeedInventoryTransactionORM.farm_id == farm_id
        )

        if product_id:
            query = query.filter(FeedInventoryTransactionORM.product_id == product_id)
        if transaction_type:
            query = query.filter(FeedInventoryTransactionORM.transaction_type == transaction_type)
        if pond_id:
            query = query.filter(FeedInventoryTransactionORM.pond_id == pond_id)

        if start_date:
            if isinstance(start_date, str):
                start_date = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            if start_date.tzinfo is None:
                start_date = start_date.replace(tzinfo=timezone.utc)
            query = query.filter(FeedInventoryTransactionORM.timestamp >= start_date)

        if end_date:
            if isinstance(end_date, str):
                end_date = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)
            query = query.filter(FeedInventoryTransactionORM.timestamp <= end_date)

        records = query.order_by(FeedInventoryTransactionORM.timestamp.desc()).limit(limit).all()
        return [self._transaction_to_dict(r) for r in records]

    # =========================================================================
    # Serializers
    # =========================================================================

    def _product_to_dict(self, orm: FeedProductORM) -> Dict[str, Any]:
        return {
            "product_id": orm.product_id,
            "farm_id": orm.farm_id,
            "product_name": orm.product_name,
            "brand": orm.brand,
            "feed_type": orm.feed_type,
            "pellet_size": orm.pellet_size,
            "unit_of_measure": orm.unit_of_measure,
            "reorder_threshold_kg": orm.reorder_threshold_kg,
            "is_active": bool(orm.is_active),
            "notes": orm.notes,
            "created_at": orm.created_at.isoformat() if orm.created_at else None,
            "updated_at": orm.updated_at.isoformat() if orm.updated_at else None,
        }

    def _transaction_to_dict(self, orm: FeedInventoryTransactionORM) -> Dict[str, Any]:
        return {
            "transaction_id": orm.transaction_id,
            "farm_id": orm.farm_id,
            "product_id": orm.product_id,
            "transaction_type": orm.transaction_type,
            "quantity_kg": orm.quantity_kg,
            "unit_of_measure": orm.unit_of_measure,
            "unit_price": orm.unit_price,
            "total_cost": orm.total_cost,
            "supplier": orm.supplier,
            "invoice_number": orm.invoice_number,
            "feeding_log_id": orm.feeding_log_id,
            "pond_id": orm.pond_id,
            "batch_id": orm.batch_id,
            "reason": orm.reason,
            "notes": orm.notes,
            "idempotency_key": orm.idempotency_key,
            "recorded_by": orm.recorded_by,
            "timestamp": orm.timestamp.isoformat() if orm.timestamp else None,
            "created_at": orm.created_at.isoformat() if orm.created_at else None,
        }

