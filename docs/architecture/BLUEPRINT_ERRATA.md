# Blueprint V2.1 — Errata

Empirical corrections to assumptions in
[`KalpaMani_Blueprint_V2_1.pdf`](KalpaMani_Blueprint_V2_1.pdf).

> **The Blueprint PDF is never edited.** It is the authoritative architecture record as
> issued, and its byte integrity is verifiable (SHA-256
> `3adaf59f01616c3b491ee988e2f60c43e863578edca74241c12b6b0b1c1495d2`). Where testing shows a
> Blueprint *assumption* does not hold in practice, the correction is recorded in an ADR and
> indexed here — so the authority chain stays intact and the correction is discoverable next
> to the document it corrects.

## How to read this

The Blueprint states both **decisions** (what the system shall do) and **assumptions** (what
the environment was believed to be). This file records only the second kind, where reality
disagreed.

- A Blueprint **decision** may only be changed by an approved ADR that says so explicitly.
- A Blueprint **assumption** contradicted by evidence is corrected here, with the ADR that
  carries the evidence and the resulting decision.

Anything not listed below stands as written.

---

## Errata

### E-001 — §25: IBKR Read-Only Access is not an order-safety control

| | |
|---|---|
| **Blueprint section** | §25, *IBKR Account Configuration Baseline* |
| **Assumption as written** | Read-Only Access observed as enabled; *"May stay enabled … It only provides a quick read-only mode; full login is still required to trade."* |
| **Discovered** | 2026-08-25, Phase 1 IBKR Paper connectivity (four runs) |
| **Recorded in** | [ADR-0003 — Broker-Side Order Controls Are Not Safety Invariants](../decisions/ADR-0003-broker-side-order-controls-are-not-safety-invariants.md) |
| **Status** | Accepted |

**Finding.** The Blueprint's assessment is accurate for *interactive login*, but it does not
constrain the API session LEAN opens. Two different settings were conflated:

- **Read-Only Access** (IBKR account settings) — a login mode. Does not govern the API session.
- **Read-Only API** (IB Gateway API configuration) — *would* block API order submission, and
  is **unselected by QuantConnect's IBAutomater on every automated start**, along with every
  `[Bypass … for API Orders]` precaution.

This is required for LEAN to operate and is not configurable from the LEAN CLI.

**Correction.** Neither setting may be treated as a KalpaMani safety control. Order safety is
enforced internally and deterministically, provable from this repository alone. Broker UI
precautions are defense-in-depth only and must never be a required safety invariant.

**Consequence for Phase 2.** Once an order path exists, nothing on the IBKR side will stop
it. Our own guards are the only guards.

---

*No further errata recorded. Add new entries in sequence (E-002, …), newest last, each
pointing at the ADR that carries the evidence.*
