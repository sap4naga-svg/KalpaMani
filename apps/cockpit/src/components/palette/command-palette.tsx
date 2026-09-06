"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Command } from "cmdk";
import * as Dialog from "@radix-ui/react-dialog";

import { Badge } from "@/components/ui/primitives";
import { NAV_GROUPS, NAV_ROUTES, type NavRoute } from "@/nav/registry";
import { withScope } from "@/lib/scope";
import { cn } from "@/lib/utils";

import { useScope } from "@/components/shell/use-scope";

/**
 * The command vocabulary is CLOSED (ui-ux-specification.md section 10).
 *
 * The palette NAVIGATES, SEARCHES AND FILTERS. It exposes NO state-changing verb (U9): no
 * order, risk, provider, approval, execution, promotion, capital or strategy mutation verb
 * exists here, and a later author cannot add one casually because the kinds below are the
 * whole vocabulary.
 */
export const COMMAND_KINDS = ["navigate", "filter"] as const;
export type CommandKind = (typeof COMMAND_KINDS)[number];

interface PaletteCommand {
  readonly id: string;
  readonly kind: CommandKind;
  readonly label: string;
  readonly hint: string;
  readonly keywords: readonly string[];
  readonly run: () => void;
}

export interface PaletteController {
  readonly isOpen: boolean;
  /** The element focus returns to when the palette closes. */
  readonly openerRef: React.RefObject<HTMLElement | null>;
  /** Opens the palette, recording `opener` as the element focus returns to. */
  open: (opener?: HTMLElement | null) => void;
  close: () => void;
  setOpen: (open: boolean) => void;
}

