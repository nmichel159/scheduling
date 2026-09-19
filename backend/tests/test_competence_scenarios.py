"""Tests for competence scenarios -- one parameter set per model case."""

import unittest

from fastapi import HTTPException

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import get_current_user, require_manager_role
from app.db.session import Base, get_db
from app.main import app
from app.models import Ambulance, Competence, Role, User
from app.models.associations import UserAmbulance, UserCompetence, UserRole
from app.schemas.competence import CompetenceCreate, CompetenceUpdate
from app.schemas.competence_scenario import (
    CompetenceScenarioCreate,
    CompetenceScenarioUpdate,
)
from app.services.competence_scenario_service import (
    DEFAULT_SCENARIO_NAME,
    create_scenario,
    delete_scenario,
    ensure_selected_scenario,
    get_selected_scenario,
    list_scenarios,
    selected_scenario_ids,
    update_scenario,
)
from app.services.competence_service import (
    create_competence,
    delete_competence,
    list_competence_responses,
    update_competence,
)
from app.services.schedule_generation_service import (
    generate_ambulance_monthly_schedule,
)


def _week(
    counts: list[int],
    recovery: list[int] | None = None,
    hours: list[float] | None = None,
    surcharge: list[bool] | None = None,
) -> list[dict[str, float]]:
    return [
        {
            "weekday": weekday,
            "required_count": count,
            "recovery_days": (recovery or [1] * 7)[weekday],
            "shift_hours": (hours or [4] * 7)[weekday],
            "is_surcharge": (
                surcharge or [False] * 5 + [True] * 2
            )[weekday],
        }
        for weekday, count in enumerate(counts)
    ]


# A response also carries the special-day slot, which these tests are not
# about -- they are about what a scenario does with the seven weekdays.
# test_competence_weekday_requirements covers slot 7 on its own.
def _weekdays_of(response):
    return [
        item for item in response.weekday_requirements if item.weekday <= 6
    ]


def _json_weekdays(payload, field):
    """One field of a JSON response's seven weekdays, special day aside."""
    return [
        item[field]
        for item in payload["weekday_requirements"]
        if item["weekday"] <= 6
    ]


def _counts(response) -> list[int]:
    return [item.required_count for item in _weekdays_of(response)]


def _recovery(response) -> list[int]:
    return [item.recovery_days for item in _weekdays_of(response)]


def _hours(response) -> list[float]:
    return [item.shift_hours for item in _weekdays_of(response)]


def _surcharge(response) -> list[bool]:
    return [item.is_surcharge for item in _weekdays_of(response)]


