"""Synthetic fixtures for the private Sharadar qualification harness.

**Entirely fictitious, and that is a licensing requirement rather than a preference.**
Sharadar Terms s.4 bars redistributing Services Data and s.8 bars disclosing conclusions
drawn from evaluating it; a committed fixture in a PUBLIC repository would breach both.
Every row below was invented for this file. No vendor row is copied, quoted, paraphrased
or reconstructed, and **no example from the vendor's API documentation is reused here**
even where one exists.

The security is ``FAKE`` / permaticker ``999001``, which is not a real US ticker. Prices
are round numbers chosen to make arithmetic checkable by eye, not to resemble a market.

Small, legible and **adversarial**. Each variant makes one guarantee falsifiable:

===========================================  ==============================================
what                                          which guarantee it makes falsifiable
===========================================  ==============================================
a split whose effective date has a price row  the inclusive/exclusive convention is *observed*
``STOCKS_EXCLUSIVE`` / ``STOCKS_INCLUSIVE``   the two conventions are distinguished, not assumed
``STOCKS_IRRECONCILABLE``                     a broken adjusted series reports INCONCLUSIVE
``STOCKS_NO_SPLIT``                           a trivially-agreeing range is not a pass
``TICKERS_RECLASSIFIED``                      differing snapshot rows are still not history
``STOCKS_COHERENT`` + ``ACTIONS_COHERENT``    the dividend denomination and convention are pinned
``ACTIONS_AMBIGUOUS_DIVIDEND``                an ambiguous vocabulary refuses to pick a favourite
``ACTIONS_WITH_SPINOFF``                      a spinoff makes the limb inconclusive, not absent
``STOCKS_UNEXPLAINED_DIVERGENCE``             an unexplained gap is inconclusive, not "no event"
===========================================  ==============================================
"""

from __future__ import annotations

#: The two headers are hoisted so no source line exceeds the project line limit; the
#: fixture text they build is unchanged.
_STOCKS_HEADER = "ticker,date,open,high,low,close,volume,closeadj,closeunadj,lastupdated\n"
_TICKERS_HEADER = (
    "table,permaticker,ticker,name,exchange,isdelisted,sector,industry,siccode,lastupdated\n"
)

# ---------------------------------------------------------------------------
# Corporate actions
# ---------------------------------------------------------------------------

#: One 2-for-1 split effective 2020-06-01, plus a dividend that must be ignored by the
#: split reconciliation. The dividend is present precisely so that a reconciliation which
#: mistakenly folded every action into the factor would fail.
ACTIONS_CSV = """date,action,ticker,name,value,contraticker,contraname
2020-06-01,split,FAKE,Fictitious Inc,2.0,,
2021-03-01,dividend,FAKE,Fictitious Inc,0.5,,
"""

ACTIONS_NO_SPLIT_CSV = """date,action,ticker,name,value,contraticker,contraname
2021-03-01,dividend,FAKE,Fictitious Inc,0.5,,
"""

# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------
#
# The invariant under test: close == closeunadj / (product of split factors that apply
# after the row's date). With one 2-for-1 split on 2020-06-01:
#
#   before the split  -> factor 2.0 under BOTH conventions
#   on   the split    -> factor 1.0 exclusive, 2.0 inclusive   <- the discriminating row
#   after  the split  -> factor 1.0 under BOTH conventions

#: The split-date row reads as UNADJUSTED, so only the exclusive convention reconciles.
STOCKS_EXCLUSIVE_CSV = (
    _STOCKS_HEADER
    + """FAKE,2020-01-02,49.0,51.0,48.0,50.0,1000,45.0,100.0,2024-06-03
FAKE,2020-03-02,54.0,56.0,53.0,55.0,1100,50.0,110.0,2024-06-03
FAKE,2020-06-01,59.0,61.0,58.0,120.0,1200,115.0,120.0,2024-06-03
FAKE,2020-09-01,64.0,66.0,63.0,65.0,1300,62.0,65.0,2024-06-03
FAKE,2021-01-04,69.0,71.0,68.0,70.0,1400,68.0,70.0,2024-06-03
"""
)

