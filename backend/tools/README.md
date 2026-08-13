# Endpoint benchmark

`benchmark_api.py` measures p50, p95, p99, maximum latency, and throughput for
the scenarios in `endpoint_benchmark.example.json`. The checked-in manifest
covers every current GET operation and is read-only. A regression test fails if
a GET route is added without a corresponding scenario.

Required environment variables:

- `BENCHMARK_SESSION_COOKIE`: valid session token for a normal API process;
- `BENCHMARK_CURRENT_USER_ID`: ID belonging to that session;
- `BENCHMARK_TARGET_USER_ID`: active employee managed by the session user;
- `BENCHMARK_AMBULANCE_ID`: active ambulance accessible to the session user;
- `BENCHMARK_COMPETENCE_ID`: active competence in that ambulance;
- `BENCHMARK_UNAVAILABILITY_ID`: active record owned by the current user;
- `BENCHMARK_ROLE_ID`, `BENCHMARK_MONTH`, and `BENCHMARK_YEAR`.

Example against localhost:

```powershell
python tools/benchmark_api.py `
  --base-url http://127.0.0.1:8000 `
  --scenario tools/endpoint_benchmark.example.json `
  --iterations 50 --warmup 3 --concurrency 4
```

Remote runs also require `--allow-remote`. Mutation scenarios are rejected
unless `--allow-mutations` is explicitly supplied. Do not enable mutations
against demo, staging, or production data merely to obtain a latency number.

For isolated local measurements, `benchmark_app.py` can override only the
authentication dependency in that benchmark process. It requires
`BENCHMARK_ALLOW_AUTH_OVERRIDE=true` and `BENCHMARK_USER_ID`; it does not alter
tokens or database rows and must never be used as the production application.
