"""Tests for a workplace's scheduling rules: storage, endpoints and the solver.

Each rule is fixed, switchable or penalty-only. The tests hold the three
kinds to what they promise -- a fixed rule cannot be relaxed, a
penalty-only rule cannot be made strict, a switchable rule does what its
setting says in the generated month -- and hold the defaults to the one
promise that matters most: a workplace nobody configured is scheduled
exactly as before.
"""

from collections import Counter
from datetime import date
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import get_current_user
from app.db.session import Base, get_db
from app.main import app
from app.models import (
    Ambulance,
    Competence,
    CompetenceScenario,
    CompetenceWeekdayRequirement,
    ConstraintSetting,
    Role,
    Unavailability,
    User,
)
from app.models.associations import UserAmbulance, UserCompetence, UserRole
from app.services.constraint_setting_service import (
    CONSTRAINTS,
    ConstraintPolicy,
    ConstraintSettingError,
    constraint_entries,
    load_constraint_policy,
    policy_from_settings,
    reset_constraint_settings,
    save_constraint_settings,
)
from app.services.schedule_generation_service import (
    ScheduleGenerationError,
    SchedulingCompetence,
    SchedulingEmployee,
    generate_ambulance_monthly_schedule,
    solve_monthly_schedule,
)


def _employee(user_id: int, **fields) -> SchedulingEmployee:
    """A one-competence employee, with whatever the test needs on top."""
    values = {
        "id": user_id,
        "email": f"employee{user_id}@example.com",
        "full_name": f"Employee {user_id}",
        "competence_ids": frozenset({1}),
        "unavailable_dates": frozenset(),
        "externally_scheduled_dates": frozenset(),
    }
    values.update(fields)
    return SchedulingEmployee(**values)


#: One person a day, every day, with a day of rest after each duty.
DAILY = SchedulingCompetence(id=1, name="Triage", required_count=1)

#: One person on Tuesdays only, and no rest to speak of.
TUESDAYS = SchedulingCompetence(
    id=1,
    name="Triage",
    required_count=1,
    weekday_required_counts=(0, 1, 0, 0, 0, 0, 0),
    weekday_recovery_days=(0,) * 7,
)

VACATION_DAY = date(2026, 8, 4)