#: The split-date row reads as ADJUSTED, so only the inclusive convention reconciles.
STOCKS_INCLUSIVE_CSV = (
    _STOCKS_HEADER
    + """FAKE,2020-01-02,49.0,51.0,48.0,50.0,1000,45.0,100.0,2024-06-03
FAKE,2020-03-02,54.0,56.0,53.0,55.0,1100,50.0,110.0,2024-06-03
FAKE,2020-06-01,59.0,61.0,58.0,60.0,1200,57.0,120.0,2024-06-03
FAKE,2020-09-01,64.0,66.0,63.0,65.0,1300,62.0,65.0,2024-06-03
FAKE,2021-01-04,69.0,71.0,68.0,70.0,1400,68.0,70.0,2024-06-03
"""
)

#: A pre-split row whose adjusted close matches NEITHER convention. This is what a broken
#: or undocumented adjustment method looks like, and it must not be reported as a pass.
STOCKS_IRRECONCILABLE_CSV = (
    _STOCKS_HEADER
    + """FAKE,2020-01-02,49.0,51.0,48.0,37.5,1000,35.0,100.0,2024-06-03
FAKE,2020-03-02,54.0,56.0,53.0,55.0,1100,50.0,110.0,2024-06-03
FAKE,2020-09-01,64.0,66.0,63.0,65.0,1300,62.0,65.0,2024-06-03
"""
)

#: No split in range: adjusted and unadjusted agree trivially, which proves nothing about
#: the adjustment method and must be reported as PARTIALLY_TESTED, never TESTED.
STOCKS_NO_SPLIT_CSV = (
    _STOCKS_HEADER
    + """FAKE,2021-01-04,69.0,71.0,68.0,70.0,1400,68.0,70.0,2024-06-03
FAKE,2021-02-01,71.0,73.0,70.0,72.0,1500,70.0,72.0,2024-06-03
"""
)

#: No lastupdated column at all -- the P1 semantics question then has no input.
STOCKS_NO_LASTUPDATED_CSV = """ticker,date,open,high,low,close,volume,closeadj,closeunadj
FAKE,2021-01-04,69.0,71.0,68.0,70.0,1400,68.0,70.0
"""

# ---------------------------------------------------------------------------
# Tickers and metadata
# ---------------------------------------------------------------------------

#: One current row: the classification carries no history, so CLASSIFICATION_STATIC holds.
TICKERS_CSV = (
    _TICKERS_HEADER
    + """SF1,999001,FAKE,Fictitious Inc,XFAK,N,Invented Sector,Invented Industry,9999,2024-06-03
"""
)

#: Several rows for ONE issuer with IDENTICAL classification -- the shape a per-source-table
#: response takes. Counting rows would call this history; it is not, and the limitation
#: must survive.
TICKERS_MULTI_TABLE_CSV = (
    _TICKERS_HEADER
    + """SF1,999001,FAKE,Fictitious Inc,XFAK,N,Invented Sector,Invented Industry,9999,2024-06-03
SEP,999001,FAKE,Fictitious Inc,XFAK,N,Invented Sector,Invented Industry,9999,2024-06-03
SFP,999001,FAKE,Fictitious Inc,XFAK,N,Invented Sector,Invented Industry,9999,2024-06-03
"""
)

#: A genuine classification change for one issuer. The limitation must be dropped here,
#: otherwise the test could not distinguish a real detection from a constant answer.
TICKERS_RECLASSIFIED_CSV = (
    _TICKERS_HEADER
    + """SF1,999001,FAKE,Fictitious Inc,XFAK,N,Invented Sector,Invented Industry,9999,2024-06-03
SF1,999001,FAKE,Fictitious Inc,XFAK,N,Second Sector,Second Industry,9998,2024-06-03
"""
)

