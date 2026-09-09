import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AvailabilityBadge } from "@/components/cockpit/availability";
import { MetricText } from "@/components/cockpit/metric-text";
import { ReferenceChip } from "@/components/cockpit/read-model-panel";
import { absent, available } from "@/contracts/factories";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import { MULTI_EXIT_TRADE } from "@/data/fixtures/book";
import { CANDIDATE_RECORDS } from "@/data/fixtures/signals";
import { fixedClock } from "@/lib/clock";
import { DEFAULT_SCOPE } from "@/lib/scope";
import { METRIC_DEFINITION_VERSION } from "@/contracts/values";

/**
 * What the C6 surfaces actually SHOW.
 *
 * These render real payloads through the shared components the pages use, so a rule that is
 * satisfied in the contract and dropped in the presentation is caught here rather than by a
 * reviewer reading a screenshot.
 */

const AS_OF = "2026-09-06T13:00:00.000Z";
const DEMO = { ...DEFAULT_SCOPE, scenario: "demo" as const };
const client = new FixtureReadClient({ clock: fixedClock(AS_OF) });

/* ============================================================ unavailable states */

describe("an unavailable signals figure renders as a state", () => {
  it("renders a refused conversion rate as its state, never as a zero", () => {
    const { container } = render(
      <MetricText
        metric={absent(
          "NOT_APPLICABLE",
          "NOT_DEFINED_FOR_SUBJECT",
          "funnel.conversion_rate",
          "RATIO",
        )}
      />,
    );
    expect(screen.getByText("Not applicable")).toBeInTheDocument();
    expect(/\b0(\.0+)?\b/.test(container.textContent ?? "")).toBe(false);
  });

  it("renders a refused money counterfactual as a policy absence, never as a figure", () => {
    const { container } = render(
      <AvailabilityBadge
        state="NOT_YET_AVAILABLE"
        reason="POLICY_REFERENCE_MISSING"
      />,
    );
    expect(container.textContent).toContain("Not yet available");
    expect(/\d/.test(container.textContent ?? "")).toBe(false);
  });

  it("keeps a partial path-dependent value visible AND qualified", () => {
    render(
      <MetricText
        metric={{
          value: "3.10",
          unit: "PERCENT",
          availability: "PARTIAL",
          reason: "PRICE_PATH_INCOMPLETE",
          as_of: AS_OF,
          metric_id: "miss.counterfactual",
          metric_definition_version: METRIC_DEFINITION_VERSION,
        }}
      />,
    );
    /* The number is shown — a qualification is an answer WITH a caveat, not an absence. */
    expect(screen.getByText("+3.10")).toBeInTheDocument();
  });

  it("states a downstream stage's absence rather than substituting a Brain state", async () => {
    const candidates = await client.candidates(DEMO);
    const blocked = (candidates.payload?.items ?? []).find(
      (item) => item.brain_state === "BLOCKED_DATA",
    );
    expect(blocked).toBeDefined();
    render(
      <AvailabilityBadge
        state={blocked!.downstream_stage.availability}
        reason={blocked!.downstream_stage.reason}
      />,
    );
    /*
     * "Not yet available", and it used to read "Not implemented".
     *
     * The downstream producer IS implemented for this scope — candidates in this book
     * carry recorded stages — so a candidate without one has no such RECORD, which is
     * REFERENT_NOT_FOUND under R6. What the test is about is unchanged: the absence is
     * STATED, and a Brain state is never substituted for it.
     */
    expect(screen.getByText("Not yet available")).toBeInTheDocument();
    expect(screen.queryByText(/BLOCKED_DATA/)).toBeNull();
  });
});

/* ========================================================== references and joins */

describe("references render as what they are", () => {
  it("marks an unresolvable join as specified-but-absent rather than hiding it", async () => {
    /* A candidate the Brain left ready that was never handed downstream: no decision exists. */
    const detail = await client.candidateDetail(DEMO, "demo-candidate-0016");
    render(
      <ReferenceChip
        reference={detail.payload!.downstream_refs.risk_decision}
        label="Risk decision"
      />,
    );
    const chip = screen.getByText("Risk decision").closest("[data-ref-kind]");
    /*
     * THE JOIN IS STILL SHOWN, AND IT IS NO LONGER CALLED AN ABSENT PRODUCER.
     *
     * `risk_decision` resolves by AUTHORIZED_READ alone (R3), and the risk-decision
     * producer is implemented for this scope — so calling this an absent subsystem
     * asserted something false about it (R6). The reference stays VISIBLE, which is
     * what this test exists to check.
     */
    expect(chip?.getAttribute("data-resolution")).toBe("AUTHORIZED_READ");
    expect(chip?.getAttribute("data-ref-kind")).toBe("risk_decision");
    expect(chip?.getAttribute("title")).toContain("authorized_read");
  });

  it("marks a resolvable candidate join as an endpoint a reader can follow", async () => {
    const detail = await client.tradeDetail(DEMO, MULTI_EXIT_TRADE);
    render(<ReferenceChip reference={detail.payload!.candidate_ref} label="Candidate" />);
    const chip = screen.getByText("Candidate").closest("[data-ref-kind]");
    expect(chip?.getAttribute("data-resolution")).toBe("ENDPOINT");
    expect(chip?.getAttribute("data-ref-kind")).toBe("candidate");
  });

  it("carries an order and fill reference for a trade whose execution was recorded", async () => {
    const detail = await client.tradeDetail(DEMO, MULTI_EXIT_TRADE);
    const payload = detail.payload!;
    render(
      <ul>
        {payload.order_refs.items.map((reference) => (
          <li key={reference.ref_id}>
            <ReferenceChip reference={reference} />
          </li>
        ))}
      </ul>,
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(4);
    for (const item of items) {
      expect(within(item).getByText("ENDPOINT")).toBeInTheDocument();
    }
  });
});

/* =================================================== every state renders somewhere */

describe("the eight Brain states are all reachable in the demonstration", () => {
  it("journals at least one candidate in every state", async () => {
    const funnel = await client.candidateFunnel(DEMO);
    for (const entry of funnel.payload?.brain_axis ?? []) {
      expect(entry.count.value, entry.state).toBeGreaterThan(0);
    }
  });

  it("renders every candidate's detail without a contract refusal", async () => {
    for (const record of CANDIDATE_RECORDS) {
      const detail = await client.candidateDetail(DEMO, record.candidateId);
      expect(detail.payload?.candidate_id, record.candidateId).toBe(record.candidateId);
      expect(detail.payload?.brain_state, record.candidateId).toBe(record.state);
    }
  });
});

/* ==================================================== the slippage sign, on screen */

describe("slippage renders with its sign and its unit", () => {
  it("shows an adverse fill as a positive basis-point figure", () => {
    render(
      <MetricText
        metric={available({
          metricId: "slippage",
          unit: "BPS",
          value: "11.96",
          asOf: AS_OF,
        })}
      />,
    );
    expect(screen.getByText("+11.96")).toBeInTheDocument();
    expect(screen.getByText("bps")).toBeInTheDocument();
  });

  it("shows a favourable fill as a negative one", () => {
    render(
      <MetricText
        metric={available({
          metricId: "slippage",
          unit: "BPS",
          value: "-9.57",
          asOf: AS_OF,
        })}
      />,
    );
    expect(screen.getByText("-9.57")).toBeInTheDocument();
  });
});
