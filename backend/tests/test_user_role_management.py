"""Tests for login defaults and administrator-managed application roles."""

import inspect
import unittest
from datetime import datetime, timedelta, timezone
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.dependencies import require_admin_role
from app.core.auth_provider import SessionAuthenticationProvider
from app.api.auth import google_auth
from app.db.session import Base
from app.models.associations import UserRole
from app.models.role import Role
from app.models.user import User
from app.services.auth_service import authenticate_user
from app.services.user_service import list_user_role_assignments, update_user_roles


class StubAuthenticationProvider:
    def __init__(self, user: User) -> None:
        self.user = user

    def resolve_user(self, _db, _credential: str) -> User:
        return self.user


class UserRoleManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        self.session.add_all(
            [
                Role(id=1, code="EMPLOYEE", name="Zamestnanec", level=1, is_active=True),
                Role(id=2, code="LEADER", name="Veduci", level=2, is_active=True),
                Role(
                    id=3,
                    code="AMBULANCE_OVERSEER",
                    name="Dohlad nad ambulanciou",
                    level=3,
                    is_active=True,
                ),
                Role(
                    id=4,
                    code="HOSPITAL_ADMIN",
                    name="Cela nemocnica",
                    level=4,
                    is_active=True,
                ),
            ]
        )
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _user(self, email: str, role_ids: list[int] | None = None) -> User:
        user = User(email=email, full_name=email.split("@")[0], is_active=True)
        self.session.add(user)
        self.session.flush()
        for role_id in role_ids or []:
            self.session.add(UserRole(user_id=user.id, role_id=role_id))
        self.session.commit()
        self.session.refresh(user)
        return user

    def _role_ids(self, user_id: int) -> list[int]:
        return [
            role_id
            for (role_id,) in self.session.query(UserRole.role_id)
            .filter(UserRole.user_id == user_id)
            .order_by(UserRole.role_id)
            .all()
        ]

    def test_login_assigns_role_one_when_user_has_no_role(self) -> None:
        user = self._user("new@example.com")

        authenticate_user(
            self.session,
            "credential",
            StubAuthenticationProvider(user),
        )

        self.assertEqual(self._role_ids(user.id), [1])

    def test_google_login_runs_in_fastapi_threadpool(self) -> None:
        """Synchronous Google I/O must not block the async event loop."""
        self.assertFalse(inspect.iscoroutinefunction(google_auth))

    def test_session_authentication_eager_loads_roles_in_one_query(self) -> None:
        """Authorization guards must not add lazy role queries per request."""
        credential = "benchmark-session-token"
        user = self._user("session@example.com", [3])
        user.auth_token = sha256(credential.encode("utf-8")).hexdigest()
        user.auth_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        self.session.commit()
        user_id = user.id
        self.session.expunge_all()

        statements: list[str] = []

        def record_statement(*args) -> None:
            statements.append(args[2])

        event.listen(self.engine, "before_cursor_execute", record_statement)
        try:
            authenticated = SessionAuthenticationProvider().resolve_user(
                self.session,
                credential,
            )
            self.assertEqual(authenticated.id, user_id)
            self.assertTrue(require_admin_role(authenticated))
        finally:
            event.remove(self.engine, "before_cursor_execute", record_statement)

        self.assertEqual(len(statements), 1, statements)

    def test_login_does_not_add_role_one_when_role_two_exists(self) -> None:
        user = self._user("leader@example.com", [2])

        authenticate_user(
            self.session,
            "credential",
            StubAuthenticationProvider(user),
        )

        self.assertEqual(self._role_ids(user.id), [2])

    def test_login_does_not_add_role_one_when_role_three_exists(self) -> None:
        user = self._user("overseer@example.com", [3])

        authenticate_user(
            self.session,
            "credential",
            StubAuthenticationProvider(user),
        )

        self.assertEqual(self._role_ids(user.id), [3])

    def test_login_does_not_add_role_one_when_role_four_exists(self) -> None:
        user = self._user("admin@example.com", [4])

        authenticate_user(
            self.session,
            "credential",
            StubAuthenticationProvider(user),
        )

        self.assertEqual(self._role_ids(user.id), [4])

    def test_role_one_is_not_duplicated_on_repeated_login(self) -> None:
        user = self._user("employee@example.com", [1])

        authenticate_user(self.session, "first", StubAuthenticationProvider(user))
        authenticate_user(self.session, "second", StubAuthenticationProvider(user))

        self.assertEqual(self._role_ids(user.id), [1])

    def test_roles_one_to_three_can_be_assigned_and_all_removed(self) -> None:
        user = self._user("managed@example.com", [1])

        updated = update_user_roles(self.session, user.id, [2, 3])
        self.assertEqual([role.id for role in updated.roles], [2, 3])

        updated = update_user_roles(self.session, user.id, [])
        self.assertEqual(updated.roles, [])
        self.assertEqual(self._role_ids(user.id), [])

        authenticate_user(
            self.session,
            "next-login",
            StubAuthenticationProvider(user),
        )
        self.assertEqual(self._role_ids(user.id), [1])

    def test_role_four_is_preserved_but_cannot_be_managed(self) -> None:
        user = self._user("hospital@example.com", [1, 4])

        updated = update_user_roles(self.session, user.id, [2])
        self.assertEqual([role.id for role in updated.roles], [2, 4])

        with self.assertRaises(HTTPException) as raised:
            update_user_roles(self.session, user.id, [4])
        self.assertEqual(raised.exception.status_code, 422)

    def test_only_role_three_or_higher_passes_admin_guard(self) -> None:
        role_two_user = self._user("role2@example.com", [2])
        role_three_user = self._user("role3@example.com", [3])

        with self.assertRaises(HTTPException) as raised:
            require_admin_role(role_two_user)
        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(require_admin_role(role_three_user).id, role_three_user.id)

    def test_assignment_list_contains_active_roles_for_each_user(self) -> None:
        self._user("one@example.com", [1])
        self._user("two@example.com", [2, 3])

        result = list_user_role_assignments(self.session)

        self.assertEqual(len(result), 2)
        self.assertEqual([role.id for role in result[0].roles], [1])
        self.assertEqual([role.id for role in result[1].roles], [2, 3])


if __name__ == "__main__":
    unittest.main()
