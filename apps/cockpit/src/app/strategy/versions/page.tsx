"use client";

import * as React from "react";

import { Badge, Button, Card, CardBody, CardHeader, Label, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { FilterBar, SelectField } from "@/components/cockpit/filters";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel } from "@/components/cockpit/read-model-panel";
import {
  ReadOnlyNotice,
  ReferenceListPanel,
  ReferenceRow,
} from "@/components/cockpit/research";
import { usePageFilters } from "@/components/shell/use-page-filters";
import { useScope } from "@/components/shell/use-scope";
import type { StrategyVersionRecord } from "@/contracts/strategy-models";
import type { MetricValue, VersionPins } from "@/contracts/values";
import { useStrategyVersions } from "@/data/client/hooks";
import { isValueBearing } from "@/contracts/validity";
import { humanizeCode } from "@/lib/format";

/**
 * Strategy Version Registry — Area 20.
 *
 * "Make every production and candidate version findable with its complete lineage."
 *
 *   PRODUCTION VERSIONS RENDER IMMUTABLE     and a modification creates a NEW Challenger
 *                                            version rather than an edit in place
 *   OPEN-POSITION PINNING IS EXPLICIT        every open position lists the exact versions
 *                                            that opened it, so a reader can see which
 *                                            positions a retirement does and does not affect
 *   A CHALLENGER DOES NOT REPLACE A CHAMPION the role is a recorded property, the Champion
 *                                            row is unchanged, and a Challenger governs no
 *                                            open position because it produces no order
 *   NO ROLLBACK, ACTIVATION OR PROMOTION     no such control exists here, and the registry
 *                                            records no rollback at all — stated, rather than
 *                                            invented so a conditional field would render
 */

const ROLE_TONE: Readonly<Record<string, React.ComponentProps<typeof Badge>["tone"]>> = {
  CHAMPION: "positive",
  CHALLENGER: "info",
  SUPERSEDED_VERSION: "unavailable",
};

const PIN_LABELS: readonly (readonly [keyof VersionPins, string])[] = [
  ["strategy_version", "Strategy version"],
  ["factor_definition_version", "Factor definitions"],
  ["risk_policy_version", "Risk policy"],
  ["entry_policy_version", "Entry policy"],
  ["exit_policy_version", "Exit policy"],
  ["model_version", "AI model"],
  ["prompt_version", "AI prompt"],
  ["code_identity", "Code identity"],
  ["config_identity", "Configuration identity"],
];

function PinValue({ pin }: { pin: string | MetricValue }) {
  if (typeof pin === "string") {
    return <span className="font-mono text-label-m text-text-secondary">{pin}</span>;
  }
  return <MetricText metric={pin} neutral />;
}

