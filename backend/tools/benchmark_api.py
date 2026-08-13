"""Concurrent p50/p95/p99 benchmark runner for Scheduling API scenarios.

The runner is read-only by default. Scenario values support ``${ENV_NAME}``
placeholders, so authentication cookies and resource IDs never need to be
stored in the repository.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import os
from pathlib import Path
from string import Template
import threading
from time import perf_counter
from typing import Any
from urllib.parse import urljoin, urlparse

import requests


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_thread_local = threading.local()


def _session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        _thread_local.session = session
    return session


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return Template(value).substitute(os.environ)
    if isinstance(value, list):
        return [_expand(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    return value


def _percentile(sorted_values: list[float], percentile: float) -> float:
    """Return a linearly interpolated percentile for non-empty values."""
    position = (len(sorted_values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return (
        sorted_values[lower] * (1 - fraction)
        + sorted_values[upper] * fraction
    )


def _request_once(
    base_url: str,
    scenario: dict[str, Any],
    timeout: float,
    cookie_name: str | None,
    cookie_value: str | None,
) -> float:
    method = scenario["method"].upper()
    url = urljoin(f"{base_url.rstrip('/')}/", scenario["path"].lstrip("/"))
    cookies = (
        {cookie_name: cookie_value}
        if cookie_name is not None and cookie_value is not None
        else None
    )
    started = perf_counter()
    response = _session().request(
        method,
        url,
        params=scenario.get("params"),
        headers=scenario.get("headers"),
        json=scenario.get("json"),
        cookies=cookies,
        timeout=timeout,
        allow_redirects=False,
    )
    elapsed_ms = (perf_counter() - started) * 1000
    expected_status = int(scenario.get("expected_status", 200))
    if response.status_code != expected_status:
        body = response.text[:300].replace("\n", " ")
        raise RuntimeError(
            f"{scenario['name']} returned {response.status_code}, expected "
            f"{expected_status}: {body}"
        )
    return elapsed_ms


def _benchmark_scenario(
    base_url: str,
    scenario: dict[str, Any],
    warmup: int,
    iterations: int,
    concurrency: int,
    timeout: float,
    cookie_name: str | None,
    cookie_value: str | None,
) -> dict[str, Any]:
    for _ in range(warmup):
        _request_once(base_url, scenario, timeout, cookie_name, cookie_value)

    started = perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                _request_once,
                base_url,
                scenario,
                timeout,
                cookie_name,
                cookie_value,
            )
            for _ in range(iterations)
        ]
        durations = [future.result() for future in as_completed(futures)]
    wall_seconds = perf_counter() - started
    durations.sort()
    return {
        "name": scenario["name"],
        "method": scenario["method"].upper(),
        "path": scenario["path"],
        "requests": len(durations),
        "concurrency": concurrency,
        "p50_ms": round(_percentile(durations, 0.50), 3),
        "p95_ms": round(_percentile(durations, 0.95), 3),
        "p99_ms": round(_percentile(durations, 0.99), 3),
        "max_ms": round(durations[-1], 3),
        "requests_per_second": round(len(durations) / wall_seconds, 2),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--cookie-name", default="scheduling_session")
    parser.add_argument("--cookie-env", default="BENCHMARK_SESSION_COOKIE")
    parser.add_argument("--allow-mutations", action="store_true")
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument(
        "--only",
        help="Comma-separated scenario names to run (defaults to every scenario)",
    )
    parser.add_argument("--json-output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.iterations < 1 or args.warmup < 0 or args.concurrency < 1:
        raise SystemExit("iterations/concurrency must be positive and warmup non-negative")

    parsed_url = urlparse(args.base_url)
    if parsed_url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        if not args.allow_remote:
            raise SystemExit("Remote benchmarks require the explicit --allow-remote flag")

    document = json.loads(args.scenario.read_text(encoding="utf-8"))
    raw_scenarios = document["requests"]
    if args.only:
        requested_names = {
            name.strip() for name in args.only.split(",") if name.strip()
        }
        raw_scenarios = [
            item for item in raw_scenarios if item["name"] in requested_names
        ]
        found_names = {item["name"] for item in raw_scenarios}
        missing_names = requested_names - found_names
        if missing_names:
            raise SystemExit(
                "Unknown scenario names: " + ", ".join(sorted(missing_names))
            )
    scenarios = _expand(raw_scenarios)
    unsafe = [
        item["name"]
        for item in scenarios
        if item["method"].upper() not in SAFE_METHODS
    ]
    if unsafe and not args.allow_mutations:
        raise SystemExit(
            "Mutating scenarios require --allow-mutations: " + ", ".join(unsafe)
        )

    cookie_value = os.getenv(args.cookie_env)
    results = []
    for scenario in scenarios:
        results.append(
            _benchmark_scenario(
                args.base_url,
                scenario,
                args.warmup,
                args.iterations,
                args.concurrency,
                args.timeout,
                args.cookie_name if cookie_value else None,
                cookie_value,
            )
        )

    print("| endpoint | requests | p50 ms | p95 ms | p99 ms | max ms | req/s |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for result in results:
        endpoint = f"{result['method']} {result['name']}"
        print(
            f"| {endpoint} | {result['requests']} | {result['p50_ms']:.3f} | "
            f"{result['p95_ms']:.3f} | {result['p99_ms']:.3f} | "
            f"{result['max_ms']:.3f} | {result['requests_per_second']:.2f} |"
        )

    if args.json_output:
        args.json_output.write_text(
            json.dumps(results, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