export function useCommandPalette(): PaletteController {
  const [isOpen, setOpen] = React.useState(false);
  /*
   * The element that opened the palette.
   *
   * Escape must return focus TO THE ELEMENT THAT OPENED IT (U8). The palette opens from a
   * keyboard shortcut as well as from the header button, and a shortcut has no
   * `Dialog.Trigger` for Radix to restore focus to -- so the opener is captured here and
   * restored explicitly on close.
   */
  const openerRef = React.useRef<HTMLElement | null>(null);

  const openFrom = React.useCallback((opener: HTMLElement | null) => {
    openerRef.current = opener;
    setOpen(true);
  }, []);

  React.useEffect(() => {
    // Cmd/Ctrl+K opens the palette from anywhere, including from within a dialog.
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((current) => {
          if (current) return false;
          openerRef.current = document.activeElement as HTMLElement | null;
          return true;
        });
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return React.useMemo(
    () => ({
      isOpen,
      openerRef,
      open: (opener?: HTMLElement | null) =>
        openFrom(opener ?? (document.activeElement as HTMLElement | null)),
      close: () => setOpen(false),
      setOpen: (open: boolean) => {
        if (open) openerRef.current = document.activeElement as HTMLElement | null;
        setOpen(open);
      },
    }),
    [isOpen, openFrom],
  );
}

function groupLabel(route: NavRoute): string {
  return NAV_GROUPS.find((group) => group.id === route.group)?.label ?? route.group;
}

export function CommandPalette({ controller }: { controller: PaletteController }) {
  const router = useRouter();
  const { scope, setScope } = useScope();
  const [search, setSearch] = React.useState("");

  const commands = React.useMemo<PaletteCommand[]>(() => {
    // Environment and provenance context is preserved in every destination URL.
    const navigation = NAV_ROUTES.map<PaletteCommand>((route) => ({
      id: `navigate:${route.href}`,
      kind: "navigate",
      label: route.label,
      hint: groupLabel(route),
      keywords: [route.href, ...(route.keywords ?? []), ...route.areas.map(String)],
      run: () => router.push(withScope(route.href, scope)),
    }));

    const filters: PaletteCommand[] = [
      {
        id: "filter:mode-executive",
        kind: "filter",
        label: "View as Executive",
        hint: "Local view filter",
        keywords: ["mode", "executive"],
        run: () => setScope({ mode: "executive" }),
      },
      {
        id: "filter:mode-operator",
        kind: "filter",
        label: "View as Operator",
        hint: "Local view filter",
        keywords: ["mode", "operator", "evidence"],
        run: () => setScope({ mode: "operator" }),
      },
      {
        id: "filter:scenario-project",
        kind: "filter",
        label: "Show project readiness (tracked facts)",
        hint: "Local data scope",
        keywords: ["scenario", "project", "real", "tracked"],
        run: () => setScope({ scenario: "project" }),
      },
      {
        id: "filter:scenario-demo",
        kind: "filter",
        label: "Show synthetic demonstration data",
        hint: "Local data scope",
        keywords: ["scenario", "demo", "synthetic", "fixture"],
        run: () => setScope({ scenario: "demo" }),
      },
    ];

    return [...navigation, ...filters];
  }, [router, scope, setScope]);

  const runCommand = (command: PaletteCommand) => {
    controller.close();
    command.run();
  };

  return (
    <Dialog.Root
      open={controller.isOpen}
      onOpenChange={(open) => {
        // Reset the search as the layer closes, rather than reacting to it afterwards.
        if (!open) setSearch("");
        controller.setOpen(open);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/60" />
        <Dialog.Content
          data-testid="command-palette"
          onCloseAutoFocus={(event) => {
            // Radix has no trigger to restore to when the palette was opened by shortcut.
            const opener = controller.openerRef.current;
            if (opener !== null && opener.isConnected) {
              event.preventDefault();
              opener.focus();
            }
          }}
          className={cn(
            "fixed left-1/2 top-[12vh] z-50 w-[min(38rem,92vw)] -translate-x-1/2",
            "overflow-hidden rounded-md border border-border-strong bg-surface-overlay",
            "shadow-elevation-2",
          )}
        >
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <Dialog.Description className="sr-only">
            Navigate and filter. This palette exposes no state-changing command.
          </Dialog.Description>
          <Command loop label="Command palette">
            <div className="border-b border-border-subtle px-4">
              <Command.Input
                autoFocus
                value={search}
                onValueChange={setSearch}
                placeholder="Search areas and view filters…"
                className={cn(
                  "h-12 w-full bg-transparent text-numeric-s text-text-primary outline-none",
                  "placeholder:text-text-tertiary",
                )}
              />
            </div>
            <Command.List className="max-h-[52vh] overflow-y-auto p-2">
              <Command.Empty className="px-3 py-6 text-center text-label-m text-text-tertiary">
                No area or view filter matches that search. The palette navigates and filters
                only — it has no state-changing command.
              </Command.Empty>
              {COMMAND_KINDS.map((kind) => (
                <Command.Group
                  key={kind}
                  heading={kind === "navigate" ? "Go to" : "View filters"}
                  className={cn(
                    "[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5",
                    "[&_[cmdk-group-heading]]:text-label-s",
                    "[&_[cmdk-group-heading]]:uppercase",
                    "[&_[cmdk-group-heading]]:tracking-[0.09em]",
                    "[&_[cmdk-group-heading]]:text-text-tertiary",
                  )}
                >
                  {commands
                    .filter((command) => command.kind === kind)
                    .map((command) => (
                      <Command.Item
                        key={command.id}
                        value={`${command.label} ${command.keywords.join(" ")}`}
                        onSelect={() => runCommand(command)}
                        className={cn(
                          "flex cursor-pointer items-center gap-2 rounded-sm px-3 py-2",
                          "text-label-m text-text-secondary",
                          "data-[selected=true]:bg-surface-sunken",
                          "data-[selected=true]:text-text-primary",
                        )}
                      >
                        <span className="truncate">{command.label}</span>
                        <Badge tone="unavailable" className="ml-auto shrink-0">
                          {command.hint}
                        </Badge>
                      </Command.Item>
                    ))}
                </Command.Group>
              ))}
            </Command.List>
          </Command>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
