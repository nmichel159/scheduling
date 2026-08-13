"""Keep the read-only benchmark manifest aligned with every GET operation."""

import json
import os
from pathlib import Path
import unittest


os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.main import app  # noqa: E402


PLACEHOLDER_TO_PATH_PARAMETER = {
    "${BENCHMARK_AMBULANCE_ID}": "{ambulance_id}",
    "${BENCHMARK_COMPETENCE_ID}": "{competence_id}",
    "${BENCHMARK_CURRENT_USER_ID}": "{user_id}",
    "${BENCHMARK_TARGET_USER_ID}": "{user_id}",
    "${BENCHMARK_UNAVAILABILITY_ID}": "{unavailability_id}",
}


class BenchmarkScenarioCoverageTests(unittest.TestCase):
    """The safe benchmark suite must cover every application GET route once."""

    def test_manifest_covers_every_get_operation(self) -> None:
        manifest_path = (
            Path(__file__).resolve().parents[1]
            / "tools"
            / "endpoint_benchmark.example.json"
        )
        scenarios = json.loads(manifest_path.read_text(encoding="utf-8"))[
            "requests"
        ]

        benchmarked_routes = set()
        for scenario in scenarios:
            self.assertEqual(scenario["method"], "GET")
            route_path = scenario["path"]
            for placeholder, parameter in PLACEHOLDER_TO_PATH_PARAMETER.items():
                route_path = route_path.replace(placeholder, parameter)
            benchmarked_routes.add((scenario["method"], route_path))

        application_get_routes = {
            ("GET", route.path)
            for route in app.routes
            if "GET" in getattr(route, "methods", set())
            and route.path not in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
        }
        application_operations = {
            (method, route.path)
            for route in app.routes
            for method in getattr(route, "methods", set())
            if route.path
            not in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
        }

        self.assertEqual(benchmarked_routes, application_get_routes)
        self.assertEqual(len(benchmarked_routes), 32)
        self.assertEqual(len(application_operations), 66)


if __name__ == "__main__":
    unittest.main()
