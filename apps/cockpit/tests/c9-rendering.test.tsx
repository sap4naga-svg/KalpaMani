/**
 * What the Ask surface actually SHOWS.
 *
 * The presentational components are rendered with real payloads read through the same
 * boundary a screen uses, so a rule satisfied in the contract and dropped in the presentation
 * is caught here rather than by a reviewer reading a screenshot. The panel's interactive flow
 * is exercised end to end by the browser suite; what is checked here is what it delegates.
 *
 * Nothing here reads `Date.now()`.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AskAnswerView, AskInterpretationView } from "@/components/ask/ask-panel";
import { ClockProvider } from "@/components/shell/clock-provider";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import { ASK_INTENT_BY_CLASS, ASK_REFERRALS, EXAMPLE_SUBJECTS } from "@/lib/ask/catalogue";
import { resolveQuestion } from "@/lib/ask/resolve";
import { fixedClock } from "@/lib/clock";
import { DEFAULT_SCOPE, type ViewScope } from "@/lib/scope";

const ORIGIN = Date.parse("2026-09-08T12:00:00.000Z");
const clock = fixedClock(ORIGIN);
const client = () => new FixtureReadClient({ clock, originMs: ORIGIN });
const demo = (over: Partial<ViewScope> = {}): ViewScope => ({
  ...DEFAULT_SCOPE,
  scenario: "demo",
  ...over,
});

const intentOf = (code: Parameters<typeof ASK_INTENT_BY_CLASS.get>[0]) =>
  ASK_INTENT_BY_CLASS.get(code)!;

async function answerView(
  request: Parameters<FixtureReadClient["ask"]>[1],
  scope: ViewScope = demo(),
  operator = false,
) {
  const envelope = await client().ask(scope, request);
  return render(
    <ClockProvider clock={clock}>
      <AskAnswerView
        envelope={envelope}
        intent={intentOf(request.questionClass)}
        scope={scope}
        operator={operator}
      />
    </ClockProvider>,
  );
}

/* ================================================================ the answer hierarchy */

describe("an answer shows what it answered, before it shows the figure", () => {
  it("renders the question class, the interpreted subject and the environment", async () => {
    await answerView({
      questionClass: "TRADE_OUTCOME",
      subjectKind: "TRADE",
      subjectId: EXAMPLE_SUBJECTS.trade,
    });
    const interpretation = screen.getByTestId("ask-interpretation");
    expect(within(interpretation).getByTestId("ask-question-class")).toHaveTextContent(
      /trade outcome/i,
    );
    expect(within(interpretation).getByTestId("ask-interpreted-subject")).toHaveTextContent(
      EXAMPLE_SUBJECTS.trade,
    );
    expect(
      within(interpretation).getByTestId("ask-interpreted-environment"),
    ).toHaveTextContent("RESEARCH");
    /* Provenance is at component level, because screenshots travel. */
    expect(within(interpretation).getByText(/synthetic/i)).toBeInTheDocument();
  });

  it("renders the interpreted window for a windowed question", async () => {
    await answerView({ questionClass: "PORTFOLIO_RETURN", window: "6M" });
    expect(screen.getByTestId("ask-interpreted-window")).toHaveTextContent(/6m/i);
  });

  it("renders the supporting figures and the recorded codes apart", async () => {
    await answerView({
      questionClass: "TRADE_OUTCOME",
      subjectKind: "TRADE",
      subjectId: EXAMPLE_SUBJECTS.trade,
    });
    expect(screen.getByTestId("ask-supporting")).toBeInTheDocument();
    const notes = screen.getByTestId("ask-notes");
    /* A recorded reason is labelled as recorded, and never as a cause. */
    expect(notes).toHaveTextContent(/recorded reasons, not inferred causes/i);
  });
});

/* ==================================================================== loading and states */

