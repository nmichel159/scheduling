# Endpoint Performance Optimization Plan

This checklist tracks the performance audit remediation. Changes must preserve
API response contracts and must not modify demo/seed data.

## Baseline audit

- [x] Map all 66 application routes (excluding documentation routes).
- [x] Run the complete backend test suite: 39 tests passed.
- [x] Record isolated query-count baselines:
  - `GET /users/by-role`: 403 SQL statements for 200 users.
  - employee competence list: 23 SQL statements for 20 competences.
  - ambulance competence-table save: 203 SQL statements for 200 employees.
  - ambulance monthly schedule save: 1,202 SQL statements for 200 entries.
  - ambulance employee list: 1 SQL statement for 200 employees.
  - ambulance monthly schedule read: 2 SQL statements for 200 entries.
- [x] Record solver baseline: 0.48 s for the current 33-employee case. A
  historical run of the old naive model builder took 13.09 s at 150 employees;
  this is build time, not CBC solve time.

## Phase 1 - database access paths

- [x] Add composite indexes for schedule user/date and ambulance/date reads.
- [x] Add a composite index for user/date unavailability reads.
- [x] Add reverse lookup indexes to association tables.
- [x] Add scoped lookup indexes for competences, ambulances, and users.
- [x] Add a backward-compatible Alembic migration.
- [x] Add metadata/migration regression tests and run all backend tests: 42
  tests passed after the index changes.
- [x] Apply revision `20260813_01` to the local PostgreSQL database and verify
  the indexed access paths with `EXPLAIN ANALYZE` on temporary 500,000-row
  schedule and unavailability tables. The temporary rows were dropped at the
  end of the transaction.

## Phase 2 - bulk write paths

- [x] Batch authorization and validation in `PUT /schedules/monthly`: 10 SQL
  statements including authorization for an unchanged month.
- [x] Batch validation in `PUT /ambulances/{ambulance_id}/schedule`: reduced
  from 1,202 to 8 SQL statements for 200 unchanged entries.
- [x] Batch existing-assignment loading in the ambulance competence-table save:
  reduced from 203 to 4 SQL statements for 200 unchanged employees.
- [x] Add query-count regression tests for all three bulk writes.
- [x] Add revision `20260813_02` with race-safe uniqueness for schedule entries,
  active user/date unavailability, and active ambulance/competence names. The
  migration performs its own duplicate preflight and changes no rows; local
  PostgreSQL had zero conflicts and advanced successfully to the new revision.

## Phase 3 - N+1 read paths

- [x] Optimize `GET /users/by-role` role and ambulance loading: bounded at 6
  SQL statements.
- [x] Optimize employee competence-list aliases: reduced from 23 to 2 SQL
  statements while preserving distinct missing-user and missing-membership
  errors.
- [x] Remove cross-ambulance row amplification from the competence table.
- [x] Batch `GET /ambulances/my-ambulance-competences`: bounded at 3 SQL
  statements.
- [x] Add result-size-independent query-count tests.

## Phase 4 - schedule generator

- [x] Index decision variables by competence/date and employee/date.
- [x] Keep all existing coverage, rest, availability, and fairness semantics.
- [x] Add scaling regression coverage. In the latest 150-employee rerun (16,200
  binary variables), model construction improved from 8.53 s with repeated
  scans to 0.37 s with indexing (22.7x). The complete optimized MILP run,
  including the CBC solve, took 0.989 s and produced 248 assignments. Earlier
  full optimized runs for 33, 60, 100, and 150 employees measured 0.27 s,
  0.41 s, 0.61 s, and 0.91 s respectively; timings vary between runs.
- [x] Add a configurable 30-second solver time limit with a distinct
  `solver_timeout` response.
- [x] Define background-job handling for large or concurrent generation
  requests without auto-saving the generated draft (design below).

## Phase 5 - payload limits and production observability

