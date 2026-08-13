"""Regression tests for internal-deployment security hardening."""

import unittest

from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.main import app
from app.api import schedules as schedules_api
from app.models import Ambulance, AuditLog, User
from app.services.audit_service import AUDIT_ACTOR_KEY, install_audit_hooks
from app.schemas.ambulance import AmbulanceCreate
from app.schemas.ambulance_competences import (
    AmbulanceEmployeeCompetenceTableUpdate,
    AmbulanceEmployeeCompetenceUpdate,
)


class ApiSecurityRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_previously_public_identity_and_codebook_routes_require_login(self) -> None:
        for path in (
            "/ambulances/employees/1/ambulances",
            "/ambulances/managers/1/ambulances",
            "/ambulances",
            "/roles",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)

    def test_every_business_route_has_an_authentication_dependency(self) -> None:
        authentication_dependencies = {
            "get_current_user",
            "get_manager_ambulance",
            "require_admin_role",
            "require_manager_role",
        }
        intentionally_public = {"/", "/auth/google"}

        for route in app.routes:
            if not isinstance(route, APIRoute) or route.path in intentionally_public:
                continue
            dependency_names: set[str] = set()
            dependencies = list(route.dependant.dependencies)
            while dependencies:
                dependency = dependencies.pop()
                dependency_names.add(
                    getattr(dependency.call, "__name__", str(dependency.call))
                )
                dependencies.extend(dependency.dependencies)
            with self.subTest(path=route.path, methods=route.methods):
                self.assertFalse(
                    authentication_dependencies.isdisjoint(dependency_names),
                    f"Business route {route.path} has no authentication dependency.",
                )

    def test_cors_does_not_trust_arbitrary_vercel_subdomains(self) -> None:
        response = self.client.options(
            "/auth/me",
            headers={
                "Origin": "https://attacker.vercel.app",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_large_or_unbounded_business_payloads_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AmbulanceCreate(name="x" * 201)
        with self.assertRaises(ValidationError):
            AmbulanceEmployeeCompetenceTableUpdate(
                employees=[
                    AmbulanceEmployeeCompetenceUpdate(user_id=1, competence_ids=[])
                ]
                * 2001
            )

    def test_parallel_solver_work_is_rejected_before_consuming_resources(self) -> None:
        self.assertTrue(schedules_api._schedule_generation_slots.acquire(blocking=False))
        try:
            with self.assertRaises(HTTPException) as raised:
                schedules_api.generate_ambulance_schedule_endpoint(
                    month=8,
                    year=2026,
                    ambulance=Ambulance(id=1, name="Clinic", is_active=True),
                    db=None,
                )
        finally:
            schedules_api._schedule_generation_slots.release()

        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.headers, {"Retry-After": "5"})


class TransactionalAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(bind=self.engine)()
        install_audit_hooks()
        actor = User(email="actor@example.com", full_name="Actor", is_active=True)
        self.session.add(actor)
        self.session.commit()
        self.actor_id = actor.id
        self.session.info[AUDIT_ACTOR_KEY] = self.actor_id

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_create_update_delete_are_audited_without_business_values(self) -> None:
        ambulance = Ambulance(
            name="Sensitive clinic name",
            managed_by_user_id=self.actor_id,
            is_active=True,
        )
        self.session.add(ambulance)
        self.session.commit()
        entity_id = str(ambulance.id)

        ambulance.description = "Sensitive description"
        self.session.commit()
        self.session.delete(ambulance)
        self.session.commit()

        logs = (
            self.session.query(AuditLog)
            .filter(AuditLog.entity_type == "ambulances")
            .order_by(AuditLog.id)
            .all()
        )
        self.assertEqual([log.action for log in logs], ["CREATE", "UPDATE", "DELETE"])
        self.assertTrue(all(log.user_id == self.actor_id for log in logs))
        self.assertTrue(all(log.entity_id == entity_id for log in logs))
        serialized_changes = str([log.changes for log in logs])
        self.assertIn("description", serialized_changes)
        self.assertNotIn("Sensitive clinic name", serialized_changes)
        self.assertNotIn("Sensitive description", serialized_changes)

    def test_rolled_back_write_does_not_leave_an_audit_row(self) -> None:
        self.session.add(Ambulance(name="Rolled back", is_active=True))
        self.session.flush()
        self.session.rollback()

        self.assertEqual(self.session.query(AuditLog).count(), 0)


if __name__ == "__main__":
    unittest.main()
