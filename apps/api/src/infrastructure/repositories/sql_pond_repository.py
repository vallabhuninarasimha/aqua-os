"""SQL-backed implementation of IPondRepository."""

from typing import List, Optional

from sqlalchemy.orm import Session

from apps.api.src.domain.interfaces import IPondRepository
from apps.api.src.infrastructure.models import PondORM
from packages.telemetry_schema.config import PondConfig


class SQLPondRepository(IPondRepository):
    """Pond configuration repository backed by SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, farm_id: str, pond_id: str) -> Optional[PondConfig]:
        orm_pond = (
            self._session.query(PondORM)
            .filter(PondORM.farm_id == farm_id, PondORM.pond_id == pond_id)
            .first()
        )
        return orm_pond.to_domain() if orm_pond else None

    def list(self, farm_id: Optional[str] = None) -> List[PondConfig]:
        query = self._session.query(PondORM)
        if farm_id:
            query = query.filter(PondORM.farm_id == farm_id)
        records = query.order_by(PondORM.pond_id).all()
        return [r.to_domain() for r in records]

    def list_by_farm(self, farm_id: str) -> List[PondConfig]:
        return self.list(farm_id=farm_id)

    def get_by_id(self, farm_id: str, pond_id: str) -> Optional[PondConfig]:
        return self.get(farm_id=farm_id, pond_id=pond_id)

    def save(self, pond: PondConfig) -> PondConfig:
        existing = (
            self._session.query(PondORM)
            .filter(PondORM.farm_id == pond.farm_id, PondORM.pond_id == pond.pond_id)
            .first()
        )
        if existing:
            # Update existing pond attributes
            existing.name = pond.name
            existing.area_hectares = pond.area_hectares
            existing.depth_meters = pond.depth_meters
            existing.species = pond.species
            existing.stocking_density_per_m2 = pond.stocking_density_per_m2
            existing.days_of_culture = pond.days_of_culture
            existing.is_active = pond.is_active
            existing.aerator_count = pond.aerator_count
            existing.feeder_count = pond.feeder_count
            existing.area_acres = pond.area_acres
            existing.depth_feet = pond.depth_feet
            existing.stocking_count = pond.stocking_count
            existing.transformer_id = pond.transformer_id
            import json
            existing.thresholds_json = json.dumps(pond.thresholds.model_dump(mode="json"))
        else:
            # Insert new pond
            new_orm = PondORM.from_domain(pond)
            self._session.add(new_orm)

        self._session.commit()
        return pond

    def delete(self, farm_id: str, pond_id: str) -> bool:
        deleted = (
            self._session.query(PondORM)
            .filter(PondORM.farm_id == farm_id, PondORM.pond_id == pond_id)
            .delete()
        )
        self._session.commit()
        return deleted > 0

    def count(self, farm_id: Optional[str] = None, active_only: bool = False) -> int:
        query = self._session.query(PondORM)
        if farm_id:
            query = query.filter(PondORM.farm_id == farm_id)
        if active_only:
            query = query.filter(PondORM.is_active.is_(True))
        return query.count()