# ---------------------------------------------------------------------------
# Fundamentals and events
# ---------------------------------------------------------------------------

#: No filingdate column, matching the documented schema shape. P7 must stay DEFERRED
#: whether or not one is present, but the fixture keeps the observation meaningful.
FUNDAMENTALS_CSV = """ticker,dimension,calendardate,datekey,reportperiod,lastupdated,revenue
FAKE,ARQ,2020-03-31,2020-05-04,2020-03-31,2024-06-03,1000
FAKE,ARQ,2020-06-30,2020-08-03,2020-06-30,2024-06-03,1100
"""

#: Date only, no time component and no before/after-market indicator.
EVENTS_CSV = """ticker,date,eventcodes
FAKE,2020-05-04,11
FAKE,2020-08-03,11
"""

#: An events payload carrying a time-like column. P8 must STILL be DEFERRED -- the test
#: exists so that a "deferred" answer cannot be an accident of missing input.
EVENTS_WITH_TIME_CSV = """ticker,date,eventtime,eventcodes
FAKE,2020-05-04,16:30:00,11
"""

#: Not CSV at all. A malformed payload must degrade to INCONCLUSIVE, never to a pass.
MALFORMED_PAYLOAD = b"\xff\xfe\x00not a csv payload at all"

# ---------------------------------------------------------------------------
# The cash-dividend limb
# ---------------------------------------------------------------------------
#
# The identity under test: close / closeadj == the product of cash-dividend ratios falling
# after the row's date, where each ratio is (C + D) / C on the close **ON the action date**
# -- the vendor's `current_close` -- with preceding history divided by it.
#
# Three things are deliberately arranged so the fixture DISCRIMINATES rather than merely
# agrees:
#
#   * a price row sits ON the dividend date, so the event is exercisable at all;
#   * the action-date close differs sharply from the previous row's close, so a harness
#     that used the PREVIOUS close as the base would fail visibly rather than by a rounding
#     margin -- that is the regression the correction needs;
#   * the dividend sits BEFORE the split, so the action-date unadjusted close (200.0) and
#     split-adjusted close (100.0) differ, which separates the two share bases.
#
# Arithmetic, all exact:
#   dividend 50.0 on 2020-03-02; the row ON that date has close 100.0, closeunadj 200.0
#     UNADJUSTED_BASIS     ratio 250/200 = 1.25  -> closeadj 200.0/1.25 = 160.0
#     SPLIT_ADJUSTED_BASIS ratio 150/100 = 1.5   -> would give 133.33, far outside
#     PREVIOUS-close (wrong) 450/400 = 1.125     -> would give 177.78, far outside
#   the action-date row keeps its traded price, so close == closeadj there and after

ACTIONS_COHERENT_CSV = """date,action,ticker,name,value,contraticker,contraname
2020-03-02,dividend,FAKE,Fictitious Inc,50.0,,
2020-06-01,split,FAKE,Fictitious Inc,2.0,,
"""

STOCKS_COHERENT_CSV = (
    _STOCKS_HEADER
    + """FAKE,2020-01-02,199.0,201.0,198.0,200.0,1000,160.0,400.0,2024-06-03
FAKE,2020-03-02,99.0,101.0,98.0,100.0,1100,100.0,200.0,2024-06-03
FAKE,2020-04-01,59.0,61.0,58.0,60.0,1200,60.0,120.0,2024-06-03
FAKE,2020-06-01,129.0,131.0,128.0,130.0,1300,130.0,130.0,2024-06-03
FAKE,2020-09-01,64.0,66.0,63.0,65.0,1400,65.0,65.0,2024-06-03
"""
)