class SolverReadsSelectedScenarioTests(unittest.TestCase):
    """The schedule generator must size a month from the selected scenario."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        ambulance = Ambulance(name="Clinic", is_active=True)
        users = [
            User(email=f"duty{index}@example.com", is_active=True)
            for index in range(6)
        ]
        self.db.add_all([ambulance, *users])
        self.db.commit()
        self.ambulance_id = ambulance.id

        self.base = ensure_selected_scenario(self.db, self.ambulance_id)
        created = create_competence(
            self.db,
            self.ambulance_id,
            CompetenceCreate(name="Beds", weekday_requirements=_week([1] * 7)),
        )
        self.db.add_all(
            [
                UserAmbulance(
                    user_id=user.id, ambulance_id=self.ambulance_id, is_active=True
                )
                for user in users
            ]
            + [
                UserCompetence(
                    user_id=user.id, competence_id=created.id, is_active=True
                )
                for user in users
            ]
        )
        self.db.commit()
        self.competence_id = created.id

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _assignment_count(self) -> int:
        return generate_ambulance_monthly_schedule(
            self.db, self.ambulance_id, month=8, year=2026
        ).assignment_count

    def test_only_the_selected_scenario_reaches_the_solver(self) -> None:
        august_days = 31
        self.assertEqual(self._assignment_count(), august_days)

        weekdays_only = create_scenario(
            self.db,
            self.ambulance_id,
            CompetenceScenarioCreate(name="Weekdays only"),
        )
        update_competence(
            self.db,
            self.competence_id,
            self.ambulance_id,
            CompetenceUpdate(weekday_requirements=_week([1, 1, 1, 1, 1, 0, 0])),
            scenario_id=weekdays_only.id,
        )
        self.assertEqual(
            self._assignment_count(),
            august_days,
            "an unselected scenario must not change the schedule",
        )

        update_scenario(
            self.db,
            weekdays_only.id,
            self.ambulance_id,
            CompetenceScenarioUpdate(is_selected=True),
        )
        # August 2026 has 21 weekdays.
        self.assertEqual(self._assignment_count(), 21)


class CompetenceScenarioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        ambulance = Ambulance(name="Clinic", is_active=True)
        self.db.add(ambulance)
        self.db.commit()
        self.ambulance_id = ambulance.id

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_first_use_creates_one_selected_default_scenario(self) -> None:
        scenario = ensure_selected_scenario(self.db, self.ambulance_id)

        self.assertEqual(scenario.name, DEFAULT_SCENARIO_NAME)
        self.assertTrue(scenario.is_selected)
        self.assertEqual(len(list_scenarios(self.db, self.ambulance_id)), 1)

        # Calling it again must not produce a second default.
        self.assertEqual(
            ensure_selected_scenario(self.db, self.ambulance_id).id, scenario.id
        )
        self.assertEqual(len(list_scenarios(self.db, self.ambulance_id)), 1)

    def test_a_new_scenario_copies_parameters_and_then_diverges(self) -> None:
        base = ensure_selected_scenario(self.db, self.ambulance_id)
        create_competence(
            self.db,
            self.ambulance_id,
            CompetenceCreate(
                name="Anaesthesia",
                weekday_requirements=_week([2, 2, 2, 2, 2, 1, 1]),
            ),
        )

        copy = create_scenario(
            self.db,
            self.ambulance_id,
            CompetenceScenarioCreate(name="Busy week", copy_from_scenario_id=base.id),
        )
        copied = list_competence_responses(self.db, self.ambulance_id, copy.id)[0]
        self.assertEqual(_counts(copied), [2, 2, 2, 2, 2, 1, 1])

        update_competence(
            self.db,
            copied.id,
            self.ambulance_id,
            CompetenceUpdate(weekday_requirements=_week([5, 5, 5, 5, 5, 0, 0])),
            scenario_id=copy.id,
        )

        self.assertEqual(
            _counts(list_competence_responses(self.db, self.ambulance_id, copy.id)[0]),
            [5, 5, 5, 5, 5, 0, 0],
        )
        self.assertEqual(
            _counts(list_competence_responses(self.db, self.ambulance_id, base.id)[0]),
            [2, 2, 2, 2, 2, 1, 1],
            "editing one scenario must not touch another",
        )

    def test_a_scenario_without_a_source_starts_from_the_defaults(self) -> None:
        """The plus button on the list: every competence, one person a day."""
        ensure_selected_scenario(self.db, self.ambulance_id)
        create_competence(
            self.db,
            self.ambulance_id,
            CompetenceCreate(
                name="Anaesthesia",
                weekday_requirements=_week([7, 7, 7, 7, 7, 0, 0], hours=[12] * 7),
            ),
        )

        fresh = create_scenario(
            self.db, self.ambulance_id, CompetenceScenarioCreate(name="From scratch")
        )

        response = list_competence_responses(self.db, self.ambulance_id, fresh.id)[0]
        self.assertEqual(_counts(response), [1] * 7)
        self.assertEqual(_hours(response), [4] * 7)
        self.assertEqual(_recovery(response), [1] * 7)

    def test_a_competence_created_in_one_scenario_exists_in_all_of_them(self) -> None:
        base = ensure_selected_scenario(self.db, self.ambulance_id)
        other = create_scenario(
            self.db, self.ambulance_id, CompetenceScenarioCreate(name="Quiet week")
        )

        create_competence(
            self.db,
            self.ambulance_id,
            CompetenceCreate(name="Consults", weekday_requirements=_week([3] * 7)),
            scenario_id=other.id,
        )

        for scenario_id in (base.id, other.id):
            names = [
                item.name
                for item in list_competence_responses(
                    self.db, self.ambulance_id, scenario_id
                )
            ]
            self.assertEqual(names, ["Consults"])

        # Only the scenario it was created in is staffed by it; the others
        # carry it at zero until someone asks for people there.
        self.assertEqual(
            _counts(list_competence_responses(self.db, self.ambulance_id, other.id)[0]),
            [3] * 7,
        )
        self.assertEqual(
            _counts(list_competence_responses(self.db, self.ambulance_id, base.id)[0]),
            [0] * 7,
        )
        self.assertEqual(
            _hours(list_competence_responses(self.db, self.ambulance_id, base.id)[0]),
            [4] * 7,
            "the other scenarios still describe the duty, they just do not staff it",
        )

        # It is the same competence row, so a rename is visible everywhere.
        competence_id = list_competence_responses(
            self.db, self.ambulance_id, other.id
        )[0].id
        update_competence(
            self.db,
            competence_id,
            self.ambulance_id,
            CompetenceUpdate(name="Consultations"),
            scenario_id=other.id,
        )
        self.assertEqual(
            list_competence_responses(self.db, self.ambulance_id, base.id)[0].name,
            "Consultations",
        )

    def test_deleting_a_competence_removes_it_from_every_scenario(self) -> None:
        base = ensure_selected_scenario(self.db, self.ambulance_id)
        other = create_scenario(
            self.db, self.ambulance_id, CompetenceScenarioCreate(name="Quiet week")
        )
        created = create_competence(
            self.db,
            self.ambulance_id,
            CompetenceCreate(name="Consults", weekday_requirements=_week([1] * 7)),
        )

        delete_competence(self.db, created.id, self.ambulance_id)

        for scenario_id in (base.id, other.id):
            self.assertEqual(
                list_competence_responses(self.db, self.ambulance_id, scenario_id), []
            )

    def test_recovery_days_round_trip_per_weekday(self) -> None:
        scenario = ensure_selected_scenario(self.db, self.ambulance_id)
        created = create_competence(
            self.db,
            self.ambulance_id,
            CompetenceCreate(
                name="Night duty",
                weekday_requirements=_week([1] * 7, recovery=[2, 1, 1, 1, 3, 0, 0]),
            ),
        )

        self.assertEqual(_recovery(created), [2, 1, 1, 1, 3, 0, 0])
        self.assertEqual(
            _recovery(
                list_competence_responses(self.db, self.ambulance_id, scenario.id)[0]
            ),
            [2, 1, 1, 1, 3, 0, 0],
        )

    def test_shift_hours_round_trip_per_weekday_and_stay_in_one_scenario(self) -> None:
        base = ensure_selected_scenario(self.db, self.ambulance_id)
        created = create_competence(
            self.db,
            self.ambulance_id,
            CompetenceCreate(
                name="Ward round",
                weekday_requirements=_week([1] * 7, hours=[8, 8, 8, 8, 8, 12, 12]),
            ),
        )
        self.assertEqual(_hours(created), [8, 8, 8, 8, 8, 12, 12])

        copy = create_scenario(
            self.db,
            self.ambulance_id,
            CompetenceScenarioCreate(name="Long shifts", copy_from_scenario_id=base.id),
        )
        self.assertEqual(
            _hours(list_competence_responses(self.db, self.ambulance_id, copy.id)[0]),
            [8, 8, 8, 8, 8, 12, 12],
            "a duplicate must carry the hours over",
        )

        update_competence(
            self.db,
            created.id,
            self.ambulance_id,
            CompetenceUpdate(weekday_requirements=_week([1] * 7, hours=[24] * 7)),
            scenario_id=copy.id,
        )
        self.assertEqual(
            _hours(list_competence_responses(self.db, self.ambulance_id, copy.id)[0]),
            [24] * 7,
        )
        self.assertEqual(
            _hours(list_competence_responses(self.db, self.ambulance_id, base.id)[0]),
            [8, 8, 8, 8, 8, 12, 12],
            "hours belong to one scenario",
        )

    def test_a_new_competence_defaults_to_four_hours_and_weekend_surcharge(self) -> None:
        ensure_selected_scenario(self.db, self.ambulance_id)
        created = create_competence(
            self.db, self.ambulance_id, CompetenceCreate(name="Triage")
        )

        self.assertEqual(_hours(created), [4] * 7)
        self.assertEqual(
            _surcharge(created),
            [False, False, False, False, False, True, True],
            "a competence nobody configured is surcharged on the weekend",
        )

    def test_the_surcharge_flag_is_per_weekday_and_per_scenario(self) -> None:
        base = ensure_selected_scenario(self.db, self.ambulance_id)
        weekend_plus_friday = [False] * 4 + [True] * 3
        created = create_competence(
            self.db,
            self.ambulance_id,
            CompetenceCreate(
                name="On call",
                weekday_requirements=_week([1] * 7, surcharge=weekend_plus_friday),
            ),
        )

        self.assertEqual(_surcharge(created), weekend_plus_friday)

        copy = create_scenario(
            self.db,
            self.ambulance_id,
            CompetenceScenarioCreate(name="Quiet week", copy_from_scenario_id=base.id),
        )
        self.assertEqual(
            _surcharge(
                list_competence_responses(self.db, self.ambulance_id, copy.id)[0]
            ),
            weekend_plus_friday,
            "a duplicate must carry the surcharged days over",
        )

        update_competence(
            self.db,
            created.id,
            self.ambulance_id,
            CompetenceUpdate(
                weekday_requirements=_week([1] * 7, surcharge=[False] * 7)
            ),
            scenario_id=copy.id,
        )
        self.assertEqual(
            _surcharge(
                list_competence_responses(self.db, self.ambulance_id, copy.id)[0]
            ),
            [False] * 7,
        )
        self.assertEqual(
            _surcharge(
                list_competence_responses(self.db, self.ambulance_id, base.id)[0]
            ),
            weekend_plus_friday,
            "surcharged days belong to one scenario",
        )

    def test_a_competence_without_weekday_rows_reads_its_legacy_count(self) -> None:
        """Rows seeded straight into the table keep answering as a full week."""
        competence = Competence(
            name="Seeded",
            ambulance_id=self.ambulance_id,
            required_count=4,
            is_active=True,
        )
        self.db.add(competence)
        self.db.commit()

        response = list_competence_responses(self.db, self.ambulance_id)[0]
        self.assertEqual(_counts(response), [4] * 7)
        self.assertEqual(_recovery(response), [1] * 7)
        self.assertEqual(_hours(response), [4] * 7)
        self.assertEqual(
            _surcharge(response), [False, False, False, False, False, True, True]
        )

    def test_selecting_a_scenario_changes_what_the_application_reads(self) -> None:
        base = ensure_selected_scenario(self.db, self.ambulance_id)
        create_competence(
            self.db,
            self.ambulance_id,
            CompetenceCreate(name="Beds", weekday_requirements=_week([1] * 7)),
        )
        busy = create_scenario(
            self.db, self.ambulance_id, CompetenceScenarioCreate(name="Busy week")
        )
        self.assertFalse(busy.is_selected, "a new scenario must not steal the selection")

        competence_id = list_competence_responses(self.db, self.ambulance_id)[0].id
        update_competence(
            self.db,
            competence_id,
            self.ambulance_id,
            CompetenceUpdate(weekday_requirements=_week([9] * 7)),
            scenario_id=busy.id,
        )
        self.assertEqual(
            _counts(list_competence_responses(self.db, self.ambulance_id)[0]),
            [1] * 7,
        )

        update_scenario(
            self.db,
            busy.id,
            self.ambulance_id,
            CompetenceScenarioUpdate(is_selected=True),
        )

        self.assertEqual(get_selected_scenario(self.db, self.ambulance_id).id, busy.id)
        self.assertEqual(
            _counts(list_competence_responses(self.db, self.ambulance_id)[0]),
            [9] * 7,
        )
        self.assertEqual(
            [item.is_selected for item in list_scenarios(self.db, self.ambulance_id)],
            [False, True],
            "exactly one scenario stays selected",
        )
        self.assertEqual(
            selected_scenario_ids(self.db, [self.ambulance_id]),
            {self.ambulance_id: busy.id},
        )
        # base kept its own numbers all along.
        self.assertEqual(
            _counts(list_competence_responses(self.db, self.ambulance_id, base.id)[0]),
            [1] * 7,
        )

    def test_the_last_scenario_cannot_be_deleted(self) -> None:
        ensure_selected_scenario(self.db, self.ambulance_id)
        only = list_scenarios(self.db, self.ambulance_id)[0]

        with self.assertRaises(HTTPException) as caught:
            delete_scenario(self.db, only.id, self.ambulance_id)
        self.assertEqual(caught.exception.status_code, 400)

    def test_deleting_the_selected_scenario_hands_the_selection_over(self) -> None:
        base = ensure_selected_scenario(self.db, self.ambulance_id)
        other = create_scenario(
            self.db, self.ambulance_id, CompetenceScenarioCreate(name="Busy week")
        )

        delete_scenario(self.db, base.id, self.ambulance_id)

        remaining = list_scenarios(self.db, self.ambulance_id)
        self.assertEqual([item.id for item in remaining], [other.id])
        self.assertTrue(remaining[0].is_selected)

    def test_duplicate_scenario_names_are_rejected(self) -> None:
        ensure_selected_scenario(self.db, self.ambulance_id)
        create_scenario(
            self.db, self.ambulance_id, CompetenceScenarioCreate(name="Busy week")
        )

        with self.assertRaises(HTTPException) as caught:
            create_scenario(
                self.db, self.ambulance_id, CompetenceScenarioCreate(name="Busy week")
            )
        self.assertEqual(caught.exception.status_code, 409)

    def test_scenarios_of_another_workplace_are_not_reachable(self) -> None:
        other_ambulance = Ambulance(name="Other clinic", is_active=True)
        self.db.add(other_ambulance)
        self.db.commit()
        foreign = ensure_selected_scenario(self.db, other_ambulance.id)
        ensure_selected_scenario(self.db, self.ambulance_id)

        with self.assertRaises(HTTPException) as caught:
            update_scenario(
                self.db,
                foreign.id,
                self.ambulance_id,
                CompetenceScenarioUpdate(name="Stolen"),
            )
        self.assertEqual(caught.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()


class CompetenceScenarioRouterTests(unittest.TestCase):
    """Drive the endpoints the scenario screen calls, over HTTP."""

    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        role = Role(id=1, code="MANAGER", name="Manager", level=2, is_active=True)
        manager = User(id=1, email="manager@example.com", is_active=True)
        self.db.add_all([role, manager])
        self.db.flush()
        self.db.add(UserRole(user_id=manager.id, role_id=role.id))
        ambulance = Ambulance(
            name="Clinic", managed_by_user_id=manager.id, is_active=True
        )
        self.db.add(ambulance)
        self.db.commit()
        self.base = f"/ambulances/{ambulance.id}/competence-scenarios"

        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: manager
        app.dependency_overrides[require_manager_role] = lambda: manager
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def test_the_screens_round_trip(self) -> None:
        # Opening the screen is what gives the workplace its first scenario.
        scenarios = self.client.get(self.base).json()
        self.assertEqual(len(scenarios), 1)
        self.assertTrue(scenarios[0]["is_selected"])
        first = scenarios[0]["id"]

        created = self.client.post(
            f"{self.base}/{first}/competences",
            json={
                "name": "Anaesthesia",
                "description": "ICU",
                "weekday_requirements": _week([2, 2, 2, 2, 2, 1, 1]),
            },
        )
        self.assertEqual(created.status_code, 201)
        competence_id = created.json()["id"]

        copy = self.client.post(
            self.base, json={"name": "Busy week", "copy_from_scenario_id": first}
        )
        self.assertEqual(copy.status_code, 201)
        self.assertFalse(copy.json()["is_selected"])
        self.assertEqual(copy.json()["competence_count"], 1)
        second = copy.json()["id"]

        edited = self.client.put(
            f"{self.base}/{second}/competences/{competence_id}",
            json={
                "name": "Anaesthesia",
                "weekday_requirements": _week(
                    [5] * 7, recovery=[0, 0, 0, 0, 2, 0, 0]
                ),
            },
        )
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(
            _json_weekdays(edited.json(), "recovery_days"),
            [0, 0, 0, 0, 2, 0, 0],
        )

        untouched = self.client.get(f"{self.base}/{first}/competences").json()
        self.assertEqual(
            _json_weekdays(untouched[0], "required_count"),
            [2, 2, 2, 2, 2, 1, 1],
        )

        self.client.put(f"{self.base}/{second}", json={"is_selected": True})
        # The scenario-unaware endpoint the other screens use follows along.
        legacy = self.client.get("/ambulances/1/competences").json()
        self.assertEqual(
            _json_weekdays(legacy[0], "required_count"),
            [5] * 7,
        )

        self.assertEqual(self.client.delete(f"{self.base}/{second}").status_code, 204)
        remaining = self.client.get(self.base).json()
        self.assertEqual([item["is_selected"] for item in remaining], [True])

        refused = self.client.delete(f"{self.base}/{first}")
        self.assertEqual(refused.status_code, 400)

    def test_the_matrix_screen_writes_only_to_the_selected_scenario(self) -> None:
        """The Workplaces matrix saves counts without naming a scenario.

        It reads and writes ``/ambulances/{id}/competences``, so those calls
        have to land on the selected scenario and leave both the other
        scenarios and the recovery days it never shows untouched.
        """
        first = self.client.get(self.base).json()[0]["id"]
        created = self.client.post(
            f"{self.base}/{first}/competences",
            json={
                "name": "Beds",
                "weekday_requirements": _week([1] * 7, recovery=[2] * 7),
            },
        ).json()
        second = self.client.post(
            self.base, json={"name": "Busy week", "copy_from_scenario_id": first}
        ).json()["id"]
        self.client.put(f"{self.base}/{second}", json={"is_selected": True})

        # Exactly what the matrix sends: the week it read back, counts edited.
        matrix_week = self.client.get("/ambulances/1/competences").json()[0][
            "weekday_requirements"
        ]
        for item in matrix_week:
            item["required_count"] = 4
        saved = self.client.put(
            f"/ambulances/1/competences/{created['id']}",
            json={"weekday_requirements": matrix_week},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["scenario_id"], second)
        self.assertEqual(
            _json_weekdays(saved.json(), "recovery_days"),
            [2] * 7,
            "a matrix save must not flatten the recovery it never shows",
        )

        untouched = self.client.get(f"{self.base}/{first}/competences").json()[0]
        self.assertEqual(
            _json_weekdays(untouched, "required_count"),
            [1] * 7,
        )

    def test_a_workplace_the_caller_does_not_manage_is_refused(self) -> None:
        other = Ambulance(name="Other clinic", managed_by_user_id=2, is_active=True)
        self.db.add(other)
        self.db.commit()

        response = self.client.get(f"/ambulances/{other.id}/competence-scenarios")
        self.assertEqual(response.status_code, 403)
