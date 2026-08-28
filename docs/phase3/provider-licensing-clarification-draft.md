# Phase 3 — Provider Licensing Clarification (CANCELLED — NOT SENT)

> # CANCELLED — NOT SENT — HISTORICAL EVIDENCE ONLY
>
> **This message was never sent, and it will not be sent.** On 2026-08-27 the owner decided to
> accept the published Sharadar Personal Use License as it stands, without vendor correspondence.
> That decision is recorded in
> [ADR-0008](../decisions/ADR-0008-sharadar-personal-use-license-and-private-qualification.md), which closes **G3** for Sharadar personal use.
>
> **The draft is retained, not deleted.** It is the record of what public research could not
> settle, and two of its questions remain live for a different decision:
>
> | | |
> |---|---|
> | **Q1–Q6** — licensing questions | **cancelled**; superseded by the owner's acceptance of the published terms |
> | **Q7** — are the daily bars officially disseminated or provider-aggregated? | **still unanswered.** Not a licensing question. **Must be answered before any purchase** — a provider-aggregated answer makes prices, and the universe built on them, ineligible under `PUBLIC_PIT` |
> | **Q8** — what start date does the Full History tier actually provide, per table? | **still unanswered.** Two vendor statements disagree. **Must be answered before any purchase** |
>
> Nothing below has been sent, and nothing below is authorization to send it. Reviving any part of
> this message is a new owner decision.

## STATUS: **CANCELLED. NOT SENT. NO PROVIDER HAS BEEN CONTACTED.**

**No email has been sent. No support ticket has been opened. No contact form has been
submitted. No vendor account exists. Nothing has been purchased, trialled or credentialed.**

Sending this is an **owner decision** and is not authorized by the task that produced it. It is
drafted so the decision in
[provider-licensing-decision-packet.md](provider-licensing-decision-packet.md) §10 can be taken
on a concrete text rather than an intention.

| | |
|---|---|
| **Addressee (published route)** | `connect@sharadar.com` — the contact address published in the site footer and referenced by the privacy policy's contact section (`PSR-SHD-106`) |
| **Subject of the licence** | Sharadar **Personal Use License**, `https://sharadar.com/terms`, as published **2026-08-27**. The page carries **no version or effective date** (`PSR-SHD-089`), so no revision can be cited — §18 provides for notice of changes on the website, but where such notices appear and whether superseded revisions are retrievable was not established |
| **Governing law / forum** | **Not established.** §15 was fetched and returned liability-cap language rather than a governing-law clause; the privacy policy names no legal entity, address or jurisdiction (`PSR-SHD-106`) |
| **Why written answers** | §18 permits unilateral amendment effective on posting (`PSR-SHD-082`), and the permission this project most needs sits in an undated FAQ rather than the licence (`PSR-SHD-107`) |
| **Gate** | G3 — precedes G1's purchase (authorization A2 before A3) |

---

## Drafting rules applied

1. **Only unresolved material points.** Eight questions in total — **Q1–Q8**. Q1–Q6 are
   licensing questions, each traced to a specific licence section read on 2026-08-27; Q7 and Q8
   are data and product questions carried in the same message because they gate the same
   decision. Anything the public record already settles is not asked.
2. **Yes/no answerable.** Each question is phrased so a one-word answer is meaningful, with the
   context needed to make that answer safe to give.
3. **No account identifiers, no credentials, no personal financial details.** No account exists
   to identify. No dollar amount, broker, position or holding is disclosed.
4. **Accurate about what KalpaMani is.** A single individual, own capital, no clients, no
   external money, automated, and a public source-code repository containing **no vendor data**.
   Misdescribing it to obtain a favourable answer would make the answer worthless.
5. **No negotiating position, no pressure, no deadline.** These are questions, not demands.

---

## What must be verified before sending

Not optional. Every quotation below is **model-mediated** — the fetch tool summarised the Terms
rather than reproducing them verbatim (`PSR-SHD-081`…`PSR-SHD-089`).

- [ ] Open `https://sharadar.com/terms` and confirm each quoted string **verbatim**, including
      section numbers
- [ ] Confirm the Terms have not changed since 2026-08-27 (§18 permits unilateral amendment on
      posting, with notice to the website; no version date is published, so a re-read is the
      only available check)
- [ ] Confirm `connect@sharadar.com` is still the published contact route
- [ ] Confirm the sender description below is accurate on the day it is sent — in particular
      that no entity, client or external money is involved
