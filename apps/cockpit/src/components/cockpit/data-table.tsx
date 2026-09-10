"use client";

import * as React from "react";
import {
  columnFilteringFeature,
  createColumnHelper,
  createFilteredRowModel,
  createSortedRowModel,
  filterFn_includesString,
  globalFilteringFeature,
  rowSortingFeature,
  sortFn_alphanumeric,
  sortFn_basic,
  sortFn_text,
  tableFeatures,
  useTable,
  type RowData,
  type TableOptions,
} from "@tanstack/react-table";
import { ChevronDown, ChevronRight, ChevronsUpDown } from "lucide-react";

import { Button, ScrollRegion } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

/**
 * The shared table.
 *
 * TanStack Table is HEADLESS: it owns sorting, filtering and row identity, and this module
 * owns the markup. That division is the point — the accessibility properties below are
 * things a table must have and a headless library cannot supply.
 *
 *   REAL HEADERS AND SCOPES        `<th scope="col">` and `<th scope="row">`, so a screen
 *                                  reader announces which column a cell belongs to
 *   SORTING IS ANNOUNCED           `aria-sort` on the sorted header, and the control is a
 *                                  BUTTON rather than a click handler on a `<th>`
 *   WIDE CONTENT SCROLLS ITSELF    inside a focusable, labelled region. **The page body never
 *                                  scrolls horizontally** (U14)
 *   COLUMN PRIORITY IS DECLARED    narrow viewports drop from the BOTTOM of a declared order,
 *                                  never arbitrarily, and **identity columns never drop**
 *   A DETAIL ROW IS A DISCLOSURE   with `aria-expanded` and `aria-controls`, reachable by
 *                                  keyboard, and never a hover-only affordance
 *
 * **SORTING AND FILTERING ARE PRESENTATION.** They re-order and narrow the rows this page was
 * ALREADY SERVED; they issue no request, change no scope and grant no permission. A page that
 * was truncated stays truncated, and the panel around this table says so.
 */

/**
 * The feature set, declared once, statically, outside any component.
 *
 * `columnFilteringFeature` is required by `globalFilteringFeature` and by the filtered row
 * model; the named sort functions are required by row sorting. A feature slot without its
 * prerequisite fails to type-check, which is why they travel together.
 */
export const TABLE_FEATURES = tableFeatures({
  columnFilteringFeature,
  globalFilteringFeature,
  rowSortingFeature,
  filteredRowModel: createFilteredRowModel(),
  sortedRowModel: createSortedRowModel(),
  filterFns: { includesString: filterFn_includesString },
  sortFns: {
    alphanumeric: sortFn_alphanumeric,
    text: sortFn_text,
    basic: sortFn_basic,
  },
});

export type TableFeatureSet = typeof TABLE_FEATURES;

/** A typed column helper for one row shape. */
export function columnsFor<TRow extends RowData>() {
  return createColumnHelper<TableFeatureSet, TRow>();
}

/**
 * The exact column-list type this table accepts.
 *
 * Taken FROM the table options rather than re-spelled as `ColumnDef<..., unknown>[]`: a
 * column definition is invariant in its value type, so a hand-written annotation and the
 * type `useTable` actually wants drift apart at the first typed accessor. Build one with
 * `columnsFor<Row>().columns([...])`, which preserves each column's own value type while
 * producing exactly this list.
 */
export type TableColumns<TRow extends RowData> = TableOptions<
  TableFeatureSet,
  TRow
>["columns"];

export interface DataTableProps<TRow extends RowData> {
  /** The table's accessible caption. It states WHAT the rows are, not how many. */
  readonly caption: string;
  readonly columns: TableColumns<TRow>;
  readonly data: readonly TRow[];
  readonly getRowId: (row: TRow) => string;
  /** The free-text search term. Owned by the page, because it lives in the URL (U13). */
  readonly globalFilter?: string;
  readonly initialSorting?: readonly { readonly id: string; readonly desc: boolean }[];
  /**
   * The extra row a reader can open.
   *
   * A table cannot show everything a row knows without becoming unreadable, and hiding the
   * rest behind a hover tooltip hides it from a keyboard. This is a disclosure.
   */
  readonly renderDetail?: (row: TRow) => React.ReactNode;
  /**
   * Per-column responsive classes, LOWEST priority first in the declared column order.
   *
   * A column with no entry here never drops: those are the identity columns, plus the
   * environment and provenance a row is read under.
   */
  readonly columnClasses?: Readonly<Record<string, string>>;
  /** What an empty result says. An empty table with no sentence is a table that broke. */
  readonly empty: React.ReactNode;
  readonly testId?: string;
}

