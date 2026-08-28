"""Validate a Sharadar qualification plan offline. **There is no execution mode.**

This command builds a :class:`~kalpamani.data.ingest.sharadar.qualification.QualificationPlan`
from explicitly supplied arguments, validates it, and prints a fixed-schema
summary. That is all it does.

.. code-block:: text

    sockets opened      0        AWS requests        0
    provider requests   0        credentials read    0
    files written       0        environment reads   0

**It has no way to run a plan**, and the absence is structural rather than a
policy: it imports no client, no transport, no object store and no runtime
executor, so there is nothing here to point at a vendor even by accident. The
options a reader might expect -- ``--execute``, ``--live``, ``--api-key``,
``--secret``, ``--bucket``, ``--profile``, ``--endpoint`` -- are refused by name
and by exit code, so mistyping one fails loudly instead of being ignored as an
unknown flag.

**It is not the private qualification harness.** ``scripts/sharadar_private_qualification.py``
is a separate, owner-only tool that remains unauthorized to execute; this command
neither imports nor invokes it, and nothing here reads its output.

Output is a fixed set of lines: counts, dataset identifiers, the compiled
ceilings, and ``PLAN OK`` or ``PLAN REFUSED`` with a closed defect code. **No
subject symbol, no window, no URL, no credential, no bucket and no account
identifier is ever printed**, so the transcript of a run is safe to paste
anywhere.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from kalpamani.data.ingest.sharadar.datasets import DateWindow, ResponseFormat, SharadarDataset
from kalpamani.data.ingest.sharadar.qualification import (
    MAX_PAGES_PER_REQUEST,
    MAX_REQUESTS,
    MAX_RETRY_BUDGET,
    MAX_RUN_BYTES,
    MAX_SUBJECTS,
    DatasetPlan,
    QualificationDefect,
    QualificationLimits,
    QualificationPlan,
    QualificationPlanError,
    QualificationSubject,
    refuse_unsupported_parameters,
)

#: Options this command refuses outright, each with the reason it is refused.
#: Present as *rejected names* rather than simply absent, because an unrecognised
#: flag in ``argparse`` is already an error -- but an error that says "unrecognized
#: arguments" teaches nothing, and someone will try again with a different
#: spelling.
REFUSED_OPTIONS: dict[str, str] = {
    "--execute": "this command has no execution mode; running a plan is a separate authorization",
    "--live": "there is no live mode, and nothing here can construct one",
    "--api-key": "no credential is accepted, read, stored or bound by this command",
    "--secret": "no secret identifier is accepted; there is no secret resolver in this slice",
    "--bucket": "no bucket is bound; storage is injected by a composition root that does not exist",
    "--aws-profile": "no AWS profile is read; this command performs no AWS activity",
    "--account": "no account identifier is accepted or printed",
    "--endpoint": "no endpoint override is accepted; the transport pins one origin by parsing",
    "--token": "the vendor's published test token is not usable here and its use is unauthorized",
}


def _refusal(option: str) -> str:
    return f"REFUSED {option}: {REFUSED_OPTIONS[option]}"


def build_parser() -> argparse.ArgumentParser:
    """The complete option surface. Nothing here reaches a network or a secret."""
    parser = argparse.ArgumentParser(
        prog="sharadar_plan_check",
        description="Validate a Sharadar qualification plan offline. No execution mode exists.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--subject",
        action="append",
        default=[],
        metavar="TICKER",
        help="a qualification subject, supplied explicitly; repeat for more. No default exists.",
    )
    parser.add_argument(
        "--dataset",
        action="append",
        default=[],
        choices=sorted(member.value for member in SharadarDataset),
        help="a Stage-3A dataset to plan; repeat for more.",
    )
    parser.add_argument("--window-start", metavar="YYYY-MM-DD", default=None)
    parser.add_argument("--window-end", metavar="YYYY-MM-DD", default=None)
    parser.add_argument("--page-limit", type=int, default=500)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument(
        "--parameter",
        action="append",
        default=[],
        metavar="NAME",
        help="an extra query parameter to test for refusal. Every one is expected to be refused.",
    )
    return parser


def _window(start: str | None, end: str | None) -> DateWindow | None:
    """An explicit window, or ``None``. Never a default range.

    Half a window is refused rather than completed from the other half: the
    vendor defaults the missing end (`PSR-SHD-121`), so a plan built from one
    supplied date would silently cover a range nobody chose.
    """
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise QualificationPlanError(QualificationDefect.WINDOW_MALFORMED) from None
    return DateWindow(start=date.fromisoformat(start), end=date.fromisoformat(end))


def _emit_ceilings() -> None:
    print(f"ceiling.subjects          {MAX_SUBJECTS}")
    print(f"ceiling.requests          {MAX_REQUESTS}")
    print(f"ceiling.pages_per_request {MAX_PAGES_PER_REQUEST}")
    print(f"ceiling.run_bytes         {MAX_RUN_BYTES}")
    print(f"ceiling.retry_budget      {MAX_RETRY_BUDGET}")


def main(argv: list[str] | None = None) -> int:
    """Validate one plan and report. Returns 0 for a valid plan, 2 for a refusal.

    A refused option exits 2 as well, and says which option and why -- an unknown
    flag that merely failed to parse would leave the reader guessing whether the
    tool has a hidden mode.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    for token in arguments:
        name = token.split("=", 1)[0]
        if name in REFUSED_OPTIONS:
            print(_refusal(name))
            return 2

    parser = build_parser()
    parsed = parser.parse_args(arguments)

    print("mode                      PLAN VALIDATION ONLY")
    print("network.sockets           0")
    print("network.provider_requests 0")
    print("aws.requests              0")
    print("credentials.read          0")
    _emit_ceilings()

    try:
        refuse_unsupported_parameters(tuple(parsed.parameter))
        window = _window(parsed.window_start, parsed.window_end)
        subjects = tuple(QualificationSubject(ticker) for ticker in parsed.subject)
        datasets = tuple(
            DatasetPlan(
                dataset=SharadarDataset(name),
                window=window if SharadarDataset(name) is not SharadarDataset.TICKERS else None,
                page_limit=parsed.page_limit,
                max_pages=parsed.max_pages,
            )
            for name in parsed.dataset
        )
        plan = QualificationPlan(
            subjects=subjects,
            datasets=datasets,
            response_format=ResponseFormat.CSV,
            limits=QualificationLimits(),
        )
    except QualificationPlanError as refusal:
        # The defect is a closed vocabulary member, so this line cannot carry a
        # subject, a window, a URL or a payload.
        print(f"plan.subjects             {len(parsed.subject)}")
        print(f"plan.datasets             {len(parsed.dataset)}")
        print(f"PLAN REFUSED              {refusal.defect.value}")
        return 2
    except ValueError:
        # A malformed date reaches here from `date.fromisoformat`. Its message
        # would echo the caller's string, so it is not printed.
        print("PLAN REFUSED              WINDOW_MALFORMED")
        return 2

    print(f"plan.subjects             {len(plan.subjects)}")
    print(f"plan.datasets             {len(plan.datasets)}")
    for dataset_plan in plan.datasets:
        print(f"plan.dataset              {dataset_plan.dataset.value}")
    print(f"plan.requests             {plan.request_count}")
    print(f"plan.profile              {plan.profile.value}")
    print("PLAN OK")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    sys.exit(main())