function PinTable({ pins, testId }: { pins: VersionPins; testId?: string }) {
  return (
    <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" data-testid={testId}>
      {PIN_LABELS.map(([key, label]) => (
        <div key={key} className="flex flex-col gap-0.5">
          <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            {label}
          </dt>
          <dd data-pin={key}>
            <PinValue pin={pins[key]} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

const FILTER_KEYS = ["module", "role"] as const;

export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const versions = useStrategyVersions(scope);
  const { filters, setFilter, clearFilter, clearAll } = usePageFilters(FILTER_KEYS);
  const [selected, setSelected] = React.useState<string | null>(null);

  const payload = versions.data?.payload;
  const items = React.useMemo(() => payload?.items ?? [], [payload]);
  const visible = items.filter(
    (entry) =>
      (filters.module === "" || entry.module.code === filters.module) &&
      (filters.role === "" || entry.role.code === filters.role),
  );
  const chosen = visible.find((entry) => entry.strategy_version === selected) ?? visible[0];
  const modules = [...new Set(items.map((entry) => entry.module.code))].sort();
  const roles = [...new Set(items.map((entry) => entry.role.code))].sort();
  const rollbacks = items.filter((entry) => entry.rollback_of !== undefined);

  return (
    <>
      <PageHeader
        title="Strategy Version Registry"
        summary="Every exact strategy version with its lineage, its recorded pins, the registrations it was evaluated under and the open positions it still governs."
        pageState={payload === undefined ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 20</Badge>
          <Badge tone="unavailable">Strategy runtime: NOT IMPLEMENTED</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <ReadOnlyNotice
          subject="the recorded version registry"
          actions={["activate", "promote", "retire", "roll back", "replace"]}
        />

        <ReadModelPanel
          title="Versions"
          description="A Challenger sits beside the Champion it was derived from and never in place of it. Nothing here promotes, activates or replaces a version."
          envelope={versions.data}
          dependency="the strategy runtime — no strategy module exists and none has ever run"
          operator={operator}
          testId="version-table"
          always={
            <FilterBar
              chips={[
                ...(filters.module === ""
                  ? []
                  : [{ key: "module", label: "Module", value: filters.module }]),
                ...(filters.role === ""
                  ? []
                  : [{ key: "role", label: "Role", value: filters.role }]),
              ]}
              onRemove={(key) => clearFilter(key as (typeof FILTER_KEYS)[number])}
              onClearAll={clearAll}
              basis="A registry filter narrows what is displayed. It changes no version, no role and no lifecycle stage."
            >
              <SelectField
                id="version-module"
                label="Module"
                value={filters.module}
                options={modules.map((code) => ({ value: code, label: humanizeCode(code) }))}
                onChange={(next) => setFilter("module", next)}
              />
              <SelectField
                id="version-role"
                label="Role"
                value={filters.role}
                options={roles.map((code) => ({ value: code, label: humanizeCode(code) }))}
                onChange={(next) => setFilter("role", next)}
              />
            </FilterBar>
          }
        >
          {() => (
            <ScrollRegion label="Strategy versions">
              <table
                className="w-full min-w-[54rem] border-collapse text-label-m"
                data-testid="version-rows"
              >
                <caption className="sr-only">
                  Every recorded strategy version with its module, role, lifecycle stage,
                  maturity stage, immutability and the number of open positions it governs.
                </caption>
                <thead className="bg-surface-sunken">
                  <tr className="border-b border-border-subtle text-left text-text-tertiary">
                    <th scope="col" className="px-3 py-2 font-medium">
                      Version
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Role
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Lifecycle stage
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Maturity stage
                    </th>
                    <th scope="col" className="hidden px-3 py-2 font-medium lg:table-cell">
                      Immutable
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Open positions pinned
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Detail
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visible.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-3 py-6 text-text-tertiary">
                        No version matches this filter. Every recorded version is still in the
                        registry.
                      </td>
                    </tr>
                  )}
                  {visible.map((entry) => (
                    <tr
                      key={entry.strategy_version}
                      className="border-b border-border-subtle last:border-0"
                      data-version={entry.strategy_version}
                      data-role={entry.role.code}
                    >
                      <th
                        scope="row"
                        className="px-3 py-1.5 text-left font-normal text-text-secondary"
                      >
                        <span className="flex flex-col">
                          <span>{humanizeCode(entry.module.code)}</span>
                          <span className="font-mono text-label-s text-text-tertiary">
                            {entry.strategy_version}
                          </span>
                        </span>
                      </th>
                      <td className="px-3 py-1.5">
                        <Badge tone={ROLE_TONE[entry.role.code] ?? "neutral"}>
                          {humanizeCode(entry.role.code)}
                        </Badge>
                      </td>
                      <td className="px-3 py-1.5 text-text-secondary">
                        {humanizeCode(entry.lifecycle_stage.code)}
                      </td>
                      <td className="px-3 py-1.5">
                        <Badge tone="neutral" data-maturity-stage={entry.maturity_stage}>
                          {humanizeCode(entry.maturity_stage)}
                        </Badge>
                        {entry.maturity_stage === "SHADOW" && (
                          <span className="ml-2 text-label-s text-text-tertiary">
                            no order authority
                          </span>
                        )}
                      </td>
                      <td className="hidden px-3 py-1.5 text-text-secondary lg:table-cell">
                        {entry.immutable ? "Yes" : "No"}
                      </td>
                      <td className="px-3 py-1.5">
                        <MetricText metric={entry.open_position_count} neutral />
                      </td>
                      <td className="px-3 py-1.5">
                        <Button
                          size="sm"
                          variant={
                            entry.strategy_version === chosen?.strategy_version
                              ? "primary"
                              : "subtle"
                          }
                          aria-pressed={entry.strategy_version === chosen?.strategy_version}
                          onClick={() => setSelected(entry.strategy_version)}
                        >
                          Lineage
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollRegion>
          )}
        </ReadModelPanel>

        <Card data-testid="rollback-statement">
          <CardBody className="space-y-2 pt-4">
            <Label>Recorded rollbacks</Label>
            {rollbacks.length === 0 ? (
              <div className="flex flex-wrap items-center gap-2">
                <AvailabilityBadge state="EMPTY_VERIFIED" reason="EMPTY_RESULT_VERIFIED" />
                <span className="max-w-3xl text-label-m text-text-tertiary">
                  <strong className="text-text-secondary">
                    No rollback is recorded anywhere in this registry.
                  </strong>{" "}
                  A rollback is a governed event with its own decision, and none has occurred.
                  The field exists and is absent, rather than being filled so that a
                  conditional renders — and <strong>no rollback control exists here</strong>.
                </span>
              </div>
            ) : (
              <ul className="space-y-1">
                {rollbacks.map((entry) => (
                  <li key={entry.strategy_version}>
                    <span className="font-mono text-label-m text-text-secondary">
                      {entry.strategy_version}
                    </span>{" "}
                    rolled back{" "}
                    {entry.rollback_of !== undefined && (
                      <ReferenceRow reference={entry.rollback_of} scope={scope} />
                    )}
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>

        {chosen !== undefined && (
          <VersionDetail entry={chosen} operator={operator} scope={scope} />
        )}
      </div>
    </>
  );
}

function VersionDetail({
  entry,
  operator,
  scope,
}: {
  entry: StrategyVersionRecord;
  operator: boolean;
  scope: ReturnType<typeof useScope>["scope"];
}) {
  return (
    <Card data-testid="version-detail" data-version={entry.strategy_version}>
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Label>{humanizeCode(entry.module.code)}</Label>
          <p className="mt-0.5 font-mono text-label-m text-text-secondary">
            {entry.strategy_version}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={ROLE_TONE[entry.role.code] ?? "neutral"}>
            {humanizeCode(entry.role.code)}
          </Badge>
          <Badge tone={entry.immutable ? "info" : "warning"}>
            {entry.immutable ? "Immutable" : "Mutable"}
          </Badge>
        </div>
      </CardHeader>
      <CardBody className="space-y-4">
        <PanelSection
          title="Recorded pins"
          note="The exact identities this version was created with. A pin that does not apply says so rather than being omitted."
          testId="version-pins"
        >
          <PinTable pins={entry.pins} testId="version-pin-table" />
        </PanelSection>

        <PanelSection
          title="Open-position pinning"
          note="An open position stays governed by the exact versions that opened it. None of them may mutate while it is open, and a retirement does not release one."
          testId="version-open-positions"
        >
          {entry.open_positions.length === 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              <AvailabilityBadge state="EMPTY_VERIFIED" reason="EMPTY_RESULT_VERIFIED" />
              <span className="max-w-3xl text-label-m text-text-tertiary">
                This version governs no open position.
                {entry.maturity_stage === "SHADOW" && (
                  <>
                    {" "}
                    <strong className="text-text-secondary">
                      A Challenger produces no order in any environment
                    </strong>
                    , so it can hold none — an empty population that is verified rather than
                    unknown.
                  </>
                )}
              </span>
            </div>
          ) : (
            <ul className="space-y-2" data-testid="open-position-list">
              {entry.open_positions.map((position) => (
                <li
                  key={position.position_ref.ref_id}
                  className="rounded-sm border border-border-subtle bg-surface-sunken p-3"
                  data-position={position.position_ref.ref_id}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <ReferenceRow
                      reference={position.trade_ref}
                      label="Trade"
                      scope={scope}
                      testId="open-position-trade"
                    />
                    <span className="font-mono text-label-s text-text-tertiary">
                      opened {position.opened_at}
                    </span>
                  </div>
                  <details className="mt-2">
                    <summary className="cursor-pointer text-label-s text-text-secondary">
                      The exact versions that opened this position
                    </summary>
                    <div className="mt-2">
                      <PinTable pins={position.pinned} />
                    </div>
                  </details>
                </li>
              ))}
            </ul>
          )}
        </PanelSection>

        <PanelSection
          title="Lineage and registrations"
          note="Where the version came from, and the preregistrations it was produced by or evaluated under."
          testId="version-lineage"
        >
          <div className="grid gap-3 lg:grid-cols-2">
            <ReferenceListPanel
              list={entry.lineage_refs}
              label="Lineage"
              scope={scope}
              empty="This version records no lineage reference."
            />
            <ReferenceListPanel
              list={entry.registration_refs}
              label="Registrations"
              scope={scope}
              empty="No preregistration names this version."
            />
          </div>
        </PanelSection>

        <PanelSection
          title="Recorded history"
          note="Activation, retirement, promotion and rollback, as recorded. Nothing here causes an event."
          testId="version-history"
        >
          <ol className="space-y-2">
            {entry.history.map((event) => (
              <li
                key={`${event.at}-${event.event.code}`}
                className="flex flex-wrap items-center gap-2 rounded-sm border border-border-subtle p-2"
                data-history-event={event.event.code}
              >
                <Badge tone="neutral">{humanizeCode(event.event.code)}</Badge>
                <span className="font-mono text-label-s text-text-tertiary">{event.at}</span>
                <span className="text-label-s text-text-secondary">
                  {humanizeCode(event.authority.code)}
                </span>
                {event.decision_ref !== undefined && (
                  <ReferenceRow reference={event.decision_ref} label="Decision" scope={scope} />
                )}
              </li>
            ))}
          </ol>
        </PanelSection>

        {operator && (
          <PanelSection
            title="Created at"
            note="The instant the immutable record was written."
            testId="version-created"
          >
            <p className="font-mono text-label-m text-text-secondary">{entry.created_at}</p>
            <p className="mt-1 text-label-s text-text-tertiary">
              Open-position count is a produced figure and is shown as{" "}
              {isValueBearing(entry.open_position_count.availability)
                ? "a measured value"
                : "an availability state"}
              .
            </p>
          </PanelSection>
        )}
      </CardBody>
    </Card>
  );
}