class ConstraintSettingStorageTests(unittest.TestCase):
    """What a workplace may set, and what gets written down."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.ambulance = Ambulance(name="Clinic", is_active=True)
        self.db.add(self.ambulance)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _entry(self, code: str) -> dict:
        return next(
            entry
            for entry in constraint_entries(self.db, self.ambulance.id)
            if entry["code"] == code
        )

    def _rows(self) -> dict[str, ConstraintSetting]:
        return {
            row.code: row
            for row in self.db.query(ConstraintSetting)
            .filter(ConstraintSetting.ambulance_id == self.ambulance.id)
            .all()
        }

    def test_an_unconfigured_workplace_lists_every_rule_at_its_default(self) -> None:
        entries = constraint_entries(self.db, self.ambulance.id)
        self.assertEqual(
            [entry["code"] for entry in entries],
            [definition.code for definition in CONSTRAINTS],
        )
        self.assertTrue(all(entry["is_default"] for entry in entries))
        self.assertEqual(load_constraint_policy(self.db, self.ambulance.id).rules, {})

    def test_the_fixed_rules_are_the_ones_the_roster_cannot_do_without(self) -> None:
        fixed = {
            entry["code"]
            for entry in constraint_entries(self.db, self.ambulance.id)
            if entry["mode"] == "fixed"
        }
        self.assertEqual(
            fixed,
            {"coverage", "one_role_per_day", "qualification", "other_workplace"},
        )

    def test_a_change_is_stored_and_read_back(self) -> None:
        save_constraint_settings(
            self.db, self.ambulance.id, [("vacation", False, 250.0)]
        )
        entry = self._entry("vacation")
        self.assertFalse(entry["is_strict"])
        self.assertEqual(entry["weight"], 250.0)
        self.assertFalse(entry["is_default"])
        policy = load_constraint_policy(self.db, self.ambulance.id)
        self.assertFalse(policy.is_strict("vacation"))
        self.assertEqual(policy.weight("vacation"), 250.0)

    def test_setting_a_rule_back_to_its_default_drops_its_row(self) -> None:
        save_constraint_settings(self.db, self.ambulance.id, [("spread", False, 3.0)])
        self.assertIn("spread", self._rows())
        save_constraint_settings(self.db, self.ambulance.id, [("spread", False, 1.0)])
        self.assertNotIn("spread", self._rows())
        self.assertTrue(self._entry("spread")["is_default"])

    def test_a_fixed_rule_cannot_be_relaxed(self) -> None:
        with self.assertRaises(ConstraintSettingError):
            save_constraint_settings(
                self.db, self.ambulance.id, [("one_role_per_day", False, 10.0)]
            )

    def test_a_penalty_only_rule_cannot_be_made_strict(self) -> None:
        for code in ("spread", "balance", "preferred"):
            with self.subTest(code=code), self.assertRaises(ConstraintSettingError):
                save_constraint_settings(self.db, self.ambulance.id, [(code, True, 1.0)])

    def test_one_refused_setting_leaves_the_workplace_unchanged(self) -> None:
        with self.assertRaises(ConstraintSettingError):
            save_constraint_settings(
                self.db,
                self.ambulance.id,
                [("vacation", False, 50.0), ("rest", False, -1.0)],
            )
        self.assertEqual(self._rows(), {})

    def test_unknown_and_repeated_codes_are_refused(self) -> None:
        with self.assertRaises(ConstraintSettingError):
            save_constraint_settings(self.db, self.ambulance.id, [("nope", True, 1.0)])
        with self.assertRaises(ConstraintSettingError):
            save_constraint_settings(
                self.db,
                self.ambulance.id,
                [("vacation", False, 1.0), ("vacation", True, 1.0)],
            )

    def test_reset_hands_every_rule_back(self) -> None:
        save_constraint_settings(
            self.db,
            self.ambulance.id,
            [("vacation", False, 5.0), ("max_shifts", True, 1000.0)],
        )
        reset_constraint_settings(self.db, self.ambulance.id)
        self.assertEqual(self._rows(), {})

    def test_the_settings_belong_to_one_workplace(self) -> None:
        other = Ambulance(name="Other", is_active=True)
        self.db.add(other)
        self.db.commit()
        save_constraint_settings(self.db, other.id, [("vacation", False, 5.0)])
        self.assertTrue(self._entry("vacation")["is_strict"])

    def test_tightened_names_only_rules_made_stricter_than_their_default(self) -> None:
        policy = policy_from_settings(
            {"max_shifts": (True, 1000.0), "vacation": (False, 5.0)}
        )
        self.assertEqual(policy.tightened(), ["max_shifts"])
        self.assertEqual(ConstraintPolicy.default().tightened(), [])


class ConstraintSettingRouterTests(unittest.TestCase):
    """The endpoints the rules screen calls, over HTTP."""

    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        leader = Role(id=1, code="LEADER", name="Scheduler", level=2, is_active=True)
        self.scheduler = User(id=1, email="scheduler@example.com", is_active=True)
        self.db.add_all([leader, self.scheduler])
        self.db.flush()
        self.db.add(UserRole(user_id=self.scheduler.id, role_id=leader.id))
        ambulance = Ambulance(
            name="Clinic", managed_by_user_id=self.scheduler.id, is_active=True
        )
        foreign = Ambulance(name="Other clinic", managed_by_user_id=99, is_active=True)
        self.db.add_all([ambulance, foreign])
        self.db.commit()
        self.base = f"/ambulances/{ambulance.id}/constraints"
        self.foreign_base = f"/ambulances/{foreign.id}/constraints"

        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.scheduler
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    @staticmethod
    def _entry(payload: dict, code: str) -> dict:
        return next(item for item in payload["entries"] if item["code"] == code)

    def test_the_screen_round_trips(self) -> None:
        listed = self.client.get(self.base)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["entries"]), len(CONSTRAINTS))
        self.assertTrue(self._entry(listed.json(), "vacation")["is_strict"])

        saved = self.client.put(
            self.base,
            json={
                "entries": [
                    {"code": "vacation", "is_strict": False, "weight": 300},
                    {"code": "spread", "is_strict": False, "weight": 2.5},
                ]
            },
        )
        self.assertEqual(saved.status_code, 200)
        vacation = self._entry(saved.json(), "vacation")
        self.assertFalse(vacation["is_strict"])
        self.assertEqual(vacation["weight"], 300)
        self.assertEqual(self._entry(saved.json(), "spread")["weight"], 2.5)

        reset = self.client.delete(self.base)
        self.assertEqual(reset.status_code, 200)
        self.assertTrue(all(item["is_default"] for item in reset.json()["entries"]))

    def test_a_refused_setting_answers_422(self) -> None:
        answer = self.client.put(
            self.base,
            json={"entries": [{"code": "coverage", "is_strict": False, "weight": 1}]},
        )
        self.assertEqual(answer.status_code, 422)

    def test_another_schedulers_workplace_is_out_of_reach(self) -> None:
        self.assertEqual(self.client.get(self.foreign_base).status_code, 403)
        answer = self.client.put(
            self.foreign_base,
            json={"entries": [{"code": "vacation", "is_strict": False, "weight": 1}]},
        )
        self.assertEqual(answer.status_code, 403)


class ConstraintSettingSolverTests(unittest.TestCase):
    """Each switchable rule does in the generated month what its setting says."""

    def test_a_strict_vacation_is_never_worked(self) -> None:
        employees = [
            _employee(
                1,
                unavailable_dates=frozenset({VACATION_DAY}),
                absence_rules=((VACATION_DAY, "vacation"),),
            )
        ]
        with self.assertRaises(ScheduleGenerationError):
            solve_monthly_schedule(employees, [TUESDAYS], month=8, year=2026)

    def test_a_penalized_vacation_is_worked_only_when_nobody_else_can(self) -> None:
        absent = {
            "unavailable_dates": frozenset({VACATION_DAY}),
            "absence_rules": ((VACATION_DAY, "vacation"),),
        }
        policy = policy_from_settings({"vacation": (False, 1000.0)})

        alone = solve_monthly_schedule(
            [_employee(1, **absent)], [TUESDAYS], month=8, year=2026, constraints=policy
        )
        self.assertIn(VACATION_DAY, {item.work_date for item in alone})

        covered = solve_monthly_schedule(
            [_employee(1, **absent), _employee(2)],
            [TUESDAYS],
            month=8,
            year=2026,
            constraints=policy,
        )
        self.assertFalse(
            any(item.user_id == 1 and item.work_date == VACATION_DAY for item in covered)
        )

    def test_each_kind_of_absence_follows_its_own_rule(self) -> None:
        """A penalized vacation does not soften a business trip."""
        employees = [
            _employee(
                1,
                unavailable_dates=frozenset({VACATION_DAY}),
                absence_rules=((VACATION_DAY, "business_trip"),),
            )
        ]
        with self.assertRaises(ScheduleGenerationError):
            solve_monthly_schedule(
                employees,
                [TUESDAYS],
                month=8,
                year=2026,
                constraints=policy_from_settings({"vacation": (False, 1000.0)}),
            )

    def test_a_penalized_rest_is_broken_only_when_the_month_needs_it(self) -> None:
        with self.assertRaises(ScheduleGenerationError):
            solve_monthly_schedule([_employee(1)], [DAILY], month=8, year=2026)

        policy = policy_from_settings({"rest": (False, 1000.0)})
        alone = solve_monthly_schedule(
            [_employee(1)], [DAILY], month=8, year=2026, constraints=policy
        )
        self.assertEqual(len(alone), 31)

        pair = solve_monthly_schedule(
            [_employee(1), _employee(2)], [DAILY], month=8, year=2026, constraints=policy
        )
        worked = {(item.user_id, item.work_date) for item in pair}
        for user_id, work_date in worked:
            self.assertNotIn(
                (user_id, date.fromordinal(work_date.toordinal() + 1)), worked
            )

    def test_a_penalized_rest_still_charges_a_duty_just_before_the_month(self) -> None:
        pair = solve_monthly_schedule(
            [_employee(1), _employee(2)],
            [DAILY],
            month=8,
            year=2026,
            adjacent_assignments=frozenset({(1, 1, date(2026, 7, 31))}),
            constraints=policy_from_settings({"rest": (False, 1000.0)}),
        )
        first = next(item for item in pair if item.work_date == date(2026, 8, 1))
        self.assertEqual(first.user_id, 2)

    def test_a_penalized_rest_keeps_one_role_a_day(self) -> None:
        competences = [
            SchedulingCompetence(id=1, name="Triage", required_count=1),
            SchedulingCompetence(id=2, name="Ward", required_count=1),
        ]
        with self.assertRaises(ScheduleGenerationError):
            solve_monthly_schedule(
                [_employee(1, competence_ids=frozenset({1, 2}))],
                competences,
                month=8,
                year=2026,
                constraints=policy_from_settings({"rest": (False, 1000.0)}),
            )

    def test_a_strict_monthly_maximum_is_a_cap(self) -> None:
        employees = [_employee(1, max_shifts_per_month=1)]
        policy = policy_from_settings({"max_shifts": (True, 1000.0)})
        with self.assertRaises(ScheduleGenerationError) as raised:
            solve_monthly_schedule(
                employees, [TUESDAYS], month=8, year=2026, constraints=policy
            )
        self.assertEqual(
            raised.exception.issues[0].get("tightened_constraints"), ["max_shifts"]
        )

        shared = solve_monthly_schedule(
            [_employee(1), _employee(2), _employee(3, max_shifts_per_month=2)],
            [DAILY],
            month=8,
            year=2026,
            constraints=policy,
        )
        self.assertEqual(Counter(item.user_id for item in shared)[3], 2)

    def test_a_strict_rather_not_is_never_worked(self) -> None:
        employees = [_employee(1, soft_declined_dates=frozenset({VACATION_DAY}))]
        self.assertIn(
            VACATION_DAY,
            {
                item.work_date
                for item in solve_monthly_schedule(
                    employees, [TUESDAYS], month=8, year=2026
                )
            },
        )
        with self.assertRaises(ScheduleGenerationError):
            solve_monthly_schedule(
                employees,
                [TUESDAYS],
                month=8,
                year=2026,
                constraints=policy_from_settings({"soft_decline": (True, 10.0)}),
            )

    def test_strict_staffing_keeps_every_role_at_its_count(self) -> None:
        policy = policy_from_settings({"overstaff": (True, 1000.0)})
        assignments = solve_monthly_schedule(
            [_employee(user_id) for user_id in range(1, 5)],
            [DAILY],
            month=8,
            year=2026,
            constraints=policy,
        )
        self.assertEqual(Counter(item.work_date for item in assignments).most_common(1)[0][1], 1)

    def test_the_defaults_reproduce_the_unconfigured_model(self) -> None:
        employees = [_employee(user_id) for user_id in range(1, 5)]
        before = solve_monthly_schedule(employees, [DAILY], month=8, year=2026)
        after = solve_monthly_schedule(
            employees,
            [DAILY],
            month=8,
            year=2026,
            constraints=policy_from_settings(
                {
                    definition.code: (
                        definition.default_strict,
                        definition.default_weight,
                    )
                    for definition in CONSTRAINTS
                }
            ),
        )
        self.assertEqual(before, after)

    def test_a_zero_balance_weight_stops_evening_out_the_load(self) -> None:
        employees = [_employee(user_id) for user_id in range(1, 5)]
        balanced = solve_monthly_schedule(employees, [DAILY], month=8, year=2026)
        self.assertEqual(
            sorted(Counter(item.user_id for item in balanced).values()), [7, 8, 8, 8]
        )
        ignored = solve_monthly_schedule(
            employees,
            [DAILY],
            month=8,
            year=2026,
            constraints=policy_from_settings(
                {
                    "balance": (False, 0.0),
                    "spread": (False, 0.0),
                    "preferred": (False, 0.0),
                    "soft_decline": (False, 0.0),
                }
            ),
        )
        self.assertEqual(len(ignored), 31)


class ConstraintSettingLoadingTests(unittest.TestCase):
    """The generator reads the workplace's settings and the kind of absence."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_a_penalized_vacation_set_on_the_workplace_reaches_the_solver(self) -> None:
        """One person, one Tuesday a week, and a vacation on one of them."""
        ambulance = Ambulance(name="Clinic", is_active=True)
        user = User(email="doc@example.com", full_name="Doc", is_active=True)
        self.db.add_all([ambulance, user])
        self.db.flush()
        scenario = CompetenceScenario(
            name="Scenario 1", ambulance_id=ambulance.id, is_selected=True, is_active=True
        )
        self.db.add(scenario)
        self.db.flush()
        competence = Competence(
            name="Triage", ambulance_id=ambulance.id, required_count=0, is_active=True
        )
        competence.weekday_requirements = [
            CompetenceWeekdayRequirement(
                weekday=1, required_count=1, recovery_days=0, scenario_id=scenario.id
            )
        ]
        self.db.add(competence)
        self.db.flush()
        self.db.add_all(
            [
                UserAmbulance(user_id=user.id, ambulance_id=ambulance.id, is_active=True),
                UserCompetence(
                    user_id=user.id, competence_id=competence.id, is_active=True
                ),
                Unavailability(
                    user_id=user.id,
                    date_absent=VACATION_DAY,
                    reason="VACATION",
                    is_active=True,
                ),
            ]
        )
        self.db.commit()

        with self.assertRaises(ScheduleGenerationError):
            generate_ambulance_monthly_schedule(self.db, ambulance.id, 8, 2026)

        save_constraint_settings(self.db, ambulance.id, [("vacation", False, 1000.0)])
        response = generate_ambulance_monthly_schedule(self.db, ambulance.id, 8, 2026)
        self.assertIn(VACATION_DAY, {entry.work_date for entry in response.entries})
        self.assertEqual(response.assignment_count, 4)


if __name__ == "__main__":
    unittest.main()