- [ ] Decide what reply address to use (this correspondence is the owner's, not the
      repository's)

---

## Draft message

> Everything from here to the end marker is the proposed text. **It has not been sent.**

---

**Subject:** Personal Use License — scope questions before subscribing (retention, automated
use, publication)

Hello,

I am evaluating a Sharadar Direct subscription and would like to confirm a few points of the
Personal Use License before subscribing, rather than after. I have read the Terms at
sharadar.com/terms and the FAQ; the questions below are the ones I could not answer from either.

**About my intended use, so the answers are given against the right facts:**

- I am a single individual. There is no company, partnership, trust, fund or other entity, and
  no employer is involved.
- I would use the data for my own research and backtesting, and to run an automated trading
  system that trades **only my own capital**. I have no clients, manage no money for anyone
  else, and am not compensated for analysis.
- The system would retrieve data programmatically — an initial historical backfill, then a
  scheduled incremental refresh using the `lastupdated` filter.
- I maintain a **public source-code repository** for the software. It contains code, schemas,
  documentation and **synthetic test data that I generate myself**. It contains **no Sharadar
  data of any kind**, and I intend to keep it that way.

**My questions:**

**1. Personal use and own-capital automated trading.**
Your FAQ states that Personal Use covers *"research, backtesting, and automated trading of
their own account with no external clients or money managed for others"*. Section 2 of the
Terms does not repeat this, and separately prohibits use *"for yourself as a professional"*.

Can you confirm that an individual running an automated system that trades **only their own
capital**, with no clients and no money managed for others, is within the Personal Use License —
and that the FAQ statement is a binding interpretation of it? **Yes or no.**

**2. Automated and programmatic retrieval.**
The Terms do not mention automated access, and your API documentation refers to *"you or your
application"* providing an API key.

Is automated programmatic retrieval — an initial historical backfill followed by scheduled
incremental syncs from a single subscriber's own key — within the Personal Use License?
**Yes or no.**

**3. Rate limits and fair use.**
I could not find any published rate limit, request quota or fair-use guidance for the API or
bulk downloads.

Are there limits or expectations I should design to, particularly for an initial full-history
backfill? If there is a courtesy pacing you would prefer, I would rather build to it than
discover it.

**4. Retention after cancellation — Section 10.**
Section 10 requires deletion, within thirty days of termination, of *"all copies of the Services
Data (including downloads, bulk files, caches, and extracts), all data sets that contain,
substantially copy, or could reproduce the Services Data or Sharadar tables"*, while permitting
retention of *"research outputs, backtest results, models, summary statistics, trade logs, and
similar derived works that do not contain and cannot reproduce the Services Data or Sharadar
tables"*.

I would keep a local normalised copy while subscribed, and would delete it on cancellation —
that part is clear. What I cannot determine is where the line falls for derived research
artifacts. Specifically:

- **(a)** May I retain **research artifacts derived from the data** — for example computed
  factor values or feature panels, indexed by security and date — after cancellation, given
  that they are computed values rather than your rows, but are keyed similarly to them?
  **Yes or no.**
- **(b)** May I retain **backtest results, performance statistics and trade logs** that contain
  no Sharadar values? **Yes or no.**
- **(c)** Does "cannot reproduce the Services Data" turn on whether your original values are
  **practically recoverable** from the artifact, or on something else? A one-sentence statement
  of the test you apply would settle this.

This matters more than it may appear. My records of what was run — the run identifiers, the
provenance, the retained outputs — would survive cancellation either way, and a rerun that
cannot find its inputs is designed to stop and say so rather than quietly substitute anything.
What I am trying to establish is how much can be **regenerated from source** afterwards. If the
answer is "nothing once the data is deleted", that is workable; I would simply rather know it
going in and design honestly around it than assume otherwise.

**5. Publication and disclosure of data-quality findings — Section 8.**
Section 8 provides that conclusions about the *"value, usability or fitness for purpose"* of the
Services or the Services Data *"shall not be published in any way...or provided or otherwise
disclosed to any outside individual or entity, without prior written approval of Sharadar."*

Before relying on the data I would run validation checks — for example, recomputing
split-adjusted prices from raw prices and corporate actions and reconciling them against your
adjusted series, and sampling delisted securities to confirm history is present. My software
project is developed in the open and reviewed by others.

- **(a)** Would you grant **written approval** to publish factual validation findings of that
  kind — a coverage or reconciliation summary, with attribution and without reproducing your
  data? **Yes or no.** If yes, what form should the request take?
- **(b)** If not, does Section 8 also prevent me **showing such findings privately** to someone
  reviewing my code? I ask because "disclosed to any outside individual" appears to reach a
  private reviewer, and I would rather keep such findings entirely internal than breach the
  clause inadvertently.

**6. Use with third-party AI or LLM services.**
The Terms do not mention artificial intelligence, machine learning or large language models.

My system would use an AI component for qualitative work only — reading public SEC filings and
news. **My intention is that no Sharadar data is ever sent to a third-party AI service**, and I
would like to confirm that is the correct reading. Would submitting Services Data to a
third-party AI or LLM service for analysis fall outside the Personal Use License? **Yes or no.**

**7. A question about the data rather than the licence — daily bar construction.**
For point-in-time research it matters whether a daily bar is an officially disseminated
consolidated-tape figure, an official closing price, or a bar your systems aggregate from your
own trade collection. I could not find this stated in the documentation.

How are the daily bars in the stock prices dataset constructed? A one-line answer is plenty.

**8. Full History depth.**
The subscribe page offers 5 Years, 10 Years and Full History tiers but does not state what Full
History covers. Your documentation says January 1998 for prices and fundamentals and January
2004 for events, while your launch post says "since 1999".

What start date does the Full History tier actually provide, per table? My use depends on
having more than ten years of history including delisted securities, so this determines which
tier I would need.

Thank you — I appreciate that several of these are unusual questions. I would rather establish
the position in writing before subscribing than assume it afterwards.

Best regards,

---

> **END OF DRAFT MESSAGE.** Everything below is repository governance, not part of the message.

---

## Traceability

| Q | Licence section | Register claim | Packet section | Blocks |
|---|---|---|---|---|
| 1 | §2, §3, §5, §18 + FAQ | `PSR-SHD-047`, `049`, `050`, `081`, `082`, `107` | §3.A, §3.H | **A3 purchase** |
| 2 | silence + API docs | `PSR-SHD-088`, `102`, `107` | §3.B | Bronze ingestion design |
| 3 | not documented | `PSR-SHD-102`, `105` | §3.B | Backfill pacing |
| 4 | §10 | `PSR-SHD-083`, `084`, `085` | §3.C, §3.D | **Post-termination rerunability** |
| 5 | §8 | `PSR-SHD-086` | §3.E | How P1–P9 evidence is reviewed |
| 6 | silence; §4 and §8 apply | `PSR-SHD-086`, `087`, `088` | §3.F | AI-layer data boundary |
| 7 | not a licence question | `PSR-SHD-098` | §5.1, §6.1 (**P9**) | `PUBLIC_PIT` eligibility of prices **and the universe** |
| 8 | not a licence question | `PSR-SHD-090`, `091`, `099`, `100`, `101`, `104` | §7.1 | Which tier, if any, is purchasable |

Questions 7 and 8 are data and product questions carried in the same message because they gate
the same decision and cost nothing extra to ask.

## Deliberately not asked

| Not asked | Why |
|---|---|
| Professional / commercial licence pricing | Not needed until KalpaMani is an entity or trades real money. Asking now invites classification as a professional prospect before the personal-use question in Q1 is answered. Note it is unobtainable publicly on **both** channels (`PSR-SHD-071`, `PSR-MISC-023`) |
| Discounts, trials, or evaluation access | Nothing is authorized to be accepted, and asking implies intent to buy |
| Governing law and jurisdiction | Genuinely unestablished (`PSR-SHD-106`), but a contract question for the day a purchase is contemplated, not a scope question now |
| Anything about restatement chronology, announcement dates or `lastupdated` semantics | Already answered by the vendor's own documentation (`PSR-SHD-093`, `094`, `101`). Asking a vendor what its published documentation already says wastes the one exchange available |
| Anything requiring an account, key or data access | Outside authorization, and outside the purpose of the message |

## After a reply arrives

1. Record each answer as a new **claim id** in
   [provider-source-register.md](provider-source-register.md) — source type `OFFICIAL`, with the
   date received. A written vendor answer is the strongest evidence in the register.
2. Revise [provider-licensing-decision-packet.md](provider-licensing-decision-packet.md) §3 and
   §4, re-classifying each affected row.
3. Re-evaluate the recommendation. **A reply does not close G3.** Closing it requires the
   owner's decision on the §10 retention consequence and a recorded decision or ADR, per
   CLAUDE.md §8.
4. **Do not commit the reply verbatim if it contains anything account-specific or
   non-public.** Record the substance and its date; keep any correspondence artifact under
   `.runtime/`.

## Non-authorizations

Producing this draft does not authorize sending it, contacting any provider by any channel,
purchasing, trialling, creating an account, entering billing information, generating or storing
an API key, fetching vendor data, or closing any gate.

**G1 OPEN · G2 OPEN · G3 CLOSED (Sharadar personal use, ADR-0008) · G4 OPEN · G5 OPEN · G6 OPEN · G7 OPEN.**
**ADR-0005 remains PROPOSED. Live trading remains HARD-DISABLED.**
