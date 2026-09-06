import { Badge } from "@/components/ui/primitives";

/**
 * One `h1` per page, ordered headings, and a page-level availability statement where one
 * applies (ui-ux-specification.md section 11).
 */
export function PageHeader({
  title,
  summary,
  pageState,
  children,
}: {
  title: string;
  summary: string;
  /** The page reports itself PARTIAL when any widget is degraded (U6). */
  pageState?: "COMPLETE" | "PARTIAL";
  children?: React.ReactNode;
}) {
  return (
    <header className="mb-6">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-numeric-l font-semibold tracking-tight text-text-primary">{title}</h1>
        {pageState === "PARTIAL" && (
          <Badge tone="warning" data-testid="page-state">
            <span aria-hidden="true">◧</span>
            <span>Page partial</span>
          </Badge>
        )}
      </div>
      <p className="mt-1.5 max-w-3xl text-label-m leading-relaxed text-text-secondary">
        {summary}
      </p>
      {children !== undefined && <div className="mt-3">{children}</div>}
    </header>
  );
}
