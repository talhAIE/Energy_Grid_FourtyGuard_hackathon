"""Deactivate all GRID_* zones and restore the 8 named Houston zones with correct weights."""

from decimal import Decimal

from sqlalchemy import select

from app.db.database import get_session_factory
from app.db.models.zone import Zone


HOUSTON_ZONE_WEIGHTS = {
    "KATY_WEST": Decimal("0.15"),
    "ENERGY_CORRIDOR": Decimal("0.12"),
    "GALLERIA_UPTOWN": Decimal("0.12"),
    "DOWNTOWN": Decimal("0.12"),
    "MEDICAL_CENTER": Decimal("0.10"),
    "EAST_HOUSTON": Decimal("0.12"),
    "PORT_HOUSTON": Decimal("0.15"),
    "NORTH_HOUSTON": Decimal("0.12"),
}


def fix_zones() -> None:
    """Deactivate GRID_* zones and restore allocation weights for the 8 named zones."""
    session_factory = get_session_factory()

    with session_factory() as session:
        # Deactivate all GRID_* zones
        grid_zones = session.scalars(
            select(Zone).where(Zone.code.like("GRID_%"))
        ).all()
        deactivated_count = 0
        for zone in grid_zones:
            if zone.active:
                zone.active = False
                deactivated_count += 1

        # Ensure all 8 named Houston zones are active with correct weights
        activated_count = 0
        weight_fixed_count = 0
        for code, correct_weight in HOUSTON_ZONE_WEIGHTS.items():
            zone = session.scalar(select(Zone).where(Zone.code == code))
            if zone is not None:
                if not zone.active:
                    zone.active = True
                    activated_count += 1
                if Decimal(zone.allocation_weight) != correct_weight:
                    zone.allocation_weight = correct_weight
                    weight_fixed_count += 1

        session.commit()

        # Report
        active_zones = session.scalars(
            select(Zone).where(Zone.active.is_(True)).order_by(Zone.code)
        ).all()
        total_weight = sum(Decimal(z.allocation_weight) for z in active_zones)

        print(f"Deactivated {deactivated_count} GRID_* zone(s).")
        print(f"Re-activated {activated_count} named zone(s).")
        print(f"Fixed weights on {weight_fixed_count} zone(s).")
        print(f"Total active zones: {len(active_zones)}")
        print(f"Total allocation weight: {total_weight}")
        for zone in active_zones:
            print(f"  - {zone.code}: {zone.name} (weight={zone.allocation_weight})")


if __name__ == "__main__":
    fix_zones()
