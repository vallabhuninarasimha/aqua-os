"""Feed Inventory Management API Routes for Aqua OS."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.src.config import settings
from apps.api.src.dependencies import get_db_session
from apps.api.src.security.dependencies import require_permission, verify_farm_access
from apps.api.src.security.models import Permission, UserIdentity
from apps.api.src.services.feed_inventory_service import FeedInventoryService

router = APIRouter(prefix="/feed-inventory", tags=["Feed Inventory"])


# ============================================================================
# Request / Response Schemas
# ============================================================================

class FeedProductCreateRequest(BaseModel):
    product_name: str = Field(..., min_length=1, description="Commercial product name")
    brand: Optional[str] = Field(default=None, description="Feed manufacturer or brand")
    feed_type: Optional[str] = Field(default=None, description="Feed type (e.g. Starter, Grower, Finisher)")
    pellet_size: Optional[str] = Field(default=None, description="Pellet size or mesh (e.g. 1.2mm, #2)")
    unit_of_measure: str = Field(default="kg", description="Unit of measurement (defaults to kg)")
    reorder_threshold_kg: float = Field(default=100.0, ge=0.0, description="Minimum safe stock threshold")
    notes: Optional[str] = Field(default=None, description="Optional description or storage notes")
    product_id: Optional[str] = Field(default=None, description="Optional custom product identifier")


class FeedProductUpdateRequest(BaseModel):
    product_name: Optional[str] = Field(default=None, description="Commercial product name")
    brand: Optional[str] = Field(default=None, description="Feed manufacturer or brand")
    feed_type: Optional[str] = Field(default=None, description="Feed type")
    pellet_size: Optional[str] = Field(default=None, description="Pellet size")
    reorder_threshold_kg: Optional[float] = Field(default=None, ge=0.0, description="Minimum safe stock threshold")
    is_active: Optional[bool] = Field(default=None, description="Active status")
    notes: Optional[str] = Field(default=None, description="Notes")


class FeedStockReceiptRequest(BaseModel):
    product_id: str = Field(..., description="Target feed product identifier")
    quantity_kg: float = Field(..., gt=0.0, description="Quantity received in kg (strictly > 0)")
    unit_price: Optional[float] = Field(default=None, ge=0.0, description="Unit purchase price per kg, if known")
    total_cost: Optional[float] = Field(default=None, ge=0.0, description="Total cost of receipt, if known")
    supplier: Optional[str] = Field(default=None, description="Supplier or vendor name")
    invoice_number: Optional[str] = Field(default=None, description="Purchase order or invoice reference")
    notes: Optional[str] = Field(default=None, description="Optional delivery / batch notes")
    timestamp: Optional[datetime] = Field(default=None, description="Purchase or receipt timestamp")
    idempotency_key: Optional[str] = Field(default=None, description="Client idempotency key to prevent double posting")


class FeedStockAdjustmentRequest(BaseModel):
    product_id: str = Field(..., description="Target feed product identifier")
    adjustment_type: str = Field(
        ...,
        description="Type: ADJUSTMENT_DAMAGE, ADJUSTMENT_EXPIRED, ADJUSTMENT_CORRECTION, ADJUSTMENT_OTHER",
    )
    quantity_kg: float = Field(..., description="Quantity to adjust (positive or negative delta)")
    reason: str = Field(..., min_length=3, description="Documented operational reason for adjustment")
    notes: Optional[str] = Field(default=None, description="Optional audit notes")
    timestamp: Optional[datetime] = Field(default=None, description="Adjustment timestamp")
    idempotency_key: Optional[str] = Field(default=None, description="Client idempotency key")


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/summary", response_model=Dict[str, Any])
async def get_inventory_summary(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve farm feed inventory summary, available balances, and low-stock alerts."""
    verify_farm_access(user, farm_id)
    service = FeedInventoryService(session)
    return service.get_farm_inventory_summary(farm_id=farm_id)