export function DataTable<TRow extends RowData>({
  caption,
  columns,
  data,
  getRowId,
  globalFilter = "",
  initialSorting = [],
  renderDetail,
  columnClasses = {},
  empty,
  testId,
}: DataTableProps<TRow>) {
  const [openRow, setOpenRow] = React.useState<string | null>(null);
  const rows = React.useMemo(() => [...data], [data]);

  const table = useTable({
    features: TABLE_FEATURES,
    columns,
    data: rows,
    getRowId: (row: TRow) => getRowId(row),
    state: { globalFilter },
    initialState: { sorting: [...initialSorting] },
    globalFilterFn: "includesString",
    enableGlobalFilter: true,
  });

  const visibleRows = table.getRowModel().rows;

  return (
    <ScrollRegion
      label={caption}
      className="rounded-sm border border-border-subtle"
      /*
       * The shell's second skip link targets the FIRST of these inside `main`.
       * `ui-ux-specification.md` section 10 asks skip links to reach "the main content AND the
       * primary table", and a table is exactly the content a keyboard reader most needs to
       * reach without tabbing the whole sidebar and header first.
       */
      data-table-region=""
    >
      <table
        className="w-full min-w-[46rem] border-collapse text-label-m"
        data-testid={testId}
      >
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-surface-sunken">
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id} className="border-b border-border-subtle">
              {renderDetail !== undefined && (
                <th scope="col" className="w-8 px-2 py-2">
                  <span className="sr-only">Row detail</span>
                </th>
              )}
              {headerGroup.headers.map((header) => {
                const sorted = header.column.getIsSorted();
                const sortable = header.column.getCanSort();
                return (
                  <th
                    key={header.id}
                    scope="col"
                    aria-sort={
                      sorted === "asc"
                        ? "ascending"
                        : sorted === "desc"
                          ? "descending"
                          : sortable
                            ? "none"
                            : undefined
                    }
                    className={cn(
                      "px-3 py-2 text-left align-bottom font-medium text-text-tertiary",
                      columnClasses[header.column.id],
                    )}
                  >
                    {sortable ? (
                      <button
                        type="button"
                        onClick={header.column.getToggleSortingHandler()}
                        className="inline-flex items-center gap-1 rounded-sm text-text-tertiary hover:text-text-primary"
                      >
                        <table.FlexRender header={header} />
                        {sorted === "asc" ? (
                          <ChevronDown size={12} className="rotate-180" aria-hidden="true" />
                        ) : sorted === "desc" ? (
                          <ChevronDown size={12} aria-hidden="true" />
                        ) : (
                          <ChevronsUpDown size={12} aria-hidden="true" />
                        )}
                      </button>
                    ) : (
                      <table.FlexRender header={header} />
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {visibleRows.length === 0 && (
            <tr>
              <td
                colSpan={table.getAllLeafColumns().length + (renderDetail === undefined ? 0 : 1)}
                className="px-3 py-6 text-text-tertiary"
              >
                {empty}
              </td>
            </tr>
          )}
          {visibleRows.map((row) => {
            const rowId = row.id;
            const open = openRow === rowId;
            const cells = row.getAllCells();
            return (
              <React.Fragment key={rowId}>
                <tr
                  className="border-b border-border-subtle last:border-0 hover:bg-surface-sunken/60"
                  data-row-id={rowId}
                >
                  {renderDetail !== undefined && (
                    <td className="px-2 py-1.5 align-top">
                      <button
                        type="button"
                        aria-expanded={open}
                        aria-controls={`detail-${rowId}`}
                        onClick={() => setOpenRow(open ? null : rowId)}
                        className="rounded-sm p-0.5 text-text-tertiary hover:text-text-primary"
                      >
                        <span className="sr-only">
                          {open ? "Hide details for" : "Show details for"} {rowId}
                        </span>
                        {open ? (
                          <ChevronDown size={13} aria-hidden="true" />
                        ) : (
                          <ChevronRight size={13} aria-hidden="true" />
                        )}
                      </button>
                    </td>
                  )}
                  {cells.map((cell, index) => {
                    const className = cn(
                      "px-3 py-1.5 align-top",
                      columnClasses[cell.column.id],
                    );
                    /*
                     * The first cell is the row's HEADER, not a data cell: it is what
                     * identifies the row, and a screen reader announces it with every other
                     * cell in the row.
                     */
                    return index === 0 ? (
                      <th
                        key={cell.id}
                        scope="row"
                        className={cn(className, "text-left font-normal")}
                      >
                        <table.FlexRender cell={cell} />
                      </th>
                    ) : (
                      <td key={cell.id} className={className}>
                        <table.FlexRender cell={cell} />
                      </td>
                    );
                  })}
                </tr>
                {renderDetail !== undefined && open && (
                  <tr id={`detail-${rowId}`} className="border-b border-border-subtle">
                    <td
                      colSpan={cells.length + 1}
                      className="bg-surface-sunken px-4 py-3 align-top"
                    >
                      {renderDetail(row.original)}
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </ScrollRegion>
  );
}

/** The row count a table actually rendered, and the population it came from. */
export function RowCount({
  shown,
  total,
  noun,
}: {
  shown: number;
  total: number;
  noun: string;
}) {
  return (
    <p className="text-label-s text-text-tertiary" data-testid="row-count">
      Showing <strong className="font-mono text-text-secondary">{shown}</strong> of{" "}
      <strong className="font-mono text-text-secondary">{total}</strong> {noun} delivered by
      this read.{" "}
      {shown !== total && (
        <span>
          A filter is applied, and the hidden rows are still part of the population every
          figure above was computed over.
        </span>
      )}
    </p>
  );
}

export { Button };
