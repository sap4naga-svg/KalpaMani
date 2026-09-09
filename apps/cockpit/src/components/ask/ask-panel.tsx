"use client";

import * as React from "react";
import Link from "next/link";
import * as Dialog from "@radix-ui/react-dialog";
import { Sparkles, X } from "lucide-react";

import { Badge, Button, Card, CardBody, Label, Separator, Skeleton } from "@/components/ui/primitives";
import { AvailabilityBadge, UnavailableBody } from "@/components/cockpit/availability";
import { MetricText } from "@/components/cockpit/metric-text";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import { FreshnessIndicator } from "@/components/cockpit/freshness";
import { ReferenceDestinations } from "@/components/cockpit/reference-links";
import { useAsk, useSearch } from "@/data/client/hooks";
import { ASK_INTENTS, ASK_INTENT_BY_CLASS, type AskIntent } from "@/lib/ask/catalogue";
import { resolveQuestion, requestFor, type AskRequest, type AskResolution } from "@/lib/ask/resolve";
import { humanizeCode } from "@/lib/format";
import {
  PERFORMANCE_PERIODS,
  PERIOD_LABEL,
  withScope,
  type PerformancePeriod,
  type ViewScope,
} from "@/lib/scope";
import type { EnvelopeOf } from "@/contracts/envelope";
import type { AskAnswerPayload } from "@/contracts/ask-models";
import { cn } from "@/lib/utils";

import { useScope } from "@/components/shell/use-scope";

/**
 * Ask KalpaMani — Area 31, as the GLOBAL SURFACE the accepted UX specification describes.
 *
 * It is a surface present on every route rather than a route of its own, because that is what
 * `ui-ux-specification.md` §4 says it is: "Global surfaces, present on every route: the command
 * palette (area 30), Ask KalpaMani (area 31)". No route is added to the accepted registry.
 *
 * WHAT THIS PANEL IS, AND WHAT IT IS NOT.
 *
 *   it IS      a bounded reader over the read models this application already serves
 *   it is NOT  a running model. Questions are matched against a CLOSED catalogue by
 *              `lib/ask/resolve.ts`; there is no inference, no embedding and no network
 *   it is NOT  a control. There is no execution vocabulary anywhere in it, and an
 *              action-shaped request receives a stated boundary rather than a queued command
 *
 * THE ANSWER ALWAYS SAYS WHAT IT ANSWERED. The question class, the interpreted subject and the
 * interpreted window are rendered above the figure, so a reader can see that the assistant did
 * not silently substitute a different trade, strategy or period for the one they named.
 *
 * A STALE ANSWER IS STRUCTURALLY IMPOSSIBLE rather than something this component remembers to
 * clear: every request parameter and the whole scope join the cache key, so a different
 * question, subject, window, environment or scenario is a DIFFERENT ENTRY and React Query
 * returns nothing for a key it has not seen. A late response for an earlier question lands on
 * that question's key, not on this one's.
 */
export interface AskController {
  readonly isOpen: boolean;
  readonly openerRef: React.RefObject<HTMLElement | null>;
  open: (opener?: HTMLElement | null) => void;
  close: () => void;
  setOpen: (open: boolean) => void;
}

export function useAskPanel(): AskController {
  const [isOpen, setOpen] = React.useState(false);
  const openerRef = React.useRef<HTMLElement | null>(null);
  return React.useMemo(
    () => ({
      isOpen,
      openerRef,
      open: (opener?: HTMLElement | null) => {
        openerRef.current = opener ?? (document.activeElement as HTMLElement | null);
        setOpen(true);
      },
      close: () => setOpen(false),
      setOpen: (next: boolean) => {
        if (next) openerRef.current = document.activeElement as HTMLElement | null;
        setOpen(next);
      },
    }),
    [isOpen],
  );
}

/** What the panel is currently asking about, and the question text that produced it. */
interface AskedQuestion {
  readonly request: AskRequest;
  readonly intent: AskIntent;
  /** The exact text the reader submitted, so an edited draft can be flagged as unasked. */
  readonly askedText: string;
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <Label className="block text-label-s uppercase tracking-[0.09em] text-text-tertiary">
      {children}
    </Label>
  );
}

