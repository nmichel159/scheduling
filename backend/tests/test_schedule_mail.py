"""Mailing a workplace's monthly schedule out to its clinic addresses."""

from datetime import date
import unittest
from unittest import mock

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.session import Base
from app.models import Ambulance, Competence, Schedule, User
from app.models.associations import UserAmbulance, UserCompetence
from app.models.schedule_mail import (
    DISPATCH_STATUS_DRY_RUN,
    DISPATCH_STATUS_FAILED,
    DISPATCH_STATUS_SENT,
)
from app.services import schedule_mail_service
from app.services.email_service import EmailDeliveryError, EmailNotConfiguredError
from app.services.schedule_mail_service import (
    add_recipient,
    build_schedule_mail,
    delete_recipient,
    list_dispatches,
    list_recipients,
    send_schedule_mail,
)


class ScheduleMailTests(unittest.TestCase):
    """One approved month, one clinic address, and the send around them."""

    def setUp(self) -> None:
        # Every send goes through build_message, which needs a sender; the
        # transport itself is mocked per test.
        sender = mock.patch.object(settings, "MAIL_FROM", "rozpisy@nemocnica.sk")
        sender.start()
        self.addCleanup(sender.stop)

        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.manager = User(
            email="manager@example.com",
            full_name="Manager",
            is_active=True,
        )
        self.employee = User(
            email="employee@example.com",
            full_name="Employee",
            is_active=True,
        )
        self.ambulance = Ambulance(name="Cardiology", isurgent=False, is_active=True)
        self.db.add_all([self.manager, self.employee, self.ambulance])
        self.db.flush()
        self.competence = Competence(
            name="Physician",
            ambulance_id=self.ambulance.id,
            required_count=1,
            is_active=True,
        )
        self.db.add(self.competence)
        self.db.flush()
        self.db.add_all(
            [
                UserAmbulance(
                    user_id=self.employee.id,
                    ambulance_id=self.ambulance.id,
                    is_active=True,
                ),
                UserCompetence(
                    user_id=self.employee.id,
                    competence_id=self.competence.id,
                    is_active=True,
                ),
                Schedule(
                    user_id=self.employee.id,
                    ambulance_id=self.ambulance.id,
                    competence_id=self.competence.id,
                    work_date=date(2026, 8, 15),
                    is_active=True,
                    is_approved=True,
                ),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    # -- address book ----------------------------------------------------

    def test_recipient_is_added_validated_and_deduplicated(self) -> None:
        """A workplace keeps a list of valid, distinct addresses."""
        added = add_recipient(self.db, self.ambulance.id, " klinika@nemocnica.sk ", "Sekretariát")
        self.assertEqual(added.email, "klinika@nemocnica.sk")
        self.assertEqual(added.label, "Sekretariát")

        with self.assertRaises(HTTPException) as invalid:
            add_recipient(self.db, self.ambulance.id, "not-an-address")
        self.assertEqual(invalid.exception.status_code, 422)

        with self.assertRaises(HTTPException) as duplicate:
            add_recipient(self.db, self.ambulance.id, "klinika@nemocnica.sk")
        self.assertEqual(duplicate.exception.status_code, 409)

    def test_removed_recipient_disappears_and_can_be_added_back(self) -> None:
        """Removal is reversible and leaves the dispatch log readable."""
        added = add_recipient(self.db, self.ambulance.id, "klinika@nemocnica.sk")
        delete_recipient(self.db, self.ambulance.id, added.id)
        self.assertEqual(list_recipients(self.db, self.ambulance.id), [])

        revived = add_recipient(self.db, self.ambulance.id, "klinika@nemocnica.sk", "Nová")
        self.assertEqual(revived.id, added.id)
        self.assertEqual(revived.label, "Nová")
        self.assertEqual(len(list_recipients(self.db, self.ambulance.id)), 1)

    # -- what gets built -------------------------------------------------

    def test_message_lists_every_duty_of_the_month(self) -> None:
        """The body is readable on its own; the CSV carries the same rows."""
        content = build_schedule_mail(self.db, self.ambulance, 8, 2026, "Dobrý deň")
        self.assertEqual(content["entry_count"], 1)
        self.assertIn("Cardiology", content["subject"])
        self.assertIn("august 2026", content["subject"])
        self.assertIn("Dobrý deň", content["text_body"])
        self.assertIn("2026-08-15", content["text_body"])
        self.assertIn("Employee", content["text_body"])
        filename, subtype, payload = content["attachment"]
        self.assertEqual((filename, subtype), ("rozpis.csv", "csv"))
        self.assertIn("2026-08-15", payload.decode("utf-8"))

    def test_empty_month_is_refused(self) -> None:
        with self.assertRaises(HTTPException) as refused:
            build_schedule_mail(self.db, self.ambulance, 9, 2026)
        self.assertEqual(refused.exception.status_code, 409)
        self.assertEqual(refused.exception.detail["code"], "empty_schedule")

    def test_unapproved_month_is_refused(self) -> None:
        """A draft the employees cannot see yet must not reach the clinic."""
        entry = self.db.query(Schedule).one()
        entry.is_approved = False
        self.db.commit()

        with self.assertRaises(HTTPException) as refused:
            build_schedule_mail(self.db, self.ambulance, 8, 2026)
        self.assertEqual(refused.exception.status_code, 409)
        self.assertEqual(refused.exception.detail["code"], "not_approved")

    # -- sending ---------------------------------------------------------

    def test_send_without_recipients_is_refused(self) -> None:
        with self.assertRaises(HTTPException) as refused:
            send_schedule_mail(self.db, self.ambulance, 8, 2026, self.manager)
        self.assertEqual(refused.exception.status_code, 409)
        self.assertEqual(refused.exception.detail["code"], "no_recipients")

    def test_successful_send_is_recorded_with_its_addresses(self) -> None:
        add_recipient(self.db, self.ambulance.id, "klinika@nemocnica.sk")
        add_recipient(self.db, self.ambulance.id, "primar@nemocnica.sk")

        with mock.patch.object(
            schedule_mail_service, "send_message", return_value="sent"
        ) as send:
            dispatch = send_schedule_mail(self.db, self.ambulance, 8, 2026, self.manager)

        sent_message = send.call_args.args[0]
        self.assertEqual(
            sent_message["To"],
            "klinika@nemocnica.sk, primar@nemocnica.sk",
        )
        self.assertEqual(dispatch.status, DISPATCH_STATUS_SENT)
        self.assertEqual(dispatch.entry_count, 1)
        self.assertEqual(dispatch.sent_by_user_id, self.manager.id)
        self.assertEqual(
            dispatch.recipients,
            "klinika@nemocnica.sk, primar@nemocnica.sk",
        )
        self.assertEqual(len(list_dispatches(self.db, self.ambulance.id)), 1)

    def test_send_can_be_limited_to_selected_addresses(self) -> None:
        """A resend to one mailbox must not mail the whole list again."""
        first = add_recipient(self.db, self.ambulance.id, "klinika@nemocnica.sk")
        add_recipient(self.db, self.ambulance.id, "primar@nemocnica.sk")

        with mock.patch.object(schedule_mail_service, "send_message", return_value="sent"):
            dispatch = send_schedule_mail(
                self.db,
                self.ambulance,
                8,
                2026,
                self.manager,
                recipient_ids=[first.id],
            )

        self.assertEqual(dispatch.recipients, "klinika@nemocnica.sk")

    def test_delivery_failure_is_recorded_rather_than_raised(self) -> None:
        """The scheduler must be able to see that a send did not happen."""
        add_recipient(self.db, self.ambulance.id, "klinika@nemocnica.sk")

        with mock.patch.object(
            schedule_mail_service,
            "send_message",
            side_effect=EmailDeliveryError("connection refused"),
        ):
            dispatch = send_schedule_mail(self.db, self.ambulance, 8, 2026, self.manager)

        self.assertEqual(dispatch.status, DISPATCH_STATUS_FAILED)
        self.assertEqual(dispatch.error, "connection refused")
        self.assertEqual(list_dispatches(self.db, self.ambulance.id)[0].id, dispatch.id)

    def test_dry_run_is_recorded_as_such(self) -> None:
        add_recipient(self.db, self.ambulance.id, "klinika@nemocnica.sk")

        with mock.patch.object(
            schedule_mail_service, "send_message", return_value="dry-run"
        ):
            dispatch = send_schedule_mail(self.db, self.ambulance, 8, 2026, self.manager)

        self.assertEqual(dispatch.status, DISPATCH_STATUS_DRY_RUN)

    def test_unconfigured_mail_server_is_reported_not_logged(self) -> None:
        """Nothing was attempted, so nothing is written into the log."""
        add_recipient(self.db, self.ambulance.id, "klinika@nemocnica.sk")

        with mock.patch.object(
            schedule_mail_service,
            "send_message",
            side_effect=EmailNotConfiguredError("SMTP_HOST is not configured."),
        ):
            with self.assertRaises(HTTPException) as refused:
                send_schedule_mail(self.db, self.ambulance, 8, 2026, self.manager)

        self.assertEqual(refused.exception.status_code, 503)
        self.assertEqual(list_dispatches(self.db, self.ambulance.id), [])


if __name__ == "__main__":
    unittest.main()