- [x] Add backward-compatible `after_id` cursor pagination to user, role, and
  ambulance employee listings; calls without pagination remain unchanged.
- [x] Add employee cursor pagination to the competence matrix and ambulance
  schedule; schedule queries fetch entries only for users on the selected page.
- [x] Add the same employee-ID cursor to the employees-by-competence lookup;
  validation plus the result page stays fixed at 2 SQL statements regardless
  of the qualification-group size.
- [x] Default unfiltered personal and manager schedule history reads to the
  current month while preserving explicit month/year filters.
- [x] Add stable `(after_date, after_id)` keyset pagination to unavailability
  listings; retain `skip` as a deprecated compatibility parameter.
- [x] Avoid blocking the async event loop during Google authentication by
  running the synchronous provider endpoint in FastAPI's threadpool.
- [x] Eager-load active session roles in the single token lookup so manager and
  admin guards do not trigger lazy authorization queries on every request.
- [x] Measure local PostgreSQL query plans plus endpoint p50/p95/p99 with 10,000
  synthetic users, 40,000 qualifications, 100,000 schedules, 100,000
  unavailability rows, and four concurrent HTTP requests. The isolated
  benchmark database was removed afterward.
- [ ] Repeat the HTTP benchmark in staging/production after deployment to
  include hosted network, worker, connection-pool, and platform effects. On
  2026-08-13 the public Render OpenAPI still exposed only 58 operations and
  lacked the new competence-employee cursor, while the local source exposes 66
  operations; benchmarking it now would measure the older deployment.

## Complete route-family audit

The final source audit covers all 66 application operations. Read endpoints
that can grow with employee, schedule, or unavailability volume are either
date-bounded or expose an indexed keyset cursor. Small organization codebooks
remain backward-compatible unpaginated lists, but use fixed query counts and
indexed ordering. Mutation latency was verified on isolated databases so the
demo data was not changed.

| Route family | Operations | Large-data result |
| --- | ---: | --- |
| Authentication | 2 | Indexed token lookup, roles eager-loaded, Google HTTP call runs outside the async event loop. |
| Unavailability | 7 | User/date index, 100-row default keyset pages, database uniqueness, constant-size CRUD. |
| Ambulance employees | 13 | Employee and matrix cursors, 1-query reads, bounded bulk validation and writes. |
| Ambulance competences | 5 | Managed groups use 3 queries; codebook list uses 2; CRUD is constant-size. |
| User competences | 4 | Per-user list uses 2 queries; employees-by-competence now uses 2-query cursor pages. |
| Users and assignments | 5 | User-ID cursors; role/ambulance eager loading has result-size-independent query counts. |
| Roles | 2 | Small fixed codebook; session roles are already loaded by authentication. |
| Ambulance administration | 8 | One indexed organization-codebook query; single-row writes have no result-size loop. |
| Public competence aliases | 4 | Reuse the same bounded competence service paths. |
| Employee-competence aliases | 3 | Reuse the same 2-query scoped assignment paths. |
| Schedules and generator | 12 | Month bounds, composite indexes, paged ambulance read, batched writes, indexed MILP variables and timeout. |
| Health | 1 | No database access. |
| **Total** | **66** | **All current application operations classified.** |

## PostgreSQL verification

- Local migration revision after the test: `20260813_02`.
- Persistent row counts before and after: 53 users, 230 schedules, 148
  unavailability rows. No demo rows were added, changed, or deleted.
- At the current small volume PostgreSQL correctly preferred sequential scans;
  measured query execution was 0.03-0.09 ms.
- With 500,000 temporary rows, PostgreSQL selected the new bitmap index paths:
  user-month schedule 0.083 ms, ambulance-month schedule 1.117 ms, and
  unavailability history 0.158 ms.

## Large-volume HTTP benchmark

Each endpoint received 50 measured requests after warmup, with concurrency 4.
Employee-oriented endpoints used a 100-employee cursor page.

