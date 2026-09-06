"use client";

import * as React from "react";
import { Search, X } from "lucide-react";

import { Badge, Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

/**
 * Filter controls and the chips that make an applied filter visible.
 *
 * §8: "active filters are visible as removable chips. **A filter that is applied but
 * invisible is how a reader misreads a subset as the whole**." Every control here writes to
 * the URL through `usePageFilters`, so a filtered view is a shareable view.
 *
 * **THESE ARE PRESENTATION CONTROLS.** They narrow what is shown; they issue no request,
 * change no scope, compute no metric and grant no permission.
 */

export interface FilterChip {
  readonly key: string;
  readonly label: string;
  readonly value: string;
}

export function FilterChips({
  chips,
  onRemove,
  onClearAll,
}: {
  chips: readonly FilterChip[];
  onRemove: (key: string) => void;
  onClearAll: () => void;
}) {
  if (chips.length === 0) {
    return (
      <p className="text-label-s text-text-tertiary" data-testid="filter-chips-empty">
        No filter is applied. Every row this read delivered is shown.
      </p>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="filter-chips">
      <span className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
        Filters
      </span>
      {chips.map((chip) => (
        <span
          key={chip.key}
          className="inline-flex items-center gap-1 rounded-sm border border-accent-muted bg-surface-sunken py-0.5 pl-2 pr-1 text-label-s text-accent"
          data-filter-key={chip.key}
        >
          <span>
            {chip.label}: <strong className="font-mono">{chip.value}</strong>
          </span>
          <button
            type="button"
            onClick={() => onRemove(chip.key)}
            className="rounded-sm p-0.5 hover:bg-surface-overlay"
          >
            <span className="sr-only">Remove the {chip.label} filter</span>
            <X size={11} aria-hidden="true" />
          </button>
        </span>
      ))}
      <Button size="sm" variant="ghost" onClick={onClearAll}>
        Clear all
      </Button>
    </div>
  );
}

export function SearchField({
  id,
  label,
  value,
  onChange,
  placeholder,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (next: string) => void;
  placeholder: string;
}) {
  return (
    <div className="flex min-w-[12rem] flex-1 flex-col gap-1 sm:max-w-xs">
      <label htmlFor={id} className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
        {label}
      </label>
      <div className="relative">
        <Search
          size={13}
          aria-hidden="true"
          className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-text-tertiary"
        />
        <input
          id={id}
          type="search"
          value={value}
          placeholder={placeholder}
          onChange={(event) => onChange(event.currentTarget.value)}
          className={cn(
            "h-8 w-full rounded-sm border border-border-subtle bg-surface-sunken pl-8 pr-2",
            "text-label-m text-text-primary placeholder:text-text-tertiary",
          )}
        />
      </div>
    </div>
  );
}

export function SelectField<T extends string>({
  id,
  label,
  value,
  options,
  onChange,
  anyLabel = "Any",
}: {
  id: string;
  label: string;
  value: string;
  options: readonly { readonly value: T; readonly label: string }[];
  onChange: (next: string) => void;
  anyLabel?: string;
}) {
  return (
    <div className="flex min-w-[9rem] flex-col gap-1">
      <label htmlFor={id} className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.currentTarget.value)}
        className="h-8 rounded-sm border border-border-subtle bg-surface-sunken px-2 text-label-m text-text-primary"
      >
        <option value="">{anyLabel}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

export function DateField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (next: string) => void;
}) {
  return (
    <div className="flex min-w-[9rem] flex-col gap-1">
      <label htmlFor={id} className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
        {label}
      </label>
      <input
        id={id}
        type="date"
        value={value}
        onChange={(event) => onChange(event.currentTarget.value)}
        className="h-8 rounded-sm border border-border-subtle bg-surface-sunken px-2 text-label-m text-text-primary"
      />
    </div>
  );
}

/**
 * The bar every filtered table sits under.
 *
 * The date basis is stated beside the range, because §8 requires a date range to show "the
 * calendar basis and timezone" — a range with neither is a range whose boundaries depend on
 * the reader's clock.
 */
export function FilterBar({
  children,
  chips,
  onRemove,
  onClearAll,
  basis,
}: {
  children: React.ReactNode;
  chips: readonly FilterChip[];
  onRemove: (key: string) => void;
  onClearAll: () => void;
  basis?: React.ReactNode;
}) {
  return (
    <div className="space-y-2.5" data-testid="filter-bar">
      <div className="flex flex-wrap items-end gap-3">{children}</div>
      <FilterChips chips={chips} onRemove={onRemove} onClearAll={onClearAll} />
      {basis !== undefined && (
        <p className="flex flex-wrap items-center gap-2 text-label-s text-text-tertiary">
          <Badge tone="neutral">UTC</Badge>
          <span>{basis}</span>
        </p>
      )}
    </div>
  );
}
