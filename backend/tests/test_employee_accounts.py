"""Creating and editing accounts from the scheduler's employee screen."""

import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models import Ambulance, User
from app.models.associations import UserAmbulance
from app.schemas.ambulance_employee import EmployeeAccountCreate, EmployeeProfileUpdate
from app.services.ambulance_employee_service import (
    create_employee_account,
    update_employee_profile,
)


class EmployeeAccountTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.ambulance = Ambulance(name="A")
        self.db.add(self.ambulance)
        self.db.commit()

    def test_create_assigns_to_ambulance_and_normalises(self) -> None:
        row = create_employee_account(
            self.db,
            self.ambulance.id,
            EmployeeAccountCreate(first_name=" Jana ", last_name="Nová", email="Jana@Example.com "),
        )
        self.assertEqual(row.email, "jana@example.com")
        self.assertEqual(row.full_name, "Jana Nová")
        link = self.db.query(UserAmbulance).filter_by(user_id=row.user_id).one()
        self.assertEqual(link.ambulance_id, self.ambulance.id)

    def test_duplicate_email_is_conflict(self) -> None:
        data = EmployeeAccountCreate(first_name="A", last_name="B", email="a@b.sk")
        create_employee_account(self.db, self.ambulance.id, data)
        with self.assertRaises(HTTPException) as ctx:
            create_employee_account(self.db, self.ambulance.id, data)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_invalid_email_rejected_and_profile_update(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            create_employee_account(
                self.db,
                self.ambulance.id,
                EmployeeAccountCreate(first_name="A", last_name="B", email="nope"),
            )
        self.assertEqual(ctx.exception.status_code, 422)
        row = create_employee_account(
            self.db,
            self.ambulance.id,
            EmployeeAccountCreate(first_name="A", last_name="B", email="a@b.sk"),
        )
        user = self.db.get(User, row.user_id)
        out = update_employee_profile(
            self.db, self.ambulance.id, user, EmployeeProfileUpdate(full_name="MUDr. Adam Boh", email="adam@b.sk")
        )
        self.assertEqual((out.full_name, out.email), ("MUDr. Adam Boh", "adam@b.sk"))


if __name__ == "__main__":
    unittest.main()