| Endpoint | p50 | p95 | p99 |
| --- | ---: | ---: | ---: |
| `GET /users?limit=100` | 10.684 ms | 34.814 ms | 39.955 ms |
| `GET /users/by-role?...&limit=100` | 35.853 ms | 53.175 ms | 65.859 ms |
| Employee list | 14.810 ms | 17.145 ms | 26.646 ms |
| Employee competence matrix | 28.680 ms | 50.957 ms | 52.246 ms |
| Ambulance month, 100 employees / 1,000 entries | 91.395 ms | 133.338 ms | 149.027 ms |
| Personal month | 8.672 ms | 10.046 ms | 19.108 ms |
| Unavailability page | 7.467 ms | 22.388 ms | 23.332 ms |

The unbounded control responses demonstrate why clients should use the new
cursor: the full 10,000-employee competence matrix was 2.61 MiB / 0.389 s, and
the full 100,000-entry ambulance month was 29.27 MiB / 2.834 s. Existing calls
remain compatible, but large deployments should page these two screens.

## Complete GET endpoint benchmark

The read-only manifest now contains all 32 current application GET operations,
including compatibility aliases. An automated coverage test compares the
manifest to FastAPI's route table so a future GET operation cannot be silently
omitted. On the local PostgreSQL demo database, every operation returned its
expected `200` response for 30 measured requests after warmup at concurrency 4.
The five highest p95 values were:

| Endpoint | p50 | p95 | p99 | Optimization conclusion |
| --- | ---: | ---: | ---: | --- |
| Ambulance month (`limit=100`) | 127.168 ms | 140.975 ms | 147.569 ms | Slowest read, but already bounded to 2 SQL queries and employee cursor pages. |
| Users by role (`limit=100`) | 91.083 ms | 97.334 ms | 98.444 ms | Six bounded eager-load queries; no N+1 growth. |
| Employee competences | 57.355 ms | 70.243 ms | 72.537 ms | Two scoped queries; result is naturally bounded by one employee. |
| Ambulance employee page | 46.511 ms | 64.588 ms | 66.027 ms | One indexed query and a 500-row maximum page. |
| Competence codebook alias | 55.672 ms | 62.749 ms | 63.903 ms | Two queries including weekly requirements; small organization codebook. |

The newly audited employees-by-competence page measured p50 52.572 ms, p95
62.371 ms, and p99 69.023 ms. The single-record unavailability lookup, which
requires a record owned by the authenticated benchmark user, was measured in a
separate authenticated pass at p50 8.515 ms and p95 47.066 ms. No write method
was invoked during these HTTP measurements.

## Final local verification

- [x] Backend compile check completed.
- [x] Complete backend suite: 68 tests passed.
- [x] OpenAPI generated successfully against isolated SQLite: 45 path objects;
  the new pagination parameters are present.
- [x] Frontend ESLint passed.
- [x] Frontend production build passed (147 modules transformed).
- [x] `git diff --check` passed; only Windows line-ending notices remain.

## Background generation design

The synchronous generator remains the default while the measured 150-employee
case stays below one second. If production p95 exceeds five seconds or
concurrent generation causes worker saturation, move only the generation step
to a durable worker queue:

1. `POST .../schedule/generate` validates access and returns `202` plus a job
   ID; it never writes schedule rows.
2. Deduplicate active jobs by manager, ambulance, month, year, and input
   revision so repeated clicks do not enqueue duplicate solves.
3. A worker runs the existing bounded solver and stores the draft/error with a
   short TTL. Cancellation and the existing solver timeout remain enforced.
4. `GET .../schedule/generate/{job_id}` returns pending, completed draft, or
   structured error. The frontend must still show the completed draft for
   review and use the existing explicit save endpoint.

This queue should use shared durable storage in production, not an in-process
FastAPI background task, so jobs survive web-worker restarts and work across
multiple instances.