/** A ready-made question, and it RUNS — nothing here is decorative copy. */
function SuggestionList({
  onPick,
  heading,
}: {
  onPick: (question: string) => void;
  heading: string;
}) {
  return (
    <div className="space-y-2" data-testid="ask-suggestions">
      <SectionLabel>{heading}</SectionLabel>
      <ul className="grid gap-1.5 sm:grid-cols-2">
        {ASK_INTENTS.map((intent) => (
          <li key={intent.questionClass}>
            <button
              type="button"
              data-testid={`ask-suggestion-${intent.questionClass}`}
              onClick={() => onPick(intent.examples[0]!)}
              className={cn(
                "w-full rounded-sm border border-border-subtle bg-surface-sunken px-3 py-2",
                "text-left text-label-m text-text-secondary transition-colors",
                "hover:border-border-strong hover:text-text-primary",
                "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent",
              )}
            >
              <span className="block truncate text-text-primary">{intent.examples[0]}</span>
              <span className="mt-0.5 block text-label-s text-text-tertiary">
                {intent.label}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The subject picker, fed by the SAME index the command palette searches (Area 30).
 *
 * A subject is never defaulted and never guessed: where a question named none, the reader
 * chooses one from the records that actually exist, and the chosen identifier is what the
 * typed request carries.
 */
function SubjectPicker({
  intent,
  scope,
  onChoose,
}: {
  intent: AskIntent;
  scope: ViewScope;
  onChoose: (subjectId: string) => void;
}) {
  const wanted = intent.subjectKind;
  /*
   * THE INDEX IS FILTERED BY THE SUBJECT KIND, THROUGH THE READ BOUNDARY.
   *
   * `/search` delivers ONE PAGE of a canonical ordering, so an unfiltered read would hand
   * back the first twenty-five rows of the whole index -- which, ordered by subject, may
   * contain none of the kind this question is about. The kind is passed as the search term
   * and the rows are checked against it again below: the boundary narrows the population,
   * and the component never treats a row of another kind as a candidate subject.
   */
  const search = useSearch(scope, wanted ?? "");
  const rows = (search.data?.payload?.results ?? []).filter(
    (row) => row.subject.code === wanted,
  );
  if (search.data === undefined) {
    return <Skeleton className="h-9 w-full" data-testid="ask-subject-loading" />;
  }
  if (rows.length === 0) {
    return (
      <p className="text-label-m text-text-tertiary" data-testid="ask-subject-empty">
        No {humanizeCode(String(wanted))} records are indexed under this environment and
        scenario, so there is nothing to ask about here.
      </p>
    );
  }
  return (
    <div className="flex flex-wrap gap-1.5" data-testid="ask-subject-picker">
      {rows.slice(0, 8).map((row) => (
        <button
          key={row.result_id}
          type="button"
          data-testid={`ask-subject-${row.result_id}`}
          onClick={() => onChoose(row.result_id)}
          className={cn(
            "rounded-sm border border-border-subtle bg-surface-sunken px-2.5 py-1.5",
            "font-mono text-label-s text-text-secondary transition-colors",
            "hover:border-border-strong hover:text-text-primary",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent",
          )}
        >
          {row.result_id}
        </button>
      ))}
    </div>
  );
}

function WindowPicker({ onChoose }: { onChoose: (window: PerformancePeriod) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5" data-testid="ask-window-picker">
      {PERFORMANCE_PERIODS.map((period) => (
        <button
          key={period}
          type="button"
          data-testid={`ask-window-${period}`}
          onClick={() => onChoose(period)}
          className={cn(
            "rounded-sm border border-border-subtle bg-surface-sunken px-2.5 py-1.5",
            "text-label-s text-text-secondary transition-colors",
            "hover:border-border-strong hover:text-text-primary",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent",
          )}
        >
          {PERIOD_LABEL[period]}
        </button>
      ))}
    </div>
  );
}

/**
 * What the resolver decided, before any read happens. NOTHING HERE HAS ASKED ANYTHING YET.
 *
 * It takes its scope as a prop rather than reading it from the URL, so the same component a
 * screen renders is the one a test renders — and so a refusal, a referral or an ambiguity can
 * be checked without a router.
 */
export function AskInterpretationView({
  resolution,
  scope,
  onPick,
  onSubject,
  onWindow,
}: {
  resolution: AskResolution;
  scope: ViewScope;
  onPick: (question: string) => void;
  onSubject: (intent: AskIntent, subjectId: string) => void;
  onWindow: (intent: AskIntent, window: PerformancePeriod) => void;
}) {
  switch (resolution.kind) {
    case "ACTION_REFUSED":
      return (
        <Card data-testid="ask-action-refused">
          <CardBody className="space-y-2">
            <Badge tone="warning">Not something Ask can do</Badge>
            <p className="text-label-m leading-relaxed text-text-secondary">
              Ask explains recorded state. It cannot place, change or cancel anything, and
              nothing has been queued or scheduled by this request.
            </p>
            <p className="text-label-s text-text-tertiary">
              This Cockpit has no order, risk, promotion, approval, retry, acknowledgement or
              authorization control anywhere in it.
            </p>
          </CardBody>
        </Card>
      );
    case "REFERRED":
      return (
        <Card data-testid="ask-referred">
          <CardBody className="space-y-2">
            <Badge tone="unavailable">Answered by another area</Badge>
            <p className="text-label-m leading-relaxed text-text-secondary">
              {resolution.referral.because}
            </p>
            <Link
              href={withScope(resolution.referral.area.href, scope)}
              data-testid="ask-referral-link"
              className="inline-block text-label-m text-accent underline underline-offset-2"
            >
              {resolution.referral.area.label} area →
            </Link>
          </CardBody>
        </Card>
      );
    case "AMBIGUOUS":
      return (
        <Card data-testid="ask-ambiguous">
          <CardBody className="space-y-2">
            <Badge tone="warning">More than one reading</Badge>
            <p className="text-label-m leading-relaxed text-text-secondary">
              That question matches {resolution.candidates.length} catalogued questions equally
              well. Choosing for you would answer a question you may not have asked.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {resolution.candidates.map((intent) => (
                <button
                  key={intent.questionClass}
                  type="button"
                  data-testid={`ask-disambiguate-${intent.questionClass}`}
                  onClick={() => onPick(intent.examples[0]!)}
                  className={cn(
                    "rounded-sm border border-border-subtle bg-surface-sunken px-2.5 py-1.5",
                    "text-label-s text-text-secondary hover:border-border-strong",
                    "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent",
                  )}
                >
                  {intent.label}
                </button>
              ))}
            </div>
          </CardBody>
        </Card>
      );
    case "NEEDS_SUBJECT":
      return (
        <Card data-testid="ask-needs-subject">
          <CardBody className="space-y-2">
            <Badge tone="unavailable">Which one?</Badge>
            <p className="text-label-m leading-relaxed text-text-secondary">
              {resolution.reason === "ABSENT"
                ? `“${resolution.intent.label}” is about one record, and none was named.`
                : `More than one identifier was named, so which one “${resolution.intent.label}” is about is not decidable.`}{" "}
              Nothing is chosen for you.
            </p>
            <SubjectPicker
              intent={resolution.intent}
              scope={scope}
              onChoose={(subjectId) => onSubject(resolution.intent, subjectId)}
            />
          </CardBody>
        </Card>
      );
    case "NEEDS_WINDOW":
      return (
        <Card data-testid="ask-needs-window">
          <CardBody className="space-y-2">
            <Badge tone="unavailable">Over which period?</Badge>
            <p className="text-label-m leading-relaxed text-text-secondary">
              A period changes the extent the answer covers, so it is a parameter of the
              question rather than a display preference. No default is applied.
            </p>
            <WindowPicker onChoose={(window) => onWindow(resolution.intent, window)} />
          </CardBody>
        </Card>
      );
    case "UNSUPPORTED":
      return (
        <Card data-testid="ask-unsupported">
          <CardBody className="space-y-2">
            <Badge tone="unavailable">Not in the question catalogue</Badge>
            <p className="text-label-m leading-relaxed text-text-secondary">
              Ask answers a fixed set of questions over the read models this Cockpit serves. It
              does not interpret free-form requests, and it will not approximate an answer it
              cannot ground in a record.
            </p>
            <SuggestionList heading="Questions it does answer" onPick={onPick} />
          </CardBody>
        </Card>
      );
    default:
      return null;
  }
}

/** The read, and nothing else. The presentation is `AskAnswerView`, which takes a payload. */
function AnswerBody({
  asked,
  scope,
  operator,
}: {
  asked: AskedQuestion;
  scope: ViewScope;
  operator: boolean;
}) {
  const answer = useAsk(scope, asked.request);
  return (
    <AskAnswerView
      envelope={answer.data}
      intent={asked.intent}
      scope={scope}
      operator={operator}
    />
  );
}

/**
 * The answer itself. EVERY FIGURE IS THE OWNING READ MODEL'S, UNCHANGED.
 *
 * `envelope` is `undefined` while the read is in flight, which is what renders the loading
 * shape. It takes its envelope and its scope as props, so the component a screen renders is
 * the one a test renders.
 */
export function AskAnswerView({
  envelope,
  intent,
  scope,
  operator,
}: {
  envelope: EnvelopeOf<AskAnswerPayload> | undefined;
  intent: AskIntent;
  scope: ViewScope;
  operator: boolean;
}) {
  if (envelope === undefined) {
    return (
      <div className="space-y-2" data-testid="ask-loading">
        {/* A LOADING PANEL CARRIES NO DIGITS, so a screenshot mid-read is not mistakable. */}
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    );
  }

  const payload = envelope.payload;
  if (payload === undefined) {
    return (
      <div className="space-y-3" data-testid="ask-unavailable">
        <UnavailableBody
          state={envelope.availability}
          reason={envelope.availability_reason}
          dependency={`${intent.sourceArea.label} — producing subsystem`}
        />
        <p className="text-label-m leading-relaxed text-text-secondary">
          The answer carries the same state its evidence does. It is not an abstention: an
          abstention names the records it consulted, and here there were none to consult.
        </p>
        <Link
          href={withScope(intent.sourceArea.href, scope)}
          data-testid="ask-source-area-link"
          className="inline-block text-label-m text-accent underline underline-offset-2"
        >
          {intent.sourceArea.label} area →
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="ask-answer">
      {/* WHAT WAS ANSWERED, above the figure, so a substitution would be visible. */}
      <div className="flex flex-wrap items-center gap-2" data-testid="ask-interpretation">
        <Badge tone="unavailable" data-testid="ask-question-class">
          {humanizeCode(payload.question_class.code)}
        </Badge>
        {payload.interpretation.subject_id !== undefined && (
          <Badge tone="unavailable" data-testid="ask-interpreted-subject">
            {humanizeCode(payload.interpretation.subject_kind?.code ?? "SUBJECT")}:{" "}
            <span className="font-mono">{payload.interpretation.subject_id}</span>
          </Badge>
        )}
        {payload.interpretation.window !== undefined && (
          <Badge tone="unavailable" data-testid="ask-interpreted-window">
            {humanizeCode(payload.interpretation.window.code)}
          </Badge>
        )}
        <Badge tone="unavailable" data-testid="ask-interpreted-environment">
          {envelope.environment}
        </Badge>
        <ProvenanceBadge provenance={envelope.provenance} />
        <AvailabilityBadge
          state={envelope.availability}
          reason={envelope.availability_reason}
        />
      </div>

      <div className="space-y-1">
        <SectionLabel>{humanizeCode(payload.answer_label.code)}</SectionLabel>
        {payload.abstained ? (
          <div className="space-y-1.5" data-testid="ask-abstained">
            <Badge tone="warning">Abstained</Badge>
            <p className="text-label-m leading-relaxed text-text-secondary">
              The record exists and the measurement does not carry a value. No estimate is
              substituted, and no zero stands in for it.
            </p>
            {payload.abstention_reason !== undefined && (
              <p className="font-mono text-label-s text-unavailable">
                {String(payload.abstention_reason.value)} · {payload.answer.availability} ·{" "}
                {payload.answer.reason}
              </p>
            )}
          </div>
        ) : (
          <div className="text-numeric-l" data-testid="ask-answer-value">
            <MetricText metric={payload.answer} operator={operator} />
          </div>
        )}
      </div>

      {payload.supporting.length > 0 && (
        <div className="space-y-1.5" data-testid="ask-supporting">
          <SectionLabel>Supporting figures</SectionLabel>
          <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
            {payload.supporting.map((figure) => (
              <div key={figure.label.code} className="flex flex-col gap-0.5 py-0.5">
                <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                  {humanizeCode(figure.label.code)}
                </dt>
                <dd className="text-numeric-s">
                  <MetricText metric={figure.value} operator={operator} />
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {payload.notes.length > 0 && (
        <div className="space-y-1.5" data-testid="ask-notes">
          <SectionLabel>Recorded on the record</SectionLabel>
          <ul className="flex flex-wrap gap-1.5">
            {payload.notes.map((note, index) => (
              <li key={`${note.code}-${index}`}>
                <Badge tone="unavailable">{humanizeCode(note.code)}</Badge>
              </li>
            ))}
          </ul>
          <p className="text-label-s leading-relaxed text-text-tertiary">
            These are codes the record itself carries. They are recorded reasons, not inferred
            causes — nothing here explains why an outcome occurred.
          </p>
        </div>
      )}

      <Separator />

      <div className="space-y-1.5" data-testid="ask-citations">
        <SectionLabel>
          Citations ({payload.citations.items.length} of{" "}
          <MetricText metric={payload.citations.total} neutral operator={operator} />)
        </SectionLabel>
        <ul className="space-y-1">
          {payload.citations.items.map((reference) => (
            <li
              key={reference.ref_id}
              className="flex flex-wrap items-center gap-2 text-label-s"
              data-testid="ask-citation"
            >
              <span className="font-mono text-text-secondary">{reference.ref_id}</span>
              <Badge tone="unavailable">{humanizeCode(reference.ref_kind)}</Badge>
              <ReferenceDestinations reference={reference} scope={scope} />
            </li>
          ))}
        </ul>
        <p className="text-label-s leading-relaxed text-text-tertiary">
          A citation names the record a figure came from. Following one navigates to the area
          that browses records of that kind — it does not retrieve the record itself, and this
          version has no evidence-retrieval endpoint.
        </p>
      </div>

      {payload.subject_ref !== undefined && (
        <div className="space-y-1.5" data-testid="ask-subject-ref">
          <SectionLabel>The record this answer is about</SectionLabel>
          <div className="flex flex-wrap items-center gap-2 text-label-s">
            <span className="font-mono text-text-secondary">
              {payload.subject_ref.ref_id}
            </span>
            <ReferenceDestinations reference={payload.subject_ref} scope={scope} />
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3" data-testid="ask-provenance-footer">
        <FreshnessIndicator report={envelope.freshness} showDetail={operator} />
        <span className="text-label-s text-text-tertiary">
          Scanned{" "}
          <MetricText metric={payload.scanned_extent} neutral operator={operator} /> of a
          declared maximum{" "}
          <MetricText metric={payload.scanned_extent_maximum} neutral operator={operator} />
        </span>
        <Link
          href={withScope(intent.sourceArea.href, scope)}
          data-testid="ask-source-area-link"
          className="text-label-s text-accent underline underline-offset-2"
        >
          {intent.sourceArea.label} area →
        </Link>
      </div>
    </div>
  );
}

export function AskPanel({ controller }: { controller: AskController }) {
  const { scope } = useScope();
  const [draft, setDraft] = React.useState("");
  const [resolution, setResolution] = React.useState<AskResolution | null>(null);
  const [asked, setAsked] = React.useState<AskedQuestion | null>(null);

  const submit = React.useCallback((question: string) => {
    const resolved = resolveQuestion(question);
    setResolution(resolved);
    if (resolved.kind === "RESOLVED") {
      setAsked({ request: resolved.request, intent: resolved.intent, askedText: question });
      return;
    }
    /*
     * ANYTHING THAT IS NOT A RESOLVED QUESTION CLEARS THE ANSWER.
     *
     * Leaving the previous answer on screen beside a refusal, an ambiguity or a referral
     * would present it as the answer to the new request, which is exactly what it is not.
     */
    setAsked(null);
  }, []);

  const pick = React.useCallback(
    (question: string) => {
      setDraft(question);
      submit(question);
    },
    [submit],
  );

  const withParameter = React.useCallback(
    (intent: AskIntent, parameters: { subjectId?: string; window?: PerformancePeriod }) => {
      const request = requestFor(intent, parameters);
      if (request === null) return;
      setResolution({ kind: "RESOLVED", intent, request });
      setAsked({ request, intent, askedText: draft });
    },
    [draft],
  );

  const edited = asked !== null && draft.trim() !== asked.askedText.trim();

  return (
    <Dialog.Root
      open={controller.isOpen}
      onOpenChange={(open) => controller.setOpen(open)}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/60" />
        <Dialog.Content
          data-testid="ask-panel"
          onCloseAutoFocus={(event) => {
            const opener = controller.openerRef.current;
            if (opener !== null && opener.isConnected) {
              event.preventDefault();
              opener.focus();
            }
          }}
          className={cn(
            "fixed inset-x-0 bottom-0 top-0 z-50 flex flex-col overflow-hidden",
            "border-border-strong bg-surface-overlay shadow-elevation-2",
            "sm:inset-x-auto sm:bottom-auto sm:left-1/2 sm:top-[6vh] sm:h-auto",
            "sm:max-h-[86vh] sm:w-[min(56rem,94vw)] sm:-translate-x-1/2 sm:rounded-md",
            "sm:border",
          )}
        >
          <div className="flex items-start justify-between gap-3 border-b border-border-subtle px-4 py-3">
            <div className="min-w-0">
              <Dialog.Title className="text-numeric-s font-semibold text-text-primary">
                Ask KalpaMani
              </Dialog.Title>
              <Dialog.Description className="mt-0.5 text-label-s leading-relaxed text-text-tertiary">
                A fixed catalogue of questions over the read models this Cockpit serves. Every
                answer carries its evidence, and no answer changes anything.
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <Button variant="ghost" size="sm" aria-label="Close Ask KalpaMani">
                <X size={15} aria-hidden="true" />
              </Button>
            </Dialog.Close>
          </div>

          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
            <form
              data-testid="ask-form"
              onSubmit={(event) => {
                event.preventDefault();
                submit(draft);
              }}
              className="flex flex-wrap gap-2"
            >
              <label htmlFor="ask-question" className="sr-only">
                Ask a question about recorded state
              </label>
              <input
                id="ask-question"
                data-testid="ask-input"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Ask about performance, a trade, a candidate, health or operations…"
                autoComplete="off"
                className={cn(
                  "min-w-0 flex-1 rounded-sm border border-border-subtle bg-surface-sunken",
                  "px-3 py-2 text-label-m text-text-primary outline-none",
                  "placeholder:text-text-tertiary",
                  "focus-visible:border-accent focus-visible:outline focus-visible:outline-2",
                  "focus-visible:outline-accent",
                )}
              />
              <Button type="submit" variant="subtle" size="sm" data-testid="ask-submit">
                Ask
              </Button>
            </form>

            {edited && (
              <p className="text-label-s text-warning" data-testid="ask-edited-hint">
                The answer below is for the question that was asked, not the one being typed.
                Press Ask to answer the new one.
              </p>
            )}

            {resolution !== null && (
              <AskInterpretationView
                resolution={resolution}
                scope={scope}
                onPick={pick}
                onSubject={(intent, subjectId) => withParameter(intent, { subjectId })}
                onWindow={(intent, window) => withParameter(intent, { window })}
              />
            )}

            {asked !== null && (
              <Card>
                <CardBody>
                  <AnswerBody
                    asked={asked}
                    scope={scope}
                    operator={scope.mode === "operator"}
                  />
                </CardBody>
              </Card>
            )}

            {resolution === null && asked === null && (
              <SuggestionList heading="Try one of these" onPick={pick} />
            )}
          </div>

          <div className="border-t border-border-subtle px-4 py-2">
            <p className="text-label-s leading-relaxed text-text-tertiary">
              Ask reads. It places no order, changes no risk, promotes no strategy, runs no
              research and authorizes nothing — this Cockpit has no such control.
            </p>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** The header control that opens the panel. Present on every route, like the palette. */
export function AskLauncher({ controller }: { controller: AskController }) {
  return (
    <Button
      variant="subtle"
      size="sm"
      className="gap-2"
      data-testid="ask-launcher"
      aria-label="Ask KalpaMani"
      onClick={(event) => controller.open(event.currentTarget)}
    >
      <Sparkles size={14} aria-hidden="true" />
      <span className="hidden sm:inline">Ask</span>
    </Button>
  );
}

export { ASK_INTENT_BY_CLASS };
