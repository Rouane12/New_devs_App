from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any
from zoneinfo import ZoneInfo

from sqlalchemy import text


MONEY_QUANTUM = Decimal("0.01")


def round_money(value: Decimal) -> Decimal:
    """
    Round financial values to cents using conventional financial rounding.
    Rounding happens only after the exact Decimal total has been calculated.
    """
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


async def calculate_monthly_revenue(
    property_id: str,
    month: int,
    year: int,
    db_session=None,
    tenant_id: str = None,
) -> Decimal:
    """
    Calculate revenue for a property's calendar month in the property's
    own timezone.

    Reservation timestamps are stored in UTC, so the local month boundaries
    are converted to UTC before querying.
    """
    if tenant_id is None:
        raise ValueError("tenant_id is required for tenant-safe revenue queries")

    owns_session = db_session is None

    if owns_session:
        from app.core.database_pool import DatabasePool

        db_pool = DatabasePool()
        await db_pool.initialize()

        if not db_pool.session_factory:
            raise RuntimeError("Database pool not available")

        db_session = db_pool.get_session()

    try:
        async with db_session if owns_session else _null_async_context(db_session) as session:
            # Retrieve the property's timezone using BOTH property_id and tenant_id.
            timezone_query = text(
                """
                SELECT timezone
                FROM properties
                WHERE id = :property_id
                  AND tenant_id = :tenant_id
                """
            )

            timezone_result = await session.execute(
                timezone_query,
                {
                    "property_id": property_id,
                    "tenant_id": tenant_id,
                },
            )

            property_timezone = timezone_result.scalar_one_or_none()

            if property_timezone is None:
                return Decimal("0.00")

            property_tz = ZoneInfo(property_timezone)

            # Create month boundaries in the property's LOCAL timezone.
            local_start = datetime(
                year,
                month,
                1,
                tzinfo=property_tz,
            )

            if month == 12:
                local_end = datetime(
                    year + 1,
                    1,
                    1,
                    tzinfo=property_tz,
                )
            else:
                local_end = datetime(
                    year,
                    month + 1,
                    1,
                    tzinfo=property_tz,
                )

            # Database timestamps are timezone-aware, so compare in UTC.
            utc_start = local_start.astimezone(timezone.utc)
            utc_end = local_end.astimezone(timezone.utc)

            revenue_query = text(
                """
                SELECT COALESCE(SUM(total_amount), 0) AS total
                FROM reservations
                WHERE property_id = :property_id
                  AND tenant_id = :tenant_id
                  AND check_in_date >= :start_date
                  AND check_in_date < :end_date
                """
            )

            result = await session.execute(
                revenue_query,
                {
                    "property_id": property_id,
                    "tenant_id": tenant_id,
                    "start_date": utc_start,
                    "end_date": utc_end,
                },
            )

            total = result.scalar_one()

            # PostgreSQL NUMERIC remains exact through Decimal.
            exact_total = Decimal(str(total))

            return round_money(exact_total)

    finally:
        if owns_session:
            await db_pool.close()


class _null_async_context:
    """
    Small async context wrapper for an already-provided database session.
    """

    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


async def calculate_total_revenue(
    property_id: str,
    tenant_id: str,
) -> Dict[str, Any]:
    """
    Aggregate total revenue for a tenant-owned property.

    Tenant ID is always part of the query to preserve tenant isolation.
    Financial values remain Decimal until the final formatted result.
    """
    from app.core.database_pool import DatabasePool

    db_pool = DatabasePool()

    try:
        await db_pool.initialize()

        if not db_pool.session_factory:
            raise RuntimeError("Database pool not available")

        async with db_pool.get_session() as session:
            query = text(
                """
                SELECT
                    property_id,
                    SUM(total_amount) AS total_revenue,
                    COUNT(*) AS reservation_count
                FROM reservations
                WHERE property_id = :property_id
                  AND tenant_id = :tenant_id
                GROUP BY property_id
                """
            )

            result = await session.execute(
                query,
                {
                    "property_id": property_id,
                    "tenant_id": tenant_id,
                },
            )

            row = result.fetchone()

            if not row:
                return {
                    "property_id": property_id,
                    "tenant_id": tenant_id,
                    "total": "0.00",
                    "currency": "USD",
                    "count": 0,
                }

            # Keep the database NUMERIC value as Decimal.
            exact_total = Decimal(str(row.total_revenue))

            # Round exactly once, at the reporting boundary.
            rounded_total = round_money(exact_total)

            return {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "total": format(rounded_total, ".2f"),
                "currency": "USD",
                "count": row.reservation_count,
            }

    except Exception as e:
        # Do NOT silently return fake revenue when the real database fails.
        # A financial dashboard must fail visibly rather than display
        # potentially incorrect client data.
        print(
            f"Database error for {property_id} "
            f"(tenant: {tenant_id}): {e}"
        )
        raise

    finally:
        await db_pool.close()