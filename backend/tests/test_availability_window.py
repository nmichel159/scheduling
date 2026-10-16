"""The restriction window: lock day, hand-set lock, and the monthly reminder."""

import unittest
from datetime import date, datetime
from unittest import mock
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.session import Base
from app.models.ambulance import Ambulance
from app.models.associations import UserAmbulance
from app.models.user import User
from app.schemas.unavailability import UnavailabilityCreate
from app.services import availability_window_service as window
from app.services.unavailability_service import create_unavailability

TZ = ZoneInfo("Europe/Bratislava")


class AvailabilityWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.today = date(2026, 10, 10)
        today = mock.patch.object(window, "local_today", lambda: self.today)
        today.start()
        self.addCleanup(today.stop)
        for name, value in (
            ("MAIL_FROM", "rozpisy@nemocnica.sk"),
            ("MAIL_DRY_RUN", True),
            ("AVAILABILITY_REMINDER_HOUR", 8),
        ):
            patch = mock.patch.object(settings, name, value)
            patch.start()
            self.addCleanup(patch.stop)

        ambulance = Ambulance(name="Ambulancia", is_active=True)
        closed = Ambulance(name="Zatvorená", is_active=False)
        self.db.add_all([ambulance, closed])
        self.db.flush()
        for email, place in (
            ("a@nemocnica.sk", ambulance),
            ("b@nemocnica.sk", ambulance),
            ("c@nemocnica.sk", closed),
        ):
            user = User(email=email, full_name=email, is_active=True)
            self.db.add(user)
            self.db.flush()
            self.db.add(
                UserAmbulance(user_id=user.id, ambulance_id=place.id, is_active=True)
            )
        self.db.commit()
        self.employee = self.db.query(User).filter_by(email="a@nemocnica.sk").one()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _status(self, year=2026, month=11):
        return window.month_status(self.db, year, month, self.today)

    def test_next_month_closes_on_the_lock_day(self) -> None:
        self.today = date(2026, 10, 14)
        self.assertFalse(self._status()["locked"])
        self.today = date(2026, 10, 15)
        self.assertTrue(self._status()["locked"])
        # The month after it is still open.
        self.assertFalse(self._status(2026, 12)["locked"])

    def test_scheduler_days_move_the_lock(self) -> None:
        window.save_window_days(self.db, 18, 20)
        self.today = date(2026, 10, 19)
        self.assertFalse(self._status()["locked"])
        self.assertEqual(self._status()["lock_date"], date(2026, 10, 20))
        self.assertEqual(self._status()["reminder_date"], date(2026, 10, 18))

    def test_reminder_must_come_before_the_lock(self) -> None:
        for reminder, lock in ((15, 15), (16, 15), (0, 10), (10, 29)):
            with self.assertRaises(HTTPException):
                window.save_window_days(self.db, reminder, lock)

    def test_hand_set_lock_wins_both_ways(self) -> None:
        window.set_month_lock(self.db, 2026, 11, True)
        self.assertTrue(self._status()["locked"])
        self.today = date(2026, 10, 20)
        window.set_month_lock(self.db, 2026, 11, False)
        self.assertFalse(self._status()["locked"])
        self.assertFalse(self._status()["manual"])

    def test_past_month_stays_closed(self) -> None:
        with self.assertRaises(HTTPException):
            window.set_month_lock(self.db, 2026, 9, False)
        self.assertTrue(self._status(2026, 9)["locked"])

    def test_employee_is_refused_but_scheduler_is_not(self) -> None:
        window.set_month_lock(self.db, 2026, 11, True)
        payload = UnavailabilityCreate(date_absent=date(2026, 11, 3), reason="VACATION")
        with mock.patch(
            "app.services.unavailability_service._first_day_of_current_month",
            lambda: date(2026, 10, 1),
        ):
            with self.assertRaises(HTTPException) as raised:
                create_unavailability(self.db, self.employee.id, payload)
            self.assertEqual(raised.exception.detail["code"], "month_locked")
            record = create_unavailability(
                self.db, self.employee.id, payload, enforce_month_lock=False
            )
        self.assertEqual(record.date_absent, date(2026, 11, 3))

    def test_reminder_goes_once_on_its_day_to_each_employee(self) -> None:
        sent = []
        with mock.patch.object(
            window, "send_message", lambda message: sent.append(message["To"]) or "sent"
        ):
            self.assertIsNone(
                window.send_due_reminder(self.db, datetime(2026, 10, 13, 9, tzinfo=TZ))
            )
            self.assertIsNone(
                window.send_due_reminder(self.db, datetime(2026, 10, 14, 7, tzinfo=TZ))
            )
            self.assertEqual(
                window.send_due_reminder(self.db, datetime(2026, 10, 14, 8, tzinfo=TZ)),
                "sent",
            )
            self.assertIsNone(
                window.send_due_reminder(self.db, datetime(2026, 10, 14, 9, tzinfo=TZ))
            )
        # One message each, and nobody from a closed workplace.
        self.assertEqual(sent, ["a@nemocnica.sk", "b@nemocnica.sk"])
        status = self._status()
        self.assertEqual(status["reminder_status"], "sent")
        self.assertEqual(status["reminder_recipients"], 2)

    def test_closed_month_is_not_announced(self) -> None:
        window.set_month_lock(self.db, 2026, 11, True)
        with mock.patch.object(window, "send_message") as send:
            outcome = window.send_due_reminder(
                self.db, datetime(2026, 10, 14, 9, tzinfo=TZ)
            )
        self.assertEqual(outcome, "skipped")
        send.assert_not_called()

    def test_message_names_the_last_day_and_the_lock(self) -> None:
        message = window.reminder_message(self.db, 2026, 11)
        self.assertIn("november 2026", message["subject"])
        self.assertIn("14. 10. 2026", message["subject"])
        self.assertIn("Od 15. 10.", message["body"])


if __name__ == "__main__":
    unittest.main()
