# Phase 3A — A1 point-in-time foundation kernel

## STATUS: **IN PROGRESS — NOT ACCEPTED, NOT COMPLETE**

| | |
|---|---|
| **Phase 3A A1 foundation implementation** | **IN PROGRESS** |
| **Phase 3 overall** | **NOT COMPLETE** |
| [ADR-0005](../decisions/ADR-0005-point-in-time-data-architecture.md) | **PROPOSED** |
| Provider purchase / trial / credentials | **NOT AUTHORIZED** |
| External data acquisition | **NOT STARTED** |
| Short research | **NOT AUTHORIZED** |
| Phase 3B / 3C / 3D | **NOT AUTHORIZED** |

This document records what the A1 slice is authorized to build, and — more usefully — what it
is not. It is written before the code so that the boundary is a commitment rather than a
description of whatever got written.

---

## 1. What A1 is

A **vendor-neutral kernel**. It implements the merged Phase-3 planning contract
([pit-data-contract.md](pit-data-contract.md), [conceptual-schema.md](conceptual-schema.md),
[data-quality-plan.md](data-quality-plan.md),
[reproducibility-and-provenance.md](reproducibility-and-provenance.md)) as executable,
type-checked Python, and proves it against **deterministic synthetic fixtures owned by this
repository**.

It is a proof that the contract can be *mechanised* — not a proof that any vendor satisfies it,
and not a claim about any real security, price or corporate action.

## 2. Authorized scope

- vendor-neutral contracts: closed vocabularies, the two mutually exclusive envelopes,
  resolved-time and fact-anchor functions, the Phase-3A entity subset
- local content-addressed Bronze storage, and local Silver/Gold storage abstractions
- point-in-time resolution and historical query interfaces
- deterministic quality checks returning typed findings
- reproducibility manifests with deterministic `run_id`
- the adjustment proof and the historical-universe proof
- synthetic security-master, calendar, price, action and universe fixtures
- tests, static architecture guards, and this documentation
- one feature branch and one open, unmerged pull request

## 3. Explicitly NOT authorized, and not done

> any paid or free vendor trial · vendor account creation · provider purchase or subscription ·
> requesting, entering or storing a provider credential · calling a real vendor API ·
> downloading external market data · importing real vendor payloads · scraping provider sites ·
> SEC / EDGAR ingestion · QuantConnect dataset download · IBKR market-data or borrow-data
> qualification · connecting to IBKR · deploying LEAN · submitting or cancelling an order ·
> strategy, scanner, ranking, portfolio or risk implementation · analyst estimates or revisions ·
> historical borrow implementation · short backtests · Phase 3B, 3C or 3D · accepting ADR-0005 ·
> resolving G1–G5 · merging the implementation pull request

**No synthetic result in this slice is vendor qualification or production evidence.** The
provider tests P1–P9 in [implementation-plan.md](implementation-plan.md) §2 remain unrun, and
they cannot be run without a provider that has not been selected.

## 4. Open decision gates — unchanged by this slice

| Gate | Subject | Status |
|---|---|---|
| G1 | Provider selection | **OPEN** |
| G2 | Production information-set profile | **OPEN** |
| G3 | Vendor licensing | **OPEN** |
| G4 | The analyst-estimate gap | **OPEN** |
| G5 | Borrow-history qualification | **OPEN** |

None of the five is resolved here, and none may be resolved silently by an implementation
choice. Where the kernel needs a value a gate would settle — which profile governs production
research, for instance — it takes it as a **required argument with no default**, so the gate
stays visible instead of being answered by whichever call site ran first.

## 5. Security posture

The repository is **PUBLIC** (CLAUDE.md §3) and [INC-0002](../incidents/INC-0002-account-binding-digest-exposure.md)
remains **OPEN**. Accordingly:

- every fixture in this slice is **fictitious** — invented tickers, invented identifiers,
  invented prices. No vendor row is copied, quoted or paraphrased.
- no credential, account identifier, account-binding digest or broker order id appears anywhere
  in the data platform. Cross-cutting invariants 9 and 10 of
  [conceptual-schema.md](conceptual-schema.md) §19 are enforced by test.
- runtime data paths stay under `.runtime/data/`, which `.gitignore` now excludes explicitly
  rather than by inheritance, together with DuckDB and generated Parquet/JSONL artifacts.
- importing the package creates no directory and performs no I/O.

Implementation detail — scope, dependencies, storage layout, the checks actually implemented
and the acceptance limitations — is recorded in this document as the slice is built.
