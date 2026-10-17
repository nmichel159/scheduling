"""Day limits on absences and the overview of who entered what, in order."""

import unittest
from datetime import date
from unittest import mock

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models.ambulance import Ambulance
from app.models.associations import UserAmbulance
from app.models.user import User
from app.schemas.unavailability import UnavailabilityCreate, UnavailabilityUpdate
from app.services import availability_overview_service as overview
from app.services import availability_window_service as window
from app.services.unavailability_service import (
    create_unavailability,
    update_unavailability,
)

DAY = date(2026, 11, 3)


class AvailabilityOverviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        today = mock.patch.object(window, "local_today", lambda: date(2026, 10, 10))
        today.start()
        self.addCleanup(today.stop)
        past = mock.patch(
            "app.services.unavailability_service._first_day_of_current_month",
            lambda: date(2026, 10, 1),
        )
        past.start()
        self.addCleanup(past.stop)

        ambulance = Ambulance(name="Ambulancia", is_active=True)
        other = Ambulance(name="Iná", is_active=True)
        self.db.add_all([ambulance, other])
        self.db.flush()
        self.amb, self.other = ambulance.id, other.id
        self.users = []
        for email in ("a@x.sk", "b@x.sk", "c@x.sk", "boss@x.sk"):
            user = User(email=email, full_name=email.split("@")[0], is_active=True)
            self.db.add(user)
            self.db.flush()
            self.db.add(
                UserAmbulance(user_id=user.id, ambulance_id=ambulance.id, is_active=True)
            )
            self.users.append(user)
        self.outsider = User(email="d@x.sk", full_name="d", is_active=True)
        self.db.add(self.outsider)
        self.db.flush()
        self.db.add(
            UserAmbulance(user_id=self.outsider.id, ambulance_id=other.id, is_active=True)
        )
        self.db.commit()
        self.a, self.b, self.c, self.boss = self.users

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _enter(self, user, reason, **kwargs):
        return create_unavailability(
            self.db, user.id, UnavailabilityCreate(date_absent=DAY, reason=reason), **kwargs
        )

    def test_limits_default_to_none_and_can_be_dropped(self) -> None:
        self.assertEqual(
            overview.day_limits(self.db, self.amb),
            {"VACATION": None, "BUSINESS_TRIP": None, "UNAVAILABLE": None},
        )
        overview.save_day_limits(self.db, self.amb, {"VACATION": 2})
        overview.save_day_limits(self.db, self.amb, {"BUSINESS_TRIP": 1})
        self.assertEqual(overview.day_limits(self.db, self.amb)["VACATION"], 2)
        overview.save_day_limits(self.db, self.amb, {"VACATION": None})
        self.assertIsNone(overview.day_limits(self.db, self.amb)["VACATION"])
        self.assertEqual(overview.day_limits(self.db, self.amb)["BUSINESS_TRIP"], 1)
        with self.assertRaises(HTTPException):
            overview.save_day_limits(self.db, self.amb, {"PREFERRED": 1})

    def test_full_day_refuses_the_employee_but_not_the_scheduler(self) -> None:
        overview.save_day_limits(self.db, self.amb, {"VACATION": 1})
        self._enter(self.a, "VACATION")
        # Another reason on the same day still has room.
        self._enter(self.b, "BUSINESS_TRIP")
        with self.assertRaises(HTTPException) as raised:
            self._enter(self.c, "VACATION")
        self.assertEqual(raised.exception.detail["code"], "day_limit_reached")
        record = self._enter(
            self.c, "VACATION", enforce_month_lock=False, entered_by_id=self.boss.id
        )
        self.assertEqual(record.entered_by_user_id, self.boss.id)

    def test_changing_the_reason_checks_the_limit_and_requeues(self) -> None:
        overview.save_day_limits(self.db, self.amb, {"VACATION": 1})
        self._enter(self.a, "VACATION")
        wish = self._enter(self.b, "PREFERRED")
        first_entered = wish.entered_at
        with self.assertRaises(HTTPException):
            update_unavailability(
                self.db, wish.id, self.b.id, UnavailabilityUpdate(reason="VACATION")
            )
        cannot = self._enter(self.c, "UNAVAILABLE")
        updated = update_unavailability(
            self.db, cannot.id, self.c.id, UnavailabilityUpdate(reason="BUSINESS_TRIP")
        )
        self.assertGreaterEqual(updated.entered_at, first_entered)

    def test_overview_counts_and_day_lists_in_entry_order(self) -> None:
        self._enter(self.b, "VACATION")
        self._enter(self.a, "VACATION")
        self._enter(self.c, None)  # an old record without a reason means "cannot"
        result = overview.month_overview(self.db, self.amb, 2026, 11)
        self.assertEqual(
            result["days"], [{"date": DAY, "counts": {"VACATION": 2, "UNAVAILABLE": 1}}]
        )
        detail = overview.day_entries(self.db, self.amb, DAY)
        self.assertEqual(
            [(entry["full_name"], entry["reason"]) for entry in detail["entries"]],
            [("b", "VACATION"), ("a", "VACATION"), ("c", "UNAVAILABLE")],
        )
        self.assertEqual(detail["entries"][0]["workplaces"], ["Ambulancia"])
        self.assertEqual(detail["entries"][0]["entered_by_name"], "b")

    def test_limits_and_overview_belong_to_one_workplace(self) -> None:
        overview.save_day_limits(self.db, self.other, {"VACATION": 0})
        self.assertIsNone(overview.day_limits(self.db, self.amb)["VACATION"])
        # The other workplace's limit does not touch this one's people...
        self._enter(self.a, "VACATION")
        # ...but refuses its own.
        with self.assertRaises(HTTPException):
            self._enter(self.outsider, "VACATION")
        self._enter(self.outsider, "BUSINESS_TRIP")
        self.assertEqual(
            overview.month_overview(self.db, self.amb, 2026, 11)["days"],
            [{"date": DAY, "counts": {"VACATION": 1}}],
        )
        self.assertEqual(
            overview.month_overview(self.db, self.other, 2026, 11)["days"],
            [{"date": DAY, "counts": {"BUSINESS_TRIP": 1}}],
        )
        self.assertEqual(
            [e["full_name"] for e in overview.day_entries(self.db, self.other, DAY)["entries"]],
            ["d"],
        )

    def test_a_member_of_two_workplaces_meets_both_limits(self) -> None:
        self.db.add(UserAmbulance(user_id=self.a.id, ambulance_id=self.other, is_active=True))
        self.db.commit()
        overview.save_day_limits(self.db, self.other, {"VACATION": 1})
        self._enter(self.outsider, "VACATION")
        with self.assertRaises(HTTPException):
            self._enter(self.a, "VACATION")
        self._enter(self.b, "VACATION")

    def test_inactive_accounts_are_not_counted(self) -> None:
        self._enter(self.a, "VACATION")
        self.a.is_active = False
        self.db.commit()
        self.assertEqual(overview.month_overview(self.db, self.amb, 2026, 11)["days"], [])


if __name__ == "__main__":
    unittest.main()
