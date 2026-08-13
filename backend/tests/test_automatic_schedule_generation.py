"""Automatic monthly schedule clock, ordering, and idempotency tests."""

import asyncio
from datetime import datetime
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main as main_module
from app.db.session import Base
from app.models import Ambulance, Competence
from app.schemas.schedule import ScheduleGenerationResponse
from app.services import automatic_schedule_generation_service as automatic
from app.services.schedule_generation_service import ScheduleGenerationError


class AutomaticScheduleClockTests(unittest.TestCase):
    """Verify the server clock boundary without waiting for wall-clock time."""

    def test_monthly_deadline_and_year_boundary(self) -> None:
        """Only 21st at 20:00 or later targets the immediately following month."""
        zone = ZoneInfo("Europe/Bratislava")
        self.assertIsNone(
            automatic.due_target_period(datetime(2026, 8, 21, 19, 59, tzinfo=zone))
        )
        self.assertEqual(
            automatic.due_target_period(datetime(2026, 8, 21, 20, 0, tzinfo=zone)),
            (2026, 9),
        )
        self.assertEqual(
            automatic.due_target_period(datetime(2026, 12, 31, 23, 0, tzinfo=zone)),
            (2027, 1),
        )

    def test_background_loop_executes_time_check(self) -> None:
        """A running server task wakes and executes its time checker."""
        stop_event = asyncio.Event()
        calls: list[str] = []

        def check() -> None:
            calls.append("checked")
            stop_event.set()

        asyncio.run(
            automatic.automatic_schedule_generation_loop(
                stop_event,
                check=check,
                poll_seconds=0.01,
            )
        )
        self.assertEqual(calls, ["checked"])

    def test_fastapi_lifespan_starts_and_stops_monthly_clock(self) -> None:
        """Starting the API server owns the background clock lifecycle."""

        async def exercise_lifespan() -> list[str]:
            calls: list[str] = []
            started = asyncio.Event()

            async def fake_loop(stop_event: asyncio.Event) -> None:
                calls.append("started")
                started.set()
                await stop_event.wait()
                calls.append("stopped")

            with (
                mock.patch.object(
                    main_module,
                    "automatic_schedule_generation_loop",
                    side_effect=fake_loop,
                ),
                mock.patch.object(
                    main_module.settings,
                    "AUTOMATIC_SCHEDULE_GENERATION_ENABLED",
                    True,
                ),
            ):
                async with main_module.lifespan(main_module.app):
                    await asyncio.wait_for(started.wait(), timeout=0.2)
            return calls

        self.assertEqual(asyncio.run(exercise_lifespan()), ["started", "stopped"])


class AutomaticScheduleGenerationTests(unittest.TestCase):
    """Verify deterministic sequential processing and persistent claiming."""

    def setUp(self) -> None:
        """Create urgent and non-urgent workplaces of different demand sizes."""
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        small = Ambulance(name="Small", isurgent=False, is_active=True)
        large = Ambulance(name="Large", isurgent=False, is_active=True)
        urgent = Ambulance(name="Urgent", isurgent=True, is_active=True)
        self.db.add_all([small, large, urgent])
        self.db.flush()
        self.db.add_all(
            [
                Competence(
                    name="Small role",
                    ambulance_id=small.id,
                    required_count=1,
                    is_active=True,
                ),
                Competence(
                    name="Large role",
                    ambulance_id=large.id,
                    required_count=2,
                    is_active=True,
                ),
                Competence(
                    name="Urgent role",
                    ambulance_id=urgent.id,
                    required_count=10,
                    is_active=True,
                ),
            ]
        )
        self.db.commit()
        self.small_id = small.id
        self.large_id = large.id
        self.urgent_id = urgent.id

    def tearDown(self) -> None:
        """Close isolated database resources."""
        self.db.close()
        self.engine.dispose()

    def test_non_urgent_large_first_and_each_save_precedes_next_generation(self) -> None:
        """Ordering honors urgency and demand while processing strictly one by one."""
        calls: list[tuple[str, int]] = []

        def generate(_db, ambulance_id, month, year):
            self.assertEqual((year, month), (2026, 9))
            calls.append(("generate", ambulance_id))
            return ScheduleGenerationResponse(
                month=month,
                year=year,
                assignment_count=0,
                entries=[],
            )

        def save(_db, ambulance_id, month, year, entries):
            self.assertEqual((year, month), (2026, 9))
            self.assertEqual(entries, [])
            calls.append(("save", ambulance_id))
            return []

        with (
            mock.patch.object(
                automatic,
                "generate_ambulance_monthly_schedule",
                side_effect=generate,
            ),
            mock.patch.object(
                automatic,
                "save_ambulance_monthly_schedule",
                side_effect=save,
            ),
        ):
            result = automatic.run_automatic_generation(self.db, 2026, 9)

        expected_ids = [self.large_id, self.small_id, self.urgent_id]
        self.assertEqual(list(result.ordered_ambulance_ids), expected_ids)
        self.assertEqual(
            calls,
            [
                action
                for ambulance_id in expected_ids
                for action in (("generate", ambulance_id), ("save", ambulance_id))
            ],
        )
        self.assertIsNone(
            automatic.run_automatic_generation(self.db, 2026, 9)
        )

    def test_one_infeasible_ambulance_does_not_stop_following_workplaces(self) -> None:
        """A solver conflict is recorded while later ambulances still run."""
        generated_ids: list[int] = []
        saved_ids: list[int] = []

        def generate(_db, ambulance_id, month, year):
            generated_ids.append(ambulance_id)
            if ambulance_id == self.large_id:
                raise ScheduleGenerationError("No solution", [])
            return ScheduleGenerationResponse(
                month=month,
                year=year,
                assignment_count=0,
                entries=[],
            )

        def save(_db, ambulance_id, _month, _year, _entries):
            saved_ids.append(ambulance_id)
            return []

        with (
            mock.patch.object(
                automatic,
                "generate_ambulance_monthly_schedule",
                side_effect=generate,
            ),
            mock.patch.object(
                automatic,
                "save_ambulance_monthly_schedule",
                side_effect=save,
            ),
        ):
            result = automatic.run_automatic_generation(self.db, 2026, 10)

        self.assertEqual(
            generated_ids,
            [self.large_id, self.small_id, self.urgent_id],
        )
        self.assertEqual(saved_ids, [self.small_id, self.urgent_id])
        self.assertEqual(result.failed_ambulance_ids, (self.large_id,))


if __name__ == "__main__":
    unittest.main()