@router.get("/products", response_model=List[Dict[str, Any]])
async def list_feed_products(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    active_only: bool = Query(default=False, description="Filter only active products"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """List all registered feed products for the farm."""
    verify_farm_access(user, farm_id)
    service = FeedInventoryService(session)
    return service.list_products(farm_id=farm_id, active_only=active_only)


@router.post("/products", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
async def create_feed_product(
    req: FeedProductCreateRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Register a new feed product in the catalog."""
    verify_farm_access(user, farm_id)
    service = FeedInventoryService(session)
    try:
        return service.create_product(
            farm_id=farm_id,
            product_name=req.product_name,
            brand=req.brand,
            feed_type=req.feed_type,
            pellet_size=req.pellet_size,
            unit_of_measure=req.unit_of_measure,
            reorder_threshold_kg=req.reorder_threshold_kg,
            notes=req.notes,
            product_id=req.product_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/products/{product_id}", response_model=Dict[str, Any])
async def get_feed_product(
    product_id: str,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Get feed product details and stock balance."""
    verify_farm_access(user, farm_id)
    service = FeedInventoryService(session)
    product = service.get_product(farm_id=farm_id, product_id=product_id)
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Product '{product_id}' not found.")
    balance = service.get_product_balance(farm_id=farm_id, product_id=product_id)
    return {**product, **balance}


@router.patch("/products/{product_id}", response_model=Dict[str, Any])
async def update_feed_product(
    product_id: str,
    req: FeedProductUpdateRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Update feed product catalog details."""
    verify_farm_access(user, farm_id)
    service = FeedInventoryService(session)
    try:
        updated = service.update_product(
            farm_id=farm_id,
            product_id=product_id,
            updates=req.model_dump(exclude_unset=True),
        )
        if not updated:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Product '{product_id}' not found.")
        return updated
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/receipts", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
async def receive_stock(
    req: FeedStockReceiptRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Record stock received from supplier purchase."""
    verify_farm_access(user, farm_id)
    service = FeedInventoryService(session)
    try:
        return service.receive_stock(
            farm_id=farm_id,
            product_id=req.product_id,
            quantity_kg=req.quantity_kg,
            unit_price=req.unit_price,
            total_cost=req.total_cost,
            supplier=req.supplier,
            invoice_number=req.invoice_number,
            notes=req.notes,
            recorded_by=user.username,
            timestamp=req.timestamp,
            idempotency_key=req.idempotency_key,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/adjustments", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
async def adjust_stock(
    req: FeedStockAdjustmentRequest,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_WRITE)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Record an authorized stock adjustment (damage, expiration, physical correction)."""
    verify_farm_access(user, farm_id)
    service = FeedInventoryService(session)
    try:
        return service.adjust_stock(
            farm_id=farm_id,
            product_id=req.product_id,
            adjustment_type=req.adjustment_type,
            quantity_kg=req.quantity_kg,
            reason=req.reason,
            notes=req.notes,
            recorded_by=user.username,
            timestamp=req.timestamp,
            idempotency_key=req.idempotency_key,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/transactions", response_model=List[Dict[str, Any]])
async def list_transactions(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    product_id: Optional[str] = Query(default=None, description="Filter by product ID"),
    transaction_type: Optional[str] = Query(default=None, description="Filter by transaction type"),
    pond_id: Optional[str] = Query(default=None, description="Filter by pond ID"),
    start_date: Optional[datetime] = Query(default=None, description="Start date filter"),
    end_date: Optional[datetime] = Query(default=None, description="End date filter"),
    limit: int = Query(default=50, ge=1, le=200, description="Max rows"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> List[Dict[str, Any]]:
    """List feed stock transactions audit history with filtering."""
    verify_farm_access(user, farm_id)
    service = FeedInventoryService(session)
    return service.list_transactions(
        farm_id=farm_id,
        product_id=product_id,
        transaction_type=transaction_type,
        pond_id=pond_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )

