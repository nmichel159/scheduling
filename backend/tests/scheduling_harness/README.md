# Scheduling test harness

An independent harness for testing the monthly schedule generator
(`app/services/schedule_generation_service.py`). It builds problem instances,
runs the solver, judges the rosters without using the solver's own helpers,
cross-checks feasibility and optimality a second way, and replays everything
through the database loader.

```
from tests.scheduling_harness.instances import make_instance, Knobs, sample_knobs
from tests.scheduling_harness.runner import run_solver
from tests.scheduling_harness.oracle import validate
```

Run tests from `backend/` with the project venv:
`venv/Scripts/python.exe -m pytest tests/<file>.py`. Style: `unittest.TestCase`,
English docstrings, type hints. Never modify `backend/app/`. If the solver looks
wrong, write a minimal test marked `@unittest.expectedFailure` with a docstring
explaining the suspected bug. Check `known_bugs.py` first, because it may
already be listed.

The self-check `tests/test_harness_selfcheck.py` proves the harness right
(53 tests, 9 expected failures, about 1 minute). Run it after changing anything here.

## Vocabulary

| Term | Meaning |
|---|---|
| Duty | `(user_id, competence_id, work_date)`; type alias `Duty` in `semantics` |
| Holds | A duty on `e` with rest `r` holds days `e .. e+r` |
| Collide | Two duties on different days collide when the later starts on a day the earlier still holds |
| Generated duty | A duty in the output that is not a manual placement (`instance.fixed`) |
| Window | Days `>= generate_from` (the whole month when it is `None`) |
| History | Days before `generate_from`; there the output must equal the placements exactly |
| Outside duties | `instance.adjacent` (this workplace, within 7 days outside the month) and duties elsewhere (`externally_scheduled_dates`) |
| Witness | A hidden roster known to satisfy every hard rule (planted instances only) |

Rest of a duty:
- At this workplace: `competence.recovery_days_on(date)`.
- For a competence the workplace no longer has: 1 (`UNKNOWN_COMPETENCE_REST`).
- Elsewhere: the longest explicit rest given for that date in `external_commitments`. If none is given, the longest `recovery_days_on(date)` over this workplace's competences. The order of entries never matters (see known bug `duplicate_external_dates`).

## Modules at a glance

| Module | Purpose |
|---|---|
| `semantics` | Shared rule definitions (rest, collisions, demand, ladders). No solver helpers. |
| `instances` | `Instance`, `Knobs`, `make_instance`, samplers, ready-made instances, `random_policy` |
| `oracle` | `validate`, `metrics`, `first_pass_cost`, `day_wish_cost`, `eligible`, `find_improving_moves` |
| `reference` | `reference_feasibility` (an independent MILP of the hard rules) and `brute_force` (exhaustive search for tiny cases) |
| `runner` | `run_solver` (optionally *observed*), `solve_in_parallel` |
| `db_builder` | `materialize` writes an instance into SQLite rows. `run_db_solver` solves it through `generate_ambulance_monthly_schedule`. |
| `scenarios` | `repair` (greedy fill-in), `regenerate` (mid-month change), `chain_next_month` / `chain_months` |
| `known_bugs` | `KNOWN_BUGS`, `known_bug_triggers`, `db_bug_triggers` |

---

## instances

### `Instance` (dataclass)

Fields:
- `employees: list[SchedulingEmployee]`
- `competences: list[SchedulingCompetence]`
- `month: int`, `year: int`
- `adjacent: frozenset[Duty]`
- `fixed: frozenset[Duty]` (manual placements, in-month)
- `generate_from: date | None`
- `policy: ConstraintPolicy | None` (`None` means all defaults)
- `witness: frozenset[Duty] | None`
- `label: str`
- `knobs: dict` (the knobs as a dict, plus `"seed"` and `"spares"`)

Properties:
- `days`, `day_set`, `window_days`, `history_days`
- `employee_map`, `competence_map`
- `special_dates`
- `effective_policy` (the policy with defaults filled in)
- `spares: int` (fully qualified employees the planter had to add)

`solver_kwargs() -> dict` returns the keyword arguments for `solve_monthly_schedule`, without the time budget.

Instances are plain dataclasses. Use `dataclasses.replace(instance, ...)` to vary one.

### `make_instance(seed: int, knobs: Knobs | None = None, carry_in: Iterable[Duty] = ()) -> Instance`

Deterministic in every interpreter, whatever `PYTHONHASHSEED` is.
- **Random** (`planted=False`): every input is drawn independently. The instance may be infeasible.
- **Planted** (`planted=True`): demand first, then a greedy witness satisfying every hard rule of the policy, then absences, wishes, externals, maxima, adjacent duties and placements, each added only where it cannot break the witness. **The solver must never call a planted instance infeasible.** Construction ends with `validate(witness) == []`, or the call raises `AssertionError`.
- If the greedy fill keeps failing, the planter adds one fully qualified, wish-free spare employee every 20 failed attempts (ids `n_employees+1, ...`). They appear in `instance.spares` and as `-spN` in the label. With `knobs.max_spares` set, exceeding it raises `PlantingFailed`; catch it and skip the seed.
- Structure has its own random stream: the competences, their 8 slots and who holds what. The same seed and knobs in another month give the same workplace. Calendar, absences, fill and decorations have per-month streams.
- `carry_in`: duties from a neighbouring month at this workplace. Those within 7 days outside the month become `adjacent`, and the witness respects their rest. Random adjacent duties are then drawn after the month only. Carried duties of unknown users are dropped.

### `Knobs` (dataclass; every field has a default)

| Knob | Default | Allowed values / meaning |
|---|---|---|
| `n_employees` | 8 | int |
| `n_competences` | 2 | int (competence ids are `1..n`) |
| `month`, `year` | 8, 2026 | any; Feb 2028 is a leap month, 31-day months are fine |
| `qualification_density` | 0.75 | chance per employee and role (`iid` structure) |
| `unqualified_employee_rate` | 0.0 | chance an employee holds nothing |
| `qualification_structure` | `"iid"` | `iid` \| `hierarchy` (35 % seniors hold all, juniors one) \| `rare` (role 1 held by only 1-2 people) |
| `demand_profile` | `"flat"` | `flat` (1 each slot) \| `weekday` (1-2 weekdays, 0-1 weekend and special) \| `sparse` (0/1, some zero days) \| `heavy` (1-3) \| `mixed` (one of those per role) |
| `target_utilization` | None | e.g. 0.5 / 0.8 / 0.95: non-zero counts are rescaled to that share of rough staff capacity (Σ over holders of 1/(roles held × (1+mean rest)) ±15 %). This is how you get 5-10 people per role per day. |
| `zero_demand_competences` | 0 | the last N roles ask for nobody all month |
| `special_days` | `"none"` | `none` \| `library` (Slovak public holidays) \| `random` (each day with `special_rate`) \| `mixed` (library minus ~40 % plus random) |
| `special_rate` | 0.08 | used by `random`/`mixed` |
| `special_slot_differs` | True | False copies Sunday's slot into the special slot |
| `recovery_profile` | `"one"` | `zero` \| `one` \| `mixed` (0-3 per slot) \| `long` (2-6 per slot) |
| `hours_profile` | `"uniform4"` | `uniform4` \| `uniform12` \| `mixed` (4/8/12/24) \| `fractional` (4.5/6.25/7.5/12) |
| `surcharge_profile` | `"weekend"` | `weekend` (Sat, Sun, special) \| `random` \| `none` \| `all` |
| `unavailability_rate` | 0.0 | chance per employee and day of a single absence |
| `absence_mix` | (1,0,0) | weights of (UNAVAILABLE, VACATION, BUSINESS_TRIP) for single absences |
| `vacation_block_rate` | 0.0 | chance per employee of one contiguous 3-14-day absence, drawn **before** the witness |
| `block_mix` | (0.1,0.6,0.3) | rule weights for blocks, same order |
| `block_cluster` | False | all blocks start within the same 5 days (holiday crowd) |
| `preferred_rate`, `soft_decline_rate` | 0.0 | chances per day of "want to" / "rather not" |
| `wish_pattern` | `"iid"` | `iid` \| `weekday` (likes 1-3 weekdays, declines on one other) \| `crowd` (everyone wants the same ~5 dates, specials first, and avoids the same 3) |
| `max_shifts_mode` | `"none"` | `none` (None) \| `zero` (0 = no limit) \| `loose` (base+1..4) \| `tight` (base) \| `below` (base-1..3) \| `hetero` (40 % part-timers at 0.4×avg, others 1.4×avg) \| `starved` (0.6×avg) \| `mixed` (per person). Base is the witness load (planted) or window average plus the person's own history placements (random). Under a **strict** `max_shifts` a planted cap never drops below the witness load. |
| `preference_mix` | `"any"` | `any` \| `surcharge` \| `standard` \| `mixed` |
| `external_rate` | 0.0 | chance per employee and day (month ±7 days) of a duty elsewhere |
| `external_explicit_rest` | 1.0 | share of those that carry their own rest (0-3); the rest use the fallback |
| `external_duplicate_rate` | 0.0 | chance that an explicit one gets a second entry on the same date with another rest, in random order (triggers known bug `duplicate_external_dates`) |
| `adjacent_rate` | 0.0 | chance per needed person and day of a duty within 7 days outside the month |
| `adjacent_retired_competence` | False | 25 % of those in `RETIRED_COMPETENCE_ID` (900), a role the workplace no longer has (rest 1) |
| `generate_from` | None | None \| day of month (int) \| `"mid"` (random day 8..len-5) |
| `keep_history` | 1.0 | share of history duties kept as placements |
| `n_fixed` | 0 | number of single witness duties in the window pinned as placements |
| `fixed_share` | 0.0 | share of the witness's window duties pinned (fill-in) |
| `fixed_full_days` | 0 | whole window days whose every duty is pinned |
| `n_breaking_fixed` | 0 | placements that break a rule on purpose |
| `breaking_kinds` | all five | subset of `two_roles`, `inside_rest`, `unqualified`, `absence`, `above_demand` |
| `policy` | None | `{code: (strict, weight)}` passed through `policy_from_settings`; see `POLICY_PRESETS`, `random_policy` |
| `planted` | False | see above |
| `witness_keeps_rest` | True | planted under a penalized rest: False lets the witness, and duties elsewhere, break rest |
| `max_spares` | None | planted only: limit on spare employees (`PlantingFailed` beyond it) |

### Samplers and ready-made instances

| Function | Use |
|---|---|
| `sample_knobs(rng, size="small", planted=True) -> Knobs` | Random knobs over every dimension. `SIZES`: `small` 4-10 employees and 1-2 roles; `medium` 10-25 and 2-4; `large` 25-60 and 3-6; `xl` 60-80 and 6-8. 75 % preset policies, 25 % `random_policy(allow_zero_balance=False)`. Duplicate externals are off. |
| `tiny_knobs(rng, planted) -> Knobs` | 3-5 employees, 1-2 roles, window = last 4-7 days. Planted sets `max_spares=0` so the brute force stays at ≤5 people; catch `PlantingFailed` (about 20 % of seeds). 30 % random policies, zero balance included. |
| `ultra_tiny_knobs(rng, planted) -> Knobs` | 2-3 employees, window = last 2-3 days (pruning-free enumeration) |
| `stress_knobs(rng, planted=True) -> Knobs` | 2-5 employees, 1-8 rule-breaking placements, tight maxima; usually needs spares |
| `fill_in_knobs(rng, share=None, size="small") -> Knobs` | Planted, `fixed_share` 0.3-0.9, sometimes whole days pinned and a history |
| `random_policy(rng, allow_zero_balance=True, keep_default_share=0.3) -> dict` | Every switchable rule strict or penalized with weight from `{0, 0.5, 1, 10, 1000}`; balance `{0, 0.5, 1, 4, 40}`, preferred `{0, 1, 10, 100}`, spread `{0, 0.5, 1, 5}` |
| `POLICY_PRESETS: dict[str, dict]` | `default`, `strict_load`, `strict_wishes`, `strict_everything`, `penalized_absences`, `penalized_rest`, `penalized_all`, `cheap_penalties`, `heavy_balance`, `silent_wishes` |
| `symmetric_instance(n_employees, n_competences, month=8, year=2026, recovery=1, hours=4.0) -> Instance` | Identical employees, 1 per role per day: fair loads differ by ≤ 1 |
| `pigeonhole_instance() -> Instance` | Plainly infeasible: 2 per day in a role one person holds |
| `unconfigured_competence(competence_id, required_count, special=frozenset()) -> SchedulingCompetence` | Exactly what the DB loader reads for a role with no scenario rows (for `materialize(scenario="none")`) |
| `knobs_of(instance) -> Knobs`, `next_month_knobs(knobs) -> Knobs` | Recover knobs; the same knobs one month later (Dec → Jan of the next year) |

Constants: `RETIRED_COMPETENCE_ID = 900`, `ABSENCE_RULES`, `MAX_SHIFT_MODES`, `SIZES`.

```python
import random
from dataclasses import replace
from tests.scheduling_harness.instances import Knobs, make_instance, sample_knobs, PlantingFailed

inst = make_instance(7, Knobs(n_employees=12, n_competences=3, recovery_profile="mixed",
                              vacation_block_rate=0.3, wish_pattern="crowd", preferred_rate=0.1,
                              max_shifts_mode="hetero", generate_from="mid", n_fixed=4,
                              policy={"max_shifts": (True, 1000.0)}, planted=True))
assert inst.witness is not None

knobs = sample_knobs(random.Random(42), "medium", planted=False)       # random: may be infeasible
big = make_instance(3, replace(sample_knobs(random.Random(3), "xl"), target_utilization=0.9))
```

---

## oracle

### `validate(instance, assignments) -> list[Violation]`

`assignments` is an iterable of `GeneratedAssignment` or `(user_id, competence_id, date)` tuples. `Violation(code: str, detail: dict)`; `violation_codes(violations) -> set[str]`. `VIOLATION_CODES` lists every code.

| Code | When | `detail` keys |
|---|---|---|
| `malformed` | Duplicate tuple, a date outside the month, an unknown user, or an unknown competence | `kind` (`duplicate`/`outside_month`/`unknown_user`/`unknown_competence`), `duty` |
| `fixed_missing` | An in-month placement is missing from the output (also in the history) | `duty` |
| `history_changed` | A generated duty before `generate_from` | `duty` |
| `coverage` | On window days only: `n < demand`, or `n != demand` when OVERSTAFF is strict. `demand = max(required_on(d), placements of (k, d))`. A generated duty where `required_on(d) == 0` is a violation with `kind="zero_day"`. | `competence_id`, `work_date`, `staffed`, `demand` [, `kind`] |
| `unqualified` | A generated duty in a role the employee does not hold | `duty` |
| `double_role` | An employee has more duties on a date than `max(1, own placements that date)` | `user_id`, `work_date`, `duties` |
| `other_workplace` | A generated duty on an `externally_scheduled_dates` day (always hard) | `duty` |
| `rest` | Only when REST is strict. A collision on different days where at least one of the two duties is generated. Placements, adjacent duties and duties elsewhere may collide among themselves. | `user_id`, `earlier`, `later` (a duty, or `("outside", date)`), `earlier_rest` |
| `absence` | A generated duty on an absence whose rule (`absence_rules`, default UNAVAILABLE) is strict | `duty`, `rule` |
| `soft_decline` | A generated duty on a "rather not" day when SOFT_DECLINE is strict | `duty` |
| `max_shifts` | When MAX_SHIFTS is strict and the cap is truthy: in-month duties `> max(cap, own placements)` | `user_id`, `duties`, `limit` |

A penalized rule is never a violation. It shows up in `metrics` and `first_pass_cost`.

### `eligible(instance, user_id, competence_id, work_date, schedule) -> bool`

Whether a generated duty may be added given the user's duties in `schedule`. It checks every per-person rule: the window, non-zero demand, qualification, not elsewhere, strict absence and "rather not", one duty a day, strict rest against everything, and a strict cap. Coverage is the caller's business. `eligible_slots(instance, user_id) -> set[(k, date)]` returns the slots a user could ever hold, ignoring other generated duties.

### `metrics(instance, assignments) -> ScheduleMetrics`

Fields:
- `loads: dict[uid, EmployeeLoad(total, surcharge, standard, hours)]`
- `eligible_employees` (people with at least one slot or a placement)
- Among eligible employees: `load_spread`, `load_stdev`, `hours_spread`, `surcharge_spread`
- `overstaff` (people beyond demand, summed)
- `over_max: dict[uid, excess]`
- `absence_breaches: dict[rule, n]` (generated duties on penalized absences)
- `rest_breach_pairs`
- `rest_breach_days`: exactly what a penalized rest is charged for; it equals the rest part of `first_pass_cost` divided by the weight
- `rest_overlap_pair_days`: the sum over colliding pairs of the days both hold, past the month too
- `soft_declined_worked`, `preferred_honored`, `preferred_opportunities`
- `gap_histogram: dict[gap_days, n]`, `min_gap`, `tightest_gaps` (gap == rest + 1), `per_employee_gaps`

### Objective

- `first_pass_cost(instance, assignments) -> float`. It equals the solver's real first-pass objective, with no offset (verified with observed runs). Per employee, four convex ladders scaled by `weight(BALANCE)/4`:
  - total, unit 4
  - surcharge and standard, unit 3/5 by `shift_preference`, 4 for `any`
  - hours, unit 4, step = mean demanded duty length over the window

  Ladder cost of a load of `q` steps is `unit·(⌊q⌋² + (2⌊q⌋+1)(q−⌊q⌋))`. On top come:
  - penalized MAX_SHIFTS excess × weight
  - penalized OVERSTAFF excess × weight
  - generated duties on penalized absences × the rule's weight (placements are never charged)
  - penalized rest × `rest_breach_days`

  `CostModel(instance)` exposes `.employee_cost(uid, duties)`, `.overstaff_cost(duties)` and `.total(duties)`.
- `day_wish_cost(instance, assignments) -> float` is `−weight(PREFERRED)·preferred duties + weight(SOFT_DECLINE)·soft-declined duties`. The soft-decline term is 0 when strict, and placements are included (a constant). `day_wish_weights(instance) -> (preferred, soft)`.
- Compare two rosters' first-pass costs with the solver's lock slack, not 1e-6: `semantics.balance_lock_slack(reached) = 1e-4 + 1e-7·|reached|`.

### `find_improving_moves(instance, assignments, max_checks=20000, seed=0, balance_cap=None) -> list[Move]`

Tries reassignments (one generated duty to someone else), drops (a generated duty above demand) and swaps. Only moves that keep `validate` clean are considered. It raises `ValueError` if the roster is invalid. `Move(kind, removed, added, first_pass_delta, day_wish_delta, reason)`, where `reason` is one of:
- `first_pass`: lowers the first-pass cost by more than the lock slack. An optimal first pass cannot leave this, so it is a finding **unless the run hit its time budget**.
- `lock_drift`: lowers it by more than 1e-6 but no more than the slack. This is the known bug `balance_lock_drift`, not a new finding.
- `day_wish`: stays within the lock and gains at least `wish_threshold(instance)` in day wishes, which proves a second-pass miss. Pass `balance_cap=outcome.balance_cap` from an observed run so the lock is judged exactly. Moves touching people whose placements clash are skipped.

---

## reference

### `reference_feasibility(instance, time_limit=60, clique_cuts=True) -> (status, roster)`

An independently written PuLP/CBC model of only the hard rules:
- Candidates are filtered up front.
- One duty a day is a per-day bound.
- Rest is written as pairwise exclusions, plus per-day clique cuts under strict rest, which change no verdict (self-checked).

`status` is `'feasible'` with a roster (validated), `'infeasible'` with `None`, or `'unknown'` with `None` on a CBC timeout. **Treat `'unknown'` as a failed confirmation, never as a pass.** Measured with the cuts, 16 in parallel: medium ≤ 1 s, long rests included. Large takes 0.2-31 s and xl 0.5-47 s; the slowest are long rests. Give large and xl `time_limit=120`.

### `brute_force(instance, node_limit=2_000_000) -> BruteForceResult`

Exhaustive DFS over window slots for tiny instances (≤5 people, ≤2 roles, ≤7-day window). It prunes on the partial first-pass cost and breaks ties on day wishes.

`BruteForceResult` fields:
- `complete: bool` (False when a node was refused)
- `feasible: bool`
- `best_cost: float | None` (minimum `first_pass_cost`)
- `best_wish: float | None` (minimum `day_wish_cost` among those)
- `best_schedule`
- `nodes`
- `wish_slack`: how far the solver's wish cost may legitimately sit above `best_wish`, which is `n_employees·weight(SPREAD) + second-pass tolerance`. The brute force ignores the spread term.

`brute_force_size(instance) -> int` is the number of slots to fill (a rough cost estimate).

```python
from tests.scheduling_harness.oracle import day_wish_cost, first_pass_cost
from tests.scheduling_harness.reference import brute_force
from tests.scheduling_harness.runner import run_solver
from tests.scheduling_harness.semantics import balance_lock_slack
outcome = run_solver(inst, 5, observe=True)
best = brute_force(inst, node_limit=200_000)
if best.complete and best.feasible and outcome.status == "ok" and not outcome.hit_budget:
    cost = first_pass_cost(inst, outcome.assignments)
    assert cost <= best.best_cost + balance_lock_slack(best.best_cost)
    if abs(cost - best.best_cost) <= 1e-6:
        assert day_wish_cost(inst, outcome.assignments) <= best.best_wish + best.wish_slack
```

---

## runner

### `run_solver(instance, time_budget_seconds=30, observe=False) -> SolveOutcome`

`SolveOutcome` fields:
- `status`: `'ok'` | `'infeasible'` (ScheduleGenerationError) | `'timeout'` (an issue with code `solver_timeout`) | `'error'` (any other exception; always a finding)
- `assignments: list[Duty]`
- `issues: list[dict]`
- `seconds`
- `error: str | None`
- `budget`
- `passes: list[PassRecord]`

Properties: `issue_codes`, `hit_budget`, `first_pass`, `second_pass`, `first_pass_objective`, `balance_cap` (`reached + lock slack`).

`observe=True` wraps the solver's CBC call and records each pass without judging anything: `PassRecord(kind='balance'|'wishes', objective, sol_status, time_limit, close_enough)`, with `.optimal` and `.stopped_early`. PuLP's `sol_status` is 1 optimal, 2 feasible when the time limit hit, 0 none, -1 infeasible. With observation, `hit_budget` is exact (some pass stopped early). Without it, `hit_budget` is guessed from wall time (≥ 90 % of the budget). `second_pass is None` means the solver skipped its wish pass.

### `solve_in_parallel(instances, time_budget_seconds=30, workers=16, observe=False) -> list[SolveOutcome]`

Runs instances in a process pool and returns outcomes in input order. CBC is single-threaded and the machine has 32 cores; keep `workers ≤ 16` so wall-clock budgets keep their meaning.

### Typical solver times (planted, 16 in parallel, 30 s budget)

| Size | Median | p90 | First pass stopped at budget | Suggested budget |
|---|---|---|---|---|
| tiny (3-5 people) | 0.2 s | 0.2 s | 0 % | 5 s |
| small (4-10) | 0.4 s | 6 s | ~5 % | 10-20 s |
| fill-in (medium, 30-90 % pinned) | 0.5 s | 2 s | ~5 % | 10-20 s |
| medium (10-25) | 18 s | 31 s | ~25 % | 30-60 s |
| large (25-60) | 26 s | 32 s | ~20 % | 60-120 s, or check validity only |
| xl (60-80) | 13 s | 32 s | ~40 % | 60-120 s, or check validity only |

The solver overruns its budget by about 1 s: the second pass always gets at least 1 s. Small instances with a cheap penalized rest (weight 0.5) and a high spread weight can still take more than 30 s to prove the first pass. **Before reporting any optimality finding, check `outcome.hit_budget` (observed runs).** Validity, coverage and "planted is never infeasible" hold regardless of the budget.

---

## db_builder

- `fresh_session()` is a context manager yielding an empty in-memory SQLite session with all tables.
- `materialize(instance, session, ambulance_name="Target", *, scenario="full", external_fallback="explicit", foreign_calendar=False, retired_recovery=None, noise=False) -> DbWorld` writes rows: Ambulance, Users (max shifts, preference), memberships, Competences, a selected scenario with all 8 slots, qualifications, Unavailability (UNAVAILABLE/VACATION/BUSINESS_TRIP per rule, PREFERRED, SOFT_DECLINE), adjacent Schedule rows, duties elsewhere at a second workplace, ConstraintSetting rows, and SpecialDay overrides. `rest_days_between` over the month ±7 then equals the instance's special dates. Options:
  - `scenario`: `full`; `no_special_slot` (slot 7 omitted, so the loader answers like Sunday; the instance's special slot must equal Sunday's); `none` (no scenario; every competence must equal `unconfigured_competence(...)`).
  - `external_fallback`: `explicit` writes a fallback-rest duty elsewhere in a competence earning exactly that rest. `unconfigured` puts it at a third workplace with no scenario, which triggers the known bug `unconfigured_external_rest`. A date with two explicit rests gives two Schedule rows, in entry order.
  - `foreign_calendar`: the second workplace gets its own rest-day overrides, and per-slot rests, so the loader must read the right slot from the right calendar.
  - `retired_recovery`: scenario rows for the deactivated competence used by adjacent duties in unknown roles (known bug `retired_competence_rest` if ≠ 1).
  - `noise`: inactive users, memberships, qualifications, absences and duties, an unselected scenario with garbage, and an unknown rule code. The loader must ignore all of it.
  - Raises `InexpressibleInstance` for things the application cannot store: two day records for one person and date, records outside the month, adjacent duties inside the month or more than 7 days out, slot values that differ within one slot, or values the scenario mode cannot express.
- `DbWorld` fields: `ambulance_id`, `external_ambulance_id`, `unconfigured_ambulance_id`, `user_ids` / `user_back`, `competence_ids` / `competence_back` (instance id ↔ db id). Methods: `to_instance_tuples(entries) -> list[Duty]` (response entries or db-id tuples) and `fixed_entries_for_db(instance)`.
- `run_db_solver(instance, time_budget_seconds=30, session_factory=fresh_session, **materialize_options) -> SolveOutcome` solves through `generate_ambulance_monthly_schedule`. An id translation failure gives `status='error'`.
- `slot_values(competence, span)`, `unconfigured_slots(required_count)` and `calendar_span(instance)` are helpers.

To see exactly what the loader hands the solver, patch `app.services.schedule_generation_service.solve_monthly_schedule` and capture its arguments. `test_harness_selfcheck._capture_solver_input` and `DbRoundTripTests._compare` do this; copy them.

---

## scenarios (fill-in, regeneration, chaining)

- `repair(instance, start=(), seed=0, attempts=30) -> frozenset[Duty] | None` keeps the placements, keeps whatever of `start` still fits, then fills each gap with the least-loaded eligible person. It returns a valid roster, or `None`. `None` says nothing about feasibility; use `reference_feasibility` for that.
- `regenerate(instance, roster, generate_from, change="none", seed=0, plant=True) -> Instance` builds the mid-month re-generation. The roster's duties before `generate_from` become placements (history), and so do the instance's placements in the window. Then one `change` from `CHANGES` is applied:
  - `none`
  - `absence`: a strict absence on someone's generated duty
  - `vacation_block`: a 3-7-day VACATION from such a duty
  - `lower_max`: the busiest person's cap becomes their total − 2
  - `leave`: the busiest person is absent for the rest of the month
  - `demand_up`: +1 on one slot

  With `plant=True`, `witness = repair(changed, roster)` when one is found. If it is found, the solver must not call the month infeasible.
- `chain_next_month(instance, roster, seed=None, knobs=None) -> Instance` builds the next month: the same workplace, with the roster's last week carried in as adjacent duties that the witness respects. `chain_months(seed, knobs, n_months, solve) -> list[(Instance, roster | None)]` solves consecutive months. `solve` returns a roster or `None`, and `None` stops the chain. `carried_week(instance, roster)` is a helper. Only the previous month is carried, one-way.

```python
import random
from tests.scheduling_harness.instances import Knobs, fill_in_knobs, make_instance
from tests.scheduling_harness.oracle import validate
from tests.scheduling_harness.scenarios import regenerate, chain_months
from tests.scheduling_harness.runner import run_solver

inst = make_instance(5, fill_in_knobs(random.Random(5), share=0.7))     # 70 % pre-filled
out = run_solver(inst, 15, observe=True)
assert out.status == "ok" and validate(inst, out.assignments) == []

changed = regenerate(inst, out.assignments, inst.days[14], "leave", seed=1)
again = run_solver(changed, 15)
if changed.witness is not None:
    assert again.status == "ok"
assert {d for d in again.assignments if d[2] < inst.days[14]} == {d for d in changed.fixed if d[2] < inst.days[14]}

chain = chain_months(3, Knobs(month=12, year=2027, n_employees=12, recovery_profile="long", planted=True), 3,
                     lambda i: (o := run_solver(i, 10)).assignments if o.status == "ok" else None)
```

---

## Known solver bugs (`known_bugs.py`)

Each bug has a minimal `expectedFailure` test in `KnownSolverBugTests` in the self-check. An "unexpected success" there means the bug was fixed. Use `known_bug_triggers(instance) -> set[str]` (in-memory) or `db_bug_triggers(instance, **materialize_options)` (database) to tally, skip or `expectedFailure` affected instances instead of rediscovering them. A trigger means "may", not "will".

| Key | Status | Surface | What |
|---|---|---|---|
| `duplicate_external_dates` | confirmed | in-memory and DB | Two `(date, rest)` entries for one day elsewhere: `dict(external_commitments)` keeps the last one, so strict rest is broken depending on entry or row order |
| `zero_balance_skips_wishes` | confirmed | in-memory | `BALANCE` weight 0 (with nothing else live in the first pass, e.g. overstaff strict) makes `value(balance)` None, so the second pass is silently skipped and day wishes are ignored |
| `balance_lock_drift` | confirmed | objective | The lock slack `1e-7·|reached|` lets the second pass return a less balanced roster once large penalties are paid (+0.48 seen with both passes optimal). Doc 3.2's "every difference is a whole number" is false with fractional hours. |
| `penalized_rest_month_end` | confirmed (low) | objective | Penalized rest between two model duties is charged only on in-month days, while against outside duties every shared day is charged. Doc 6 says every overlapping day is charged. `first_pass_cost` mirrors the **solver**. |
| `capacity_error_without_tightened_rules` | confirmed | error message | A capacity pre-check failure caused by a tightened rule (e.g. a strict soft_decline) lacks `tightened_constraints` |
| `unconfigured_external_rest` | confirmed | DB | A duty at a workplace with no scenario earns 1 day, not the documented fallback (the longest rest here that day) |
| `noncanonical_reason` | confirmed (low) | DB | Reasons `'preferred'`, `'soft_decline'` and `' SOFT_DECLINE'` become hard absences; only exact upper-case is read as a wish |
| `retired_competence_rest` | unclear | DB | An adjacent duty in a deactivated competence earns 1 day in the generator but its stored rest in the planner (`get_schedule_context`) |
| `doc_coverage_equality` | confirmed (docs) | docs | Model doc 2.1 says coverage is an equality; by default it is `>=` (overstaff penalized) |