#: The action-date close (200.0 unadjusted) and the previous row's close (400.0 unadjusted)
#: differ by a factor of two, so the two candidate bases give ratios 1.25 and 1.125. A
#: harness using the wrong one misses by 10%, far outside tolerance. Named so the regression
#: that pins the correction reads clearly.
DIVIDEND_ACTION_DATE = "2020-03-02"
DIVIDEND_AMOUNT = 50.0
DIVIDEND_ACTION_DATE_CLOSEUNADJ = 200.0
DIVIDEND_PREVIOUS_ROW_CLOSEUNADJ = 400.0

#: Two dividend-like literals. `infer_action_literal` must return None rather than pick a
#: favourite, and the limb must be INCONCLUSIVE rather than silently choose one.
ACTIONS_AMBIGUOUS_DIVIDEND_CSV = """date,action,ticker,name,value,contraticker,contraname
2020-03-02,dividend,FAKE,Fictitious Inc,50.0,,
2020-05-01,specialdividend,FAKE,Fictitious Inc,10.0,,
2020-06-01,split,FAKE,Fictitious Inc,2.0,,
"""

#: A stock dividend alongside a cash dividend. The stock-dividend literal must be excluded
#: so the cash-dividend literal stays unambiguous -- otherwise the exclusion rule is untested.
ACTIONS_STOCK_AND_CASH_DIVIDEND_CSV = """date,action,ticker,name,value,contraticker,contraname
2020-03-02,dividend,FAKE,Fictitious Inc,50.0,,
2020-05-01,stockdividend,FAKE,Fictitious Inc,1.005,,
2020-06-01,split,FAKE,Fictitious Inc,2.0,,
"""

#: A spinoff in range. Its ratio needs the spun-off entity's opening price, which no sample
#: of the parent contains, so the limb must be INCONCLUSIVE and every earlier row dropped.
ACTIONS_WITH_SPINOFF_CSV = """date,action,ticker,name,value,contraticker,contraname
2020-03-02,dividend,FAKE,Fictitious Inc,50.0,,
2020-05-01,spinoff,FAKE,Fictitious Inc,0.25,SPUN,Spun Out Inc
2020-06-01,split,FAKE,Fictitious Inc,2.0,,
"""

#: A series whose fully adjusted close matches no combination of convention and
#: denomination. A broken dividend adjustment must report INCONCLUSIVE, never a pass.
STOCKS_DIVIDEND_IRRECONCILABLE_CSV = (
    _STOCKS_HEADER
    + """FAKE,2020-01-02,199.0,201.0,198.0,200.0,1000,120.0,400.0,2024-06-03
FAKE,2020-03-02,99.0,101.0,98.0,100.0,1100,100.0,200.0,2024-06-03
FAKE,2020-04-01,59.0,61.0,58.0,60.0,1200,60.0,120.0,2024-06-03
FAKE,2020-06-01,129.0,131.0,128.0,130.0,1300,130.0,130.0,2024-06-03
"""
)

#: No cash dividend anywhere. close and closeadj agree trivially, which exercises nothing:
#: the limb must be PARTIALLY_TESTED, never TESTED.
ACTIONS_SPLIT_ONLY_CSV = """date,action,ticker,name,value,contraticker,contraname
2020-06-01,split,FAKE,Fictitious Inc,2.0,,
"""

STOCKS_NO_DIVIDEND_CSV = (
    _STOCKS_HEADER
    + """FAKE,2020-04-01,59.0,61.0,58.0,60.0,1200,60.0,120.0,2024-06-03
FAKE,2020-06-01,129.0,131.0,128.0,130.0,1300,130.0,130.0,2024-06-03
FAKE,2020-09-01,64.0,66.0,63.0,65.0,1400,65.0,65.0,2024-06-03
"""
)

#: close and closeadj diverge with no dividend and no spinoff recorded that could explain
#: it. That is an inconsistency, and it must read as INCONCLUSIVE rather than as absence.
STOCKS_UNEXPLAINED_DIVERGENCE_CSV = (
    _STOCKS_HEADER
    + """FAKE,2020-04-01,59.0,61.0,58.0,60.0,1200,50.0,120.0,2024-06-03
FAKE,2020-06-01,129.0,131.0,128.0,130.0,1300,130.0,130.0,2024-06-03
"""
)