describe("a loading, unavailable or abstained answer is never a figure", () => {
  it("renders a shape with no digits while the read is in flight", () => {
    render(
      <ClockProvider clock={clock}>
        <AskAnswerView
          envelope={undefined}
          intent={intentOf("ATTENTION_SUMMARY")}
          scope={demo()}
          operator={false}
        />
      </ClockProvider>,
    );
    const loading = screen.getByTestId("ask-loading");
    expect(loading).toBeInTheDocument();
    expect(loading.textContent ?? "").not.toMatch(/[0-9]/);
    expect(screen.queryByTestId("ask-answer-value")).not.toBeInTheDocument();
  });

  it("states the producing subsystem's own absence rather than an abstention", async () => {
    await answerView({ questionClass: "OPEN_ALERTS" }, demo({ scenario: "project" }));
    const unavailable = screen.getByTestId("ask-unavailable");
    expect(unavailable).toHaveTextContent(/not implemented/i);
    expect(unavailable).toHaveTextContent(/PRODUCER_NOT_IMPLEMENTED/);
    expect(unavailable).toHaveTextContent(/it is not an abstention/i);
    expect(screen.queryByTestId("ask-answer-value")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ask-abstained")).not.toBeInTheDocument();
  });

  it("states an abstention with its closed reason and no substituted zero", async () => {
    await answerView(
      { questionClass: "RECORDED_CHANGES" },
      demo({ changes: "no-baseline" }),
    );
    const abstained = screen.getByTestId("ask-abstained");
    expect(abstained).toHaveTextContent(/abstained/i);
    expect(abstained).toHaveTextContent(/no zero stands in for it/i);
    expect(screen.queryByTestId("ask-answer-value")).not.toBeInTheDocument();
    /* An abstention still names the records it consulted. */
    expect(
      within(screen.getByTestId("ask-citations")).getAllByTestId("ask-citation").length,
    ).toBeGreaterThan(0);
  });

  it("renders a measured zero as a value rather than as an absence", async () => {
    await answerView({ questionClass: "RECORDED_CHANGES" }, demo({ changes: "none" }));
    expect(screen.getByTestId("ask-answer-value")).toHaveTextContent("0");
    expect(screen.queryByTestId("ask-abstained")).not.toBeInTheDocument();
  });
});

/* ======================================================= citations, subject and access */

describe("supporting record, target navigation and area navigation stay apart", () => {
  it("names each citation and says following one is not retrieval", async () => {
    await answerView({ questionClass: "DATA_QUALITY_CONDITION" });
    const citations = screen.getByTestId("ask-citations");
    expect(within(citations).getAllByTestId("ask-citation").length).toBeGreaterThan(0);
    expect(citations).toHaveTextContent(/does not retrieve the record itself/i);
    expect(citations).toHaveTextContent(/no evidence-retrieval endpoint/i);
  });

  it("offers the subject's own record separately from the citations", async () => {
    await answerView({
      questionClass: "CANDIDATE_PROGRESSION",
      subjectKind: "CANDIDATE",
      subjectId: EXAMPLE_SUBJECTS.candidate,
    });
    const subject = screen.getByTestId("ask-subject-ref");
    const link = within(subject).getByTestId("reference-target-link");
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining(`/signals/candidates/${EXAMPLE_SUBJECTS.candidate}`),
    );
    /* Scope travels into the destination, so a link cannot open under another environment. */
    expect(link.getAttribute("href")).toContain("env=RESEARCH");
    expect(link.getAttribute("href")).toContain("scenario=demo");
  });

  it("states the scanned extent against the declared maximum", async () => {
    await answerView({ questionClass: "ATTENTION_SUMMARY" });
    const footer = screen.getByTestId("ask-provenance-footer");
    expect(footer).toHaveTextContent(/scanned/i);
    expect(footer).toHaveTextContent(/declared maximum/i);
    expect(footer).toHaveTextContent(/100,000|100000/);
  });
});

/* =============================================================== refusals and referrals */

describe("what the panel says when it will not answer", () => {
  const noop = () => {};

  function interpretation(question: string) {
    const resolution = resolveQuestion(question);
    render(
      <ClockProvider clock={clock}>
        <AskInterpretationView
          resolution={resolution}
          scope={demo()}
          onPick={noop}
          onSubject={noop}
          onWindow={noop}
        />
      </ClockProvider>,
    );
    return resolution;
  }

  it("states the boundary for an action-shaped request, and renders no control", () => {
    interpretation("cancel the working protective order");
    const refused = screen.getByTestId("ask-action-refused");
    expect(refused).toHaveTextContent(/cannot place, change or cancel anything/i);
    expect(refused).toHaveTextContent(/nothing has been queued or scheduled/i);
    /* No control is rendered at all — not a disabled one, and not a pending one. */
    expect(within(refused).queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryByTestId("ask-answer")).not.toBeInTheDocument();
  });

  it("refers a governance question to the area that owns it", () => {
    interpretation("what is the run b authorization gate?");
    const referred = screen.getByTestId("ask-referred");
    const link = within(referred).getByTestId("ask-referral-link");
    expect(link.getAttribute("href")).toContain("/governance/qualification");
    expect(screen.queryByTestId("ask-answer")).not.toBeInTheDocument();
  });

  it("names both readings of an ambiguous question rather than choosing", () => {
    const resolution = resolveQuestion("any changed alerts?");
    expect(resolution.kind).toBe("AMBIGUOUS");
    render(
      <ClockProvider clock={clock}>
        <AskInterpretationView
          resolution={resolution}
          scope={demo()}
          onPick={noop}
          onSubject={noop}
          onWindow={noop}
        />
      </ClockProvider>,
    );
    const ambiguous = screen.getByTestId("ask-ambiguous");
    expect(within(ambiguous).getAllByRole("button").length).toBeGreaterThan(1);
  });

  it("asks which period, and offers every declared one", () => {
    interpretation("how did the portfolio perform?");
    const picker = screen.getByTestId("ask-window-picker");
    expect(within(picker).getAllByRole("button")).toHaveLength(5);
    expect(screen.getByTestId("ask-needs-window")).toHaveTextContent(/no default is applied/i);
  });

  it("offers the catalogued questions when a question is unsupported", () => {
    interpretation("tell me a joke about the market");
    expect(screen.getByTestId("ask-unsupported")).toHaveTextContent(
      /does not interpret free-form requests/i,
    );
    const suggestions = screen.getByTestId("ask-suggestions");
    expect(within(suggestions).getAllByRole("button").length).toBeGreaterThan(5);
  });

  it("runs a suggestion rather than presenting it as decoration", () => {
    const onPick = vi.fn();
    render(
      <ClockProvider clock={clock}>
        <AskInterpretationView
          resolution={resolveQuestion("tell me a joke about the market")}
          scope={demo()}
          onPick={onPick}
          onSubject={noop}
          onWindow={noop}
        />
      </ClockProvider>,
    );
    screen.getByTestId("ask-suggestion-ATTENTION_SUMMARY").click();
    expect(onPick).toHaveBeenCalledWith("What needs attention?");
  });

  it("keeps every referral pointed at a real Cockpit area", () => {
    for (const referral of ASK_REFERRALS) {
      expect(referral.area.href.startsWith("/"), referral.code).toBe(true);
      expect(referral.terms.length, referral.code).toBeGreaterThan(0);
    }
  });
});
