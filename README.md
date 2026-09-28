# Property Revenue Dashboard — Debugging Assessment

This repository is my fork of the Base360.ai / The Flex practical assessment.

## Submission

**Solution branch:** [`fix/revenue-dashboard-bugs`](https://github.com/Rouane12/New_devs_App/tree/fix/revenue-dashboard-bugs)  
**Submitted solution commit:** [`c67bc058a`](https://github.com/Rouane12/New_devs_App/commit/c67bc058a0ecd2464d569a5ca3a74a9511056e06)

> The assessment solution itself is preserved on the branch and commit above. This README is documentation only.

## Assignment Summary

The task was to investigate and fix three reported problems in a multi-tenant property revenue dashboard:

1. March revenue totals did not match a client's internal records.
2. One client could sometimes see revenue that appeared to belong to another company.
3. Finance reported totals that were occasionally off by a few cents.

The exercise required debugging the existing system rather than rebuilding it.

## Root Causes and Fixes

### 1. Cross-tenant cache leakage

The revenue cache key originally used only the property ID:

```python
revenue:{property_id}
```

Property IDs are not globally unique across tenants, so two tenants using the same property ID could collide in Redis and receive the same cached result.

The cache key was changed to include the tenant ID:

```python
revenue:{tenant_id}:{property_id}
```

This keeps cached revenue isolated per tenant.

### 2. Incorrect monthly timezone boundaries

Monthly revenue boundaries were created as naive datetimes without using the property's configured timezone.

The seeded dataset includes an important edge case: a reservation stored at **2024-02-29 23:30 UTC** belongs to **March 1 in Europe/Paris**. A UTC-only month boundary incorrectly excludes it from March.

The fix:

- reads the property's timezone;
- creates the month start/end in that local timezone;
- converts those boundaries to UTC;
- queries the timezone-aware reservation timestamps using the converted range.

For the Paris property, March 2024 now correctly returns:

```text
2250.00
```

### 3. Financial precision

Revenue values come from PostgreSQL `NUMERIC`, but the API converted the total to a floating-point value.

The reporting path now keeps money as `Decimal`, performs exact aggregation, rounds once to cents using `ROUND_HALF_UP`, and returns a two-decimal formatted value without converting it back to a binary float.

### 4. Database-error fallback

The original revenue service silently returned property-specific mock revenue when the real database query failed.

For financial reporting, plausible-looking fallback revenue can hide a real system failure and mislead users. The fallback was removed so database failures remain visible instead of returning fabricated totals.

## Local Challenge Environment Fixes

While validating the assignment against the real seeded database, I also corrected local challenge-mode plumbing so the supplied environment could use its actual PostgreSQL data:

- the async SQLAlchemy pool now uses the provided `DATABASE_URL`;
- the PostgreSQL URL is converted to the `asyncpg` dialect;
- `greenlet` was added to backend requirements;
- challenge-mode JWT authentication can validate the provided local test accounts without depending on unavailable Supabase configuration.

These changes allowed the reported bugs to be verified against the seeded PostgreSQL data instead of mock fallback values.

## Validation

The fixes were tested against both tenants and multiple seeded properties.

| Tenant | Property | Revenue | Reservations |
| --- | --- | ---: | ---: |
| Sunset Properties (`tenant-a`) | `prop-001` | `2250.00` | 4 |
| Ocean Rentals (`tenant-b`) | `prop-001` | `0.00` | 0 |
| Sunset Properties (`tenant-a`) | `prop-002` | `4975.50` | 4 |
| Ocean Rentals (`tenant-b`) | `prop-004` | `1776.50` | 4 |

The identical `prop-001` request returning different, correct results for the two tenants confirms that tenant isolation is preserved.

Additional checks completed:

```text
git diff --check
docker-compose exec backend python -m compileall app
```

Both completed without errors.

## Files Changed in the Submitted Solution

- `backend/app/api/v1/dashboard.py`
- `backend/app/core/auth.py`
- `backend/app/core/database_pool.py`
- `backend/app/services/cache.py`
- `backend/app/services/reservations.py`
- `backend/requirements.txt`

## Running the Project

```bash
docker-compose up --build
```

Then open:

- Frontend: `http://localhost:3000`
- Backend Swagger UI: `http://localhost:8000/docs`

## Walkthrough

A video walkthrough demonstrating the investigation, root causes, fixes, and final validation was submitted through the assessment portal together with the repository details.

---

Practical assessment completed for Base360.ai / The Flex.