# ---------------------------------------------------------------------------
# Absent evidence, which must never read as evidence of absence
# ---------------------------------------------------------------------------
#
# Each of these makes some extractor return an empty list. Downstream that once read as
# "no split, no dividend, no spinoff", and the split limb reconciled trivially. Every one
# must now leave the limbs NOT_EXERCISED and the finding INCONCLUSIVE.

#: A syntactically valid response carrying only a header row.
ACTIONS_HEADER_ONLY_CSV = "date,action,ticker,name,value,contraticker,contraname\n"

#: Required columns absent. The table cannot answer, and must not be read as answering.
ACTIONS_MISSING_VALUE_COLUMN_CSV = """date,action,ticker,name,contraticker,contraname
2020-06-01,split,FAKE,Fictitious Inc,,
"""

#: Prices with a header and nothing else.
STOCKS_HEADER_ONLY_CSV = _STOCKS_HEADER

#: The unadjusted close is absent, so no row is comparable against the adjusted one.
STOCKS_NO_CLOSEUNADJ_CSV = """ticker,date,open,high,low,close,volume,closeadj,lastupdated
FAKE,2020-04-01,59.0,61.0,58.0,60.0,1200,60.0,2024-06-03
FAKE,2020-06-01,129.0,131.0,128.0,130.0,1300,130.0,2024-06-03
"""

#: The split-adjusted close is absent.
STOCKS_NO_CLOSE_CSV = """ticker,date,open,high,low,volume,closeadj,closeunadj,lastupdated
FAKE,2020-04-01,59.0,61.0,58.0,1200,60.0,120.0,2024-06-03
FAKE,2020-06-01,129.0,131.0,128.0,1300,130.0,130.0,2024-06-03
"""

#: Every close is non-numeric. Parsing succeeds; comparison cannot.
STOCKS_NONNUMERIC_CLOSE_CSV = (
    _STOCKS_HEADER
    + """FAKE,2020-04-01,59.0,61.0,58.0,n/a,1200,n/a,n/a,2024-06-03
FAKE,2020-06-01,129.0,131.0,128.0,n/a,1300,n/a,n/a,2024-06-03
"""
)

# ---------------------------------------------------------------------------
# A split that adjusts nothing in the sample
# ---------------------------------------------------------------------------

#: The split predates every price row, so it adjusts none of them. Counting it as "in
#: range" would let the limb report TESTED while the mechanism was never applied.
ACTIONS_EARLY_SPLIT_CSV = """date,action,ticker,name,value,contraticker,contraname
2015-01-05,split,FAKE,Fictitious Inc,2.0,,
"""

STOCKS_AFTER_EARLY_SPLIT_CSV = (
    _STOCKS_HEADER
    + """FAKE,2020-04-01,59.0,61.0,58.0,60.0,1200,60.0,60.0,2024-06-03
FAKE,2020-06-01,129.0,131.0,128.0,130.0,1300,130.0,130.0,2024-06-03
FAKE,2020-09-01,64.0,66.0,63.0,65.0,1400,65.0,65.0,2024-06-03
"""
)

#: A complete, internally consistent sample: the split limb reconciles under the exclusive
#: convention, and the cash-dividend limb reconciles under the exclusive/unadjusted model.
#: It is the fixture that lets a *favourable* outcome be reached at all -- without one, every
#: conservative assertion elsewhere would pass against a function that always says "no".
COHERENT_SAMPLE: dict[str, str] = {
    "tickers": TICKERS_CSV,
    "stocks": STOCKS_COHERENT_CSV,
    "actions": ACTIONS_COHERENT_CSV,
    "fundamentals": FUNDAMENTALS_CSV,
    "events": EVENTS_CSV,
}
