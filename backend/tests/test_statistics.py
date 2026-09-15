"""Hospital-wide yearly statistics (role level >= 4)."""

from datetime import date
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models import Ambulance, Competence, Schedule, User
from app.services.statistics_service import TOP_EMPLOYEE_LIMIT, get_yearly_statistics


class YearlyStatisticsTests(unittest.TestCase):
    """Counts must split planned from already-worked and ignore other years."""

    def setUp(self) -> None:
        """Two workplaces, two employees, duties spread across 2026."""
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.anna = User(email="anna@example.com", full_name="Anna", is_active=True)
        self.boris = User(email="boris@example.com", full_name="Boris", is_active=True)
        self.db.add_all([self.anna, self.boris])
        self.db.flush()

        self.first = Ambulance(name="Anaesthesia", isurgent=False, is_active=True)
        self.second = Ambulance(name="Cardiology", isurgent=False, is_active=True)
        self.idle = Ambulance(name="Zoology", isurgent=False, is_active=True)
        self.db.add_all([self.first, self.second, self.idle])
        self.db.flush()

        self.competences = {}
        for ambulance in (self.first, self.second, self.idle):
            competence = Competence(
                name="Physician",
                ambulance_id=ambulance.id,
                required_count=1,
                is_active=True,
            )
            self.db.add(competence)
            self.db.flush()
            self.competences[ambulance.id] = competence

        self.db.add_all(
            [
                # Two March days at the first workplace, one of them shared by
                # both employees, so the duty count (3) and the head count (2)
                # must not be confused for each other.
                self._shift(self.anna, self.first, date(2026, 3, 2)),
                self._shift(self.boris, self.first, date(2026, 3, 2)),
                self._shift(self.anna, self.first, date(2026, 3, 3)),
                # One in July, after the reference day used below.
                self._shift(self.anna, self.second, date(2026, 7, 9)),
                # Neighbouring years must not leak into the report.
                self._shift(self.anna, self.first, date(2025, 12, 31)),
                self._shift(self.anna, self.first, date(2027, 1, 1)),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _shift(self, user: User, ambulance: Ambulance, work_date: date) -> Schedule:
        return Schedule(
            user_id=user.id,
            ambulance_id=ambulance.id,
            competence_id=self.competences[ambulance.id].id,
            work_date=work_date,
            is_active=True,
        )

    def _report(self, today: date = date(2026, 5, 1)):
        return get_yearly_statistics(self.db, 2026, today=today)

    def _workplaces(self, today: date = date(2026, 5, 1)):
        return {item.ambulance_name: item for item in self._report(today).workplaces}

    def test_totals_cover_only_the_reported_year(self) -> None:
        report = self._report()
        self.assertEqual(report.year, 2026)
        self.assertEqual(report.total_shift_count, 4)
        self.assertEqual(report.employee_count, 2)

    def test_worked_counts_stop_at_the_reference_day(self) -> None:
        """"Worked" is what has already happened, not what is planned."""
        report = self._report()
        self.assertEqual(report.through_date, "2026-05-01")
        # The three March duties are behind us; the July one is not.
        self.assertEqual(report.worked_shift_count, 3)

    def test_finished_year_reports_its_own_last_day(self) -> None:
        """A closed year's totals must not keep moving with the clock."""
        report = self._report(today=date(2030, 6, 15))
        self.assertEqual(report.through_date, "2026-12-31")
        self.assertEqual(report.worked_shift_count, report.total_shift_count)

    def test_future_year_has_nothing_worked(self) -> None:
        report = self._report(today=date(2025, 6, 1))
        self.assertEqual(report.through_date, "2025-12-31")
        self.assertEqual(report.worked_shift_count, 0)
        self.assertEqual(report.total_shift_count, 4)

    def test_workplace_row_separates_shifts_from_people(self) -> None:
        """Three duties over two days held by two people must not collapse."""
        row = self._workplaces()["Anaesthesia"]
        self.assertEqual(row.shift_count, 3)
        self.assertEqual(row.employee_count, 2)
        self.assertEqual(row.worked_shift_count, 3)

    def test_workplace_without_duties_is_still_listed(self) -> None:
        """An unplanned workplace is the finding, not a row to omit."""
        rows = self._workplaces()
        self.assertIn("Zoology", rows)
        self.assertEqual(rows["Zoology"].shift_count, 0)
        report = self._report()
        self.assertEqual(report.workplace_count, 3)
        self.assertEqual(report.staffed_workplace_count, 2)

    def test_monthly_series_always_has_twelve_entries(self) -> None:
        """The caller charts the year directly, so empty months must be there."""
        by_month = self._report().by_month
        self.assertEqual([item.month for item in by_month], list(range(1, 13)))
        counts = {item.month: item.shift_count for item in by_month}
        self.assertEqual(counts[3], 3)
        self.assertEqual(counts[7], 1)
        self.assertEqual(counts[1], 0)
        worked = {item.month: item.worked_shift_count for item in by_month}
        self.assertEqual(worked[7], 0)

    def test_employees_are_ranked_by_duty_count(self) -> None:
        employees = self._report().employees
        self.assertEqual([item.full_name for item in employees], ["Anna", "Boris"])
        anna = employees[0]
        self.assertEqual(anna.shift_count, 3)
        self.assertEqual(anna.ambulance_count, 2)
        self.assertEqual(employees[1].shift_count, 1)

    def test_employee_ranking_is_capped(self) -> None:
        """The report shows a short leaderboard, not every employee."""
        for index in range(TOP_EMPLOYEE_LIMIT + 3):
            extra = User(
                email=f"extra{index}@example.com",
                full_name=f"Extra {index}",
                is_active=True,
            )
            self.db.add(extra)
            self.db.flush()
            self.db.add(self._shift(extra, self.first, date(2026, 4, 1)))
        self.db.commit()
        self.assertEqual(len(self._report().employees), TOP_EMPLOYEE_LIMIT)

    def test_inactive_rows_are_excluded(self) -> None:
        self.idle.is_active = False
        for entry in self.db.query(Schedule).filter(
            Schedule.ambulance_id == self.second.id
        ):
            entry.is_active = False
        self.db.commit()
        report = self._report()
        self.assertEqual(report.workplace_count, 2)
        self.assertEqual(report.total_shift_count, 3)
        self.assertNotIn("Zoology", {item.ambulance_name for item in report.workplaces})


if __name__ == "__main__":
    unittest.main()
