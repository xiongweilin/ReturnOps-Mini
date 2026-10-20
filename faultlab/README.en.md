# Fault lab: put "unknown" back on a real network boundary

This directory is not a load-testing tool; it is a set of reproducible failure experiments that make the abstract judgments in `src/` (timeout budgets, unknown outcomes, idempotency, reconciliation, transaction boundaries) produce observable consequences on real processes, real networks, and a real database.

```text
docker compose -f faultlab/docker-compose.faultlab.yml up -d --build   # postgres / payment / toxiproxy / api
uv run python faultlab/scenarios.py                                   # all scenarios
uv run python faultlab/scenarios.py --scenario ack-lost               # one scenario
docker compose -f faultlab/docker-compose.faultlab.yml down -v
```

## Scenarios and what each proves

| Scenario | Injection | Invariant asserted |
|---|---|---|
| `payment-latency` | Toxiproxy adds 2000ms latency to the payment proxy | A refund completes normally when the upstream is slow but still within the 3s client budget |
| `ack-lost` | provider contract `X-Simulate: timeout_after_processing` | When the upstream persisted success but the ACK is withheld, local state stays at `REFUND_UNKNOWN`, reconciliation converges it to `REFUNDED`, and there is only one refund |
| `reset-request` | Toxiproxy `reset_peer` on the request direction | A request that never reached the upstream is treated as a retryable failure; a retry succeeds, and the provider always has exactly one refund record |
| `postgres-latency` | Toxiproxy adds 250ms latency to the database proxy | Transaction boundaries still work when the database is slow, and only one refund intent is created |

Each scenario clears the fault-lab database at the start; otherwise an event left in the outbox by the previous scenario would be claimed first and the assertions would point at a different case (a real trap encountered when this experiment suite was first run).

## Performance contract

```text
thresholds                        meaning
  http_req_failed rate<0.01       error rate
  http_req_duration p(95)<500     normal latency
  http_req_duration p(99)<1000    tail latency
  duplicate_effect count==0       the same Idempotency-Key must not create two cases (more important than latency)
```

The thresholds come from measured baselines on the `faultlab` stack, not guesses: run once, record the numbers, then encode them as a contract.

## How to localize degradation (instead of looking at the diff first)

```text
1) k6: inspect the distribution first: is p99 worse (tail/locks) or is the whole distribution higher (resources/connection pool)?
2) Database side: pg_stat_activity (active sessions and wait events), pg_locks, pg_stat_statements (slowest/most frequent statements)
3) A single SQL statement: EXPLAIN (ANALYZE, BUFFERS) to see whether it degraded to a sequential scan or N+1
4) Process side: py-spy dump for stacks, docker stats for CPU/memory saturation
5) Only after the evidence points at a specific resource or SQL statement, go back and inspect code changes
```

Preset "made worse" variants (for practicing diagnosis, not run in CI): drop a composite index, widen the transaction to include an external HTTP call, set the connection pool to 5, or issue queries in a loop. Each can be distinguished by the evidence chain above.

## Boundaries

- Containers start and stop only when needed; `down -v` deletes volumes too;
- The provider's simulation mode is driven by the `X-Simulate` header (`RETURNOPS_PAYMENT_SIMULATION_MODE`); scenarios set it explicitly and reset it to `normal` at the end;
- This lab is not production validation: it proves that these mechanisms actually work at real boundaries.
