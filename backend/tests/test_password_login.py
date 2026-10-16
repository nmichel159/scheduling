"""Signing in with an e-mail and a password, changing it and resetting it."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.session import Base, get_db
from app.main import app
from app.models import Role, User
from app.services import password_service


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

    def _user(self) -> User:
        db = self.Session()
        user = db.query(User).filter_by(email="jana@example.com").one()
        db.close()
        return user

    def _login(self, email: str, password: str):
        return self.client.post("/auth/login", json={"email": email, "password": password})

    def test_initial_password_is_the_email(self) -> None:
        response = self._login(" Jana@Example.com", "jana@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertIn(settings.SESSION_COOKIE_NAME, response.cookies)
        self.assertEqual(response.json()["login_count"], 1)
        self.assertEqual(self.client.get("/roles/me").status_code, 200)

    def test_unknown_inactive_and_wrong_password_are_rejected_alike(self) -> None:
        for email, password in (
            ("nobody@example.com", "nobody@example.com"),
            ("off@example.com", "off@example.com"),
            ("jana@example.com", "wrong"),
        ):
            with self.subTest(email=email):
                response = self._login(email, password)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["detail"], "Invalid e-mail or password")

    def test_repeated_failures_are_throttled(self) -> None:
        for _ in range(password_service.MAX_FAILED_LOGINS):
            self.assertEqual(self._login("jana@example.com", "wrong").status_code, 401)
        response = self._login("jana@example.com", "jana@example.com")
        self.assertEqual(response.status_code, 429)
        self.assertIn("retry-after", response.headers)

    def test_change_password_replaces_the_initial_one(self) -> None:
        self._login("jana@example.com", "jana@example.com")
        wrong = self.client.post(
            "/auth/password/change",
            json={"current_password": "nope", "new_password": "secret-123"},
        )
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(wrong.json()["detail"], "wrong_current_password")
        for new, code in (("short", "password_too_short"), ("JANA@example.com", "password_equals_email")):
            response = self.client.post(
                "/auth/password/change",
                json={"current_password": "jana@example.com", "new_password": new},
            )
            self.assertEqual(response.json()["detail"], code)

        ok = self.client.post(
            "/auth/password/change",
            json={"current_password": "jana@example.com", "new_password": "secret-123"},
        )
        self.assertEqual(ok.status_code, 204)
        self.assertTrue(self._user().password_hash.startswith("scrypt$"))

        fresh = TestClient(app)
        self.assertEqual(
            fresh.post("/auth/login", json={"email": "jana@example.com", "password": "jana@example.com"}).status_code,
            401,
        )
        self.assertEqual(
            fresh.post("/auth/login", json={"email": "jana@example.com", "password": "secret-123"}).status_code,
            200,
        )

    def test_change_requires_a_session(self) -> None:
        response = self.client.post(
            "/auth/password/change",
            json={"current_password": "a", "new_password": "secret-123"},
        )
        self.assertEqual(response.status_code, 401)

    def test_forgot_and_reset_password(self) -> None:
        sent = []
        with (
            patch.object(settings, "MAIL_DRY_RUN", True),
            patch.object(settings, "MAIL_FROM", "noreply@example.com"),
            patch.object(settings, "APP_URL", "https://app.example.com"),
            patch.object(password_service, "send_message", side_effect=sent.append),
        ):
            unknown = self.client.post("/auth/password/forgot", json={"email": "nobody@example.com"})
            response = self.client.post("/auth/password/forgot", json={"email": "JANA@example.com"})
        self.assertEqual(unknown.status_code, 204)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(len(sent), 1)
        body = sent[0].get_content()
        prefix = "https://app.example.com/reset-password?token="
        token = body[body.index(prefix) + len(prefix):].split()[0]
        self.assertNotEqual(self._user().password_reset_token, token)

        bad = self.client.post("/auth/password/reset", json={"token": "x", "new_password": "secret-123"})
        self.assertEqual(bad.json()["detail"], "invalid_reset_link")
        ok = self.client.post("/auth/password/reset", json={"token": token, "new_password": "secret-123"})
        self.assertEqual(ok.status_code, 204)
        again = self.client.post("/auth/password/reset", json={"token": token, "new_password": "other-1234"})
        self.assertEqual(again.status_code, 400)
        self.assertEqual(self._login("jana@example.com", "secret-123").status_code, 200)

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