`sample_knobs` avoids zero balance and duplicate externals. `tiny_knobs` (random policies) and `random_policy()` do not.

## Recipes

1. **Validity sweep.**
   - Build planted instances (`sample_knobs(rng, size, True)`) and `solve_in_parallel` them.
   - For each one, assert `status == "ok"` (planted is never infeasible) and `validate(...) == []`.
   - For random instances, an `infeasible` verdict must be confirmed by `reference_feasibility(...)[0] == "infeasible"` (and `'unknown'` is not a confirmation).
2. **Optimality, tiny.** Compare `brute_force` against the solver as in the snippet above. Skip `hit_budget` runs and instances with `known_bug_triggers`.
3. **Optimality, larger.** Run `find_improving_moves(inst, out.assignments, balance_cap=out.balance_cap)` on an observed run. Every `first_pass` or `day_wish` move on a run that did not hit its budget is a finding.
4. **Fairness.** On `symmetric_instance(n, k)`, `metrics(...).load_spread <= 1`. In general, inspect `metrics` (spread, stdev, `over_max`, `rest_breach_days`).
5. **DB path.**
   - `run_db_solver(inst, 15, noise=True, foreign_calendar=True)` must agree with `run_solver(inst, 15)` on status.
   - Its roster must validate.
   - When both runs finish in time, the first-pass costs must be equal within the lock slack.

---

## Scenario test suite

Each `tests/test_scenarios_*.py` file covers one area with the harness above.
The default run is deterministic and takes a few minutes per file. Set
`SCHEDULING_STRESS=1` for the heavy sweep, and the file's report variable
(where it has one) to dump its tables as JSON. Each file prints its tables
when run with `-s`.

| File | Covers | Default | Stress | Report variable |
|---|---|---|---|---|
| `test_scenarios_hard_fuzz.py` | Hard rules on planted and random months of every size and knob profile; pre-check capacity claims recomputed | ~1.5 min | ~14 min | `HARD_FUZZ_METRICS` |
| `test_scenarios_availability_fill.py` | Unavailability 0-90 %, vacation blocks, wish patterns; feasibility frontier, wish honour rates, penalized absences | ~4 min | ~16 min | `AVAILABILITY_FILL_REPORT` |
| `test_scenarios_max_shifts_hours.py` | Monthly maximum (strict, penalized, 0/None, starved, hetero) against an exact model; hours fairness; preference tilt | ~4.5 min | ~19 min | `MAX_SHIFTS_HOURS_REPORT` |
| `test_scenarios_fill_in.py` | Completing a partly filled month: pinned shares, holes, mid-month changes, history compensation, rule-breaking placements, idempotence, month chains, DB path, API month checks | ~4.5 min | ~15 min | `FILL_IN_REPORT` |
| `test_scenarios_determinism_robustness.py` | Same input twice, hash seeds, permutations, time budgets 1-60 s, numeric extremes, no input mutation | ~3.5 min | ~18 min | `DETERMINISM_REPORT` |
| `test_scenarios_policy_matrix.py` | Every rule strict/penalized at weights 0 to 100000, presets, random policies, order of strength, settings service, conflict messages | ~2 min | ~10 min | - |
| `test_scenarios_optimality.py` | Brute force on tiny months, improving moves on larger ones, symmetric fairness, spread quality, solver vs witness | ~3 min | ~14.5 min | - |
| `test_scenarios_edge_cases.py` | Degenerate inputs, calendar edges, argument validation, 1 s budgets | ~2 min | ~4 min | - |
| `test_scenarios_db_end_to_end.py` | DB loader vs in-memory, Slovak holidays, scenarios, HTTP endpoint, save/approve/next month, automatic generation across workplaces | ~2.5 min | ~9 min | - |
| `test_scenarios_realistic_seed.py` | `config_1` / `config_2` seeds: every generated month validated, quality per department, hospital-wide consistency | ~0.5 min | ~2 min | - |
| `test_scenarios_frontend_conflicts.py` | The planner's `scheduleConflicts.js` against the oracle (needs node; skipped otherwise) | ~1 min | ~3 min | - |
| `test_scenarios_performance_scaling.py` | Smoke benchmark of build and solve times by size | ~3 min | - | - |

```bash
venv/Scripts/python.exe -m pytest tests/test_scenarios_fill_in.py -s
SCHEDULING_STRESS=1 FILL_IN_REPORT=fill_in.json venv/Scripts/python.exe -m pytest tests/test_scenarios_fill_in.py -s
```

Expected failures (`@unittest.expectedFailure`) mark solver behaviour that the
tests found wrong; each has a docstring naming the problem. An "unexpected
success" means it was fixed: drop the decorator.
