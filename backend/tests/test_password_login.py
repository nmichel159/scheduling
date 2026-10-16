"""Signing in with an e-mail and a password, setting, changing and resetting it."""

import unittest
from datetime import datetime, timedelta, timezone
import unittest.mock
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.session import Base, get_db
from app.main import app
from app.models import Ambulance, Role, User
from app.schemas.ambulance_employee import EmployeeAccountCreate, EmployeeProfileUpdate
from app.services import password_service
from app.services.ambulance_employee_service import create_employee_account, update_employee_profile
from app.services.auth_service import issue_session

LINK_PREFIX = "https://app.example.com/reset-password?token="


def _token_from(message) -> str:
    body = message.get_content()
    return body[body.index(LINK_PREFIX) + len(LINK_PREFIX):].split()[0]


class PasswordLoginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        db = self.Session()
        db.add(Role(id=1, code="EMPLOYEE", name="Employee", level=1, is_active=True))
        db.add(User(email="jana@example.com", full_name="Jana", is_active=True, login_count=0))
        db.add(User(email="off@example.com", full_name="Off", is_active=False, login_count=0))
        db.commit()
        db.close()

        def override_db():
            session = self.Session()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)
        password_service.failed_logins.clear()
        password_service.reset_requests.clear()

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_db, None)
        self.engine.dispose()

    def _mail(self, sent: list):
        """Patches under which mail 'goes out' into ``sent``."""
        return (
            patch.object(settings, "MAIL_DRY_RUN", True),
            patch.object(settings, "MAIL_FROM", "noreply@example.com"),
            patch.object(settings, "APP_URL", "https://app.example.com"),
            patch.object(password_service, "send_message", side_effect=sent.append),
        )

    def _user(self) -> User:
        db = self.Session()
        user = db.query(User).filter_by(email="jana@example.com").one()
        db.close()
        return user

    def _login(self, email: str, password: str, address: str | None = None):
        headers = {"X-Forwarded-For": address} if address else None
        return self.client.post(
            "/auth/login", json={"email": email, "password": password}, headers=headers
        )

    def _set_password(self, password: str) -> None:
        db = self.Session()
        user = db.query(User).filter_by(email="jana@example.com").one()
        user.password_hash = password_service.hash_password(password)
        db.commit()
        db.close()

    def _google_session(self) -> None:
        """Sign Jana in the way Google does: a session, but no password."""
        db = self.Session()
        user = db.query(User).filter_by(email="jana@example.com").one()
        token = issue_session(db, user)
        db.close()
        self.client.cookies.set(settings.SESSION_COOKIE_NAME, token)

    def _create_account(self, email: str):
        db = self.Session()
        ambulance = Ambulance(name="A")
        db.add(ambulance)
        db.commit()
        row = create_employee_account(
            db,
            ambulance.id,
            EmployeeAccountCreate(first_name="A", last_name="B", email=email),
        )
        token = db.get(User, row.user_id).password_reset_token
        db.close()
        return token

    def test_no_password_login_until_one_is_set(self) -> None:
        self.assertEqual(self._login("jana@example.com", "jana@example.com").status_code, 401)
        self.assertEqual(self._login("jana@example.com", "").status_code, 401)

        self._set_password("secret-123")
        response = self._login(" Jana@Example.com", "secret-123")
        self.assertEqual(response.status_code, 200)
        self.assertIn(settings.SESSION_COOKIE_NAME, response.cookies)
        self.assertEqual(response.json()["login_count"], 1)
        self.assertTrue(response.json()["has_password"])
        self.assertEqual(self.client.get("/roles/me").status_code, 200)
        self.assertTrue(self.client.get("/auth/me").json()["has_password"])

    def test_unknown_inactive_and_wrong_password_are_rejected_alike(self) -> None:
        self._set_password("secret-123")
        for email, password in (
            ("nobody@example.com", "secret-123"),
            ("off@example.com", "off@example.com"),
            ("jana@example.com", "wrong"),
        ):
            with self.subTest(email=email):
                response = self._login(email, password)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["detail"], "Invalid e-mail or password")

    def test_failures_are_throttled_per_client(self) -> None:
        self._set_password("secret-123")
        for _ in range(password_service.MAX_FAILED_LOGINS):
            self.assertEqual(self._login("jana@example.com", "wrong", "10.0.0.66").status_code, 401)
        blocked = self._login("jana@example.com", "secret-123", "10.0.0.66")
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("retry-after", blocked.headers)
        # Somebody else failing on purpose does not lock the owner out, and a
        # forged first entry does not make the same client somebody else.
        self.assertEqual(self._login("jana@example.com", "secret-123", "10.0.0.7").status_code, 200)
        self.assertEqual(
            self._login("jana@example.com", "secret-123", "1.2.3.4, 10.0.0.66").status_code, 429
        )

    def test_many_clients_together_are_throttled_per_account(self) -> None:
        self._set_password("secret-123")
        for i in range(password_service.MAX_FAILED_LOGINS_PER_ACCOUNT):
            self._login("jana@example.com", "wrong", f"10.1.0.{i}")
        self.assertEqual(self._login("jana@example.com", "secret-123", "10.9.9.9").status_code, 429)

    def test_signed_in_without_password_sets_one_without_current(self) -> None:
        self._google_session()
        self.assertFalse(self.client.get("/auth/me").json()["has_password"])
        ok = self.client.post(
            "/auth/password/change",
            json={"current_password": "", "new_password": "secret-123"},
        )
        self.assertEqual(ok.status_code, 204)
        self.assertEqual(self._login("jana@example.com", "secret-123").status_code, 200)

    def test_change_password_checks_the_current_one(self) -> None:
        self._set_password("secret-123")
        self._login("jana@example.com", "secret-123")
        wrong = self.client.post(
            "/auth/password/change",
            json={"current_password": "nope", "new_password": "other-1234"},
        )
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(wrong.json()["detail"], "wrong_current_password")
        for new, code in (("short", "password_too_short"), ("JANA@example.com", "password_equals_email")):
            response = self.client.post(
                "/auth/password/change",
                json={"current_password": "secret-123", "new_password": new},
            )
            self.assertEqual(response.json()["detail"], code)

        ok = self.client.post(
            "/auth/password/change",
            json={"current_password": "secret-123", "new_password": "other-1234"},
        )
        self.assertEqual(ok.status_code, 204)
        self.assertTrue(self._user().password_hash.startswith("scrypt$"))

        fresh = TestClient(app)
        self.assertEqual(
            fresh.post("/auth/login", json={"email": "jana@example.com", "password": "secret-123"}).status_code,
            401,
        )
        self.assertEqual(
            fresh.post("/auth/login", json={"email": "jana@example.com", "password": "other-1234"}).status_code,
            200,
        )

    def test_change_requires_a_session(self) -> None:
        response = self.client.post(
            "/auth/password/change",
            json={"current_password": "a", "new_password": "secret-123"},
        )
        self.assertEqual(response.status_code, 401)

    def test_new_account_is_mailed_a_setup_link(self) -> None:
        sent = []
        patches = self._mail(sent)
        with patches[0], patches[1], patches[2], patches[3]:
            self._create_account("novy@example.com")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["To"], "novy@example.com")
        self.assertEqual(sent[0]["Subject"], "Nastavenie hesla")
        token = _token_from(sent[0])

        self.assertEqual(self._login("novy@example.com", "novy@example.com").status_code, 401)
        ok = self.client.post("/auth/password/reset", json={"token": token, "new_password": "secret-123"})
        self.assertEqual(ok.status_code, 204)
        self.assertEqual(self._login("novy@example.com", "secret-123").status_code, 200)

    def test_changed_email_voids_the_old_link_and_mails_a_new_one(self) -> None:
        sent = []
        patches = self._mail(sent)
        with patches[0], patches[1], patches[2], patches[3]:
            self._create_account("preklep@example.com")
            db = self.Session()
            user = db.query(User).filter_by(email="preklep@example.com").one()
            ambulance_id = user.user_ambulances[0].ambulance_id
            update_employee_profile(
                db, ambulance_id, user,
                EmployeeProfileUpdate(full_name="A B", email="spravny@example.com"),
            )
            db.close()
        old_token, new_token = _token_from(sent[0]), _token_from(sent[1])
        self.assertEqual(sent[1]["To"], "spravny@example.com")
        stale = self.client.post("/auth/password/reset", json={"token": old_token, "new_password": "secret-123"})
        self.assertEqual(stale.status_code, 400)
        ok = self.client.post("/auth/password/reset", json={"token": new_token, "new_password": "secret-123"})
        self.assertEqual(ok.status_code, 204)

    def test_duplicate_email_differing_in_case_is_a_conflict(self) -> None:
        with patch.object(settings, "MAIL_DRY_RUN", False), patch.object(settings, "SMTP_HOST", ""):
            db = self.Session()
            db.add(User(email="Mixed@Example.com", full_name="Old", is_active=True))
            db.commit()
            db.close()
            with self.assertRaises(HTTPException) as ctx:
                self._create_account("mixed@example.com")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_new_account_without_mail_server_is_still_created(self) -> None:
        with patch.object(settings, "MAIL_DRY_RUN", False), patch.object(settings, "SMTP_HOST", ""):
            token = self._create_account("ab@example.com")
        self.assertIsNone(token)

    def test_forgot_and_reset_password(self) -> None:
        self._set_password("old-password")
        sent = []
        patches = self._mail(sent)
        with patches[0], patches[1], patches[2], patches[3]:
            unknown = self.client.post("/auth/password/forgot", json={"email": "nobody@example.com"})
            response = self.client.post("/auth/password/forgot", json={"email": "JANA@example.com"})
        self.assertEqual(unknown.status_code, 204)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["Subject"], "Zmena hesla")
        token = _token_from(sent[0])
        self.assertNotEqual(self._user().password_reset_token, token)

        bad = self.client.post("/auth/password/reset", json={"token": "x", "new_password": "secret-123"})
        self.assertEqual(bad.json()["detail"], "invalid_reset_link")
        ok = self.client.post("/auth/password/reset", json={"token": token, "new_password": "secret-123"})
        self.assertEqual(ok.status_code, 204)
        again = self.client.post("/auth/password/reset", json={"token": token, "new_password": "other-1234"})
        self.assertEqual(again.status_code, 400)
        self.assertEqual(self._login("jana@example.com", "old-password").status_code, 401)
        self.assertEqual(self._login("jana@example.com", "secret-123").status_code, 200)

    def test_forgot_without_a_password_sends_a_setup_mail(self) -> None:
        sent = []
        patches = self._mail(sent)
        with patches[0], patches[1], patches[2], patches[3]:
            self.client.post("/auth/password/forgot", json={"email": "jana@example.com"})
        self.assertEqual(sent[0]["Subject"], "Nastavenie hesla")

    def test_google_and_password_sign_in_to_the_same_account(self) -> None:
        self._set_password("secret-123")
        jana_id = self._user().id
        google = unittest.mock.Mock(status_code=200)
        google.json.return_value = {"email": "Jana@Example.com", "email_verified": True, "name": "Jana"}
        with patch("app.services.auth_service.requests.get", return_value=google):
            by_google = TestClient(app).post("/auth/google", json={"token": "t"})
        by_password = self._login("jana@example.com", "secret-123")
        self.assertEqual(by_google.status_code, 200)
        self.assertEqual(by_google.json()["id"], jana_id)
        self.assertEqual(by_password.json()["id"], jana_id)
        db = self.Session()
        self.assertEqual(db.query(User).filter(User.email.ilike("jana@example.com")).count(), 1)
        db.close()

    def test_expired_reset_link_is_rejected(self) -> None:
        db = self.Session()
        user = db.query(User).filter_by(email="jana@example.com").one()
        user.password_reset_token = password_service._digest("tok")
        user.password_reset_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
        db.close()
        response = self.client.post("/auth/password/reset", json={"token": "tok", "new_password": "secret-123"})
        self.assertEqual(response.status_code, 400)

    def test_forgot_without_mail_server_is_reported(self) -> None:
        with patch.object(settings, "MAIL_DRY_RUN", False), patch.object(settings, "SMTP_HOST", ""):
            response = self.client.post("/auth/password/forgot", json={"email": "jana@example.com"})
        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
