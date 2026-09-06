# Fix 1: bounded Market calls

This note describes the Rebirth V5 cold-start Market-call design. The main
implementation is in `cube/services/s06_refresh.py`; connector composition is
in `cube/services/s05_sources.py`.

## Problem

Rebirth V4.1 could start 20 Market calls concurrently and retry each failed
call four times. With a real service, that allowed one refresh to create a
large burst of requests and up to five attempts per Underlying and leg. Slow
or unavailable network calls could occupy the worker pool long enough for the
host or browser request to time out.

## V5 behavior

The safe production defaults are:

```python
_MARKET_MAX_WORKERS = 1
_MARKET_RETRIES = 0
_MARKET_RETRY_DELAY_SECONDS = 0.5
_CONNECTOR_CALL_TIMEOUT_SECONDS = 15.0
_CONNECTOR_REFRESH_BUDGET_SECONDS = 120.0
_CONNECTOR_MAX_OUTSTANDING_CALLS = 8
```

The refresh therefore makes at most one normal Market request at a time and
does not multiply failures with automatic retries. The limits remain explicit
constructor settings for a site that has measured and approved a different
connection budget.

All callable connector boundaries run through a finite daemon call gate. The
refresh owner waits for at most 15 seconds for one call and at most 120 seconds
across a complete refresh. A timed-out call may finish later, but the gate
never launches another call with the same key while it is still running and
retains at most eight outstanding calls process-wide.

The first operational Market exception or timeout opens one refresh-scoped
circuit. Remaining Underlyings, the other quote leg, and later products are not
requested; correctly shaped missing legs allow the calculation to continue.
Cold Risk/checker availability failures similarly become shaped empty inputs,
and unavailable optional overlays remain empty. `TypeError` and `ValueError`
from returned data still fail fast because they indicate a programming or
schema-contract error. A warm transactional failure retains the last good
committed snapshot.

When only one quote leg exists, continuity is preserved:

- missing Open uses Current;
- missing Current uses Open;
- when both are missing, the quote and P&L remain unavailable.

## FX Delta bulk adapter

`ProductConnectorAdapter` has optional `market_open_bulk` and
`market_status_bulk` hooks. They are accepted only for `fx/delta`. Each hook
receives the complete ordered tuple of requested Underlyings and returns one
DataFrame for that leg, reducing FX Delta to one Open request and one Current
request. If no bulk hook is supplied, the normal bounded per-Underlying path is
used.

The temporary adapter demonstrates the signature:

```python
def get_fx_delta_market_open_bulk(
    source_date,
    underlyings,
    *,
    market_status,
):
    ...
```

The bulk result may contain only requested Underlyings. A schema/type error is
rejected; an operational exception becomes one missing bulk leg.

## Native client deadline

The manager now guarantees a finite wait for the application, but Python
cannot safely terminate an arbitrary connector function blocked inside its own
I/O. The real MRX/network client should also set a finite connect/read deadline
so the abandoned daemon call releases its socket and thread:

```python
MARKET_TIMEOUT_SECONDS = 5


def get_market_data(market_date, underlying, *, market_status):
    return mrx_call(
        market_date,
        underlying,
        market_status=market_status,
        timeout=MARKET_TIMEOUT_SECONDS,
    )
```

Use the real client's timeout unit. The manager deadline protects the refresh;
the client deadline releases the underlying resource.

## Multi-session automatic refresh

The 15-minute timer remains browser-local, but the manager coalesces an
automatic request made within 14 minutes of the previous automatic attempt.
Manual Risk, P&L, settings, and Clear Cache actions are never coalesced.

## Verification

Run:

```powershell
python -m pytest tests/s07_integration.py tests/s20_connectors.py tests/s22_refreshdates.py -q
python -m pytest tests/s12_startup.py tests/s16_refreshshell.py -q
```

These contracts cover hard caller deadlines, total refresh budget, bounded
outstanding calls, circuit breaking, zero-retry defaults, cold fail-soft
behavior, strict schema failures, FX Delta bulk calls, quote-leg continuity,
automatic-request coalescing, and single-writer cold-start behavior.
