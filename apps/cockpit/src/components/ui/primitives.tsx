/**
 * Interface primitives in the shadcn/ui pattern, built on Radix primitives.
 *
 * shadcn/ui is a copy-in component pattern rather than a dependency; these are authored
 * here in that pattern so they can be reviewed as part of this repository. See NOTICE.md
 * for third-party attribution.
 */
import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

export function Card({
  className,
  ...props
}: React.ComponentPropsWithoutRef<"section">) {
  return (
    <section
      className={cn(
        "rounded-md border border-border-subtle bg-surface-raised shadow-elevation-1",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({
  className,
  ...props
}: React.ComponentPropsWithoutRef<"header">) {
  return <header className={cn("px-5 pt-4 pb-2", className)} {...props} />;
}

export function CardBody({ className, ...props }: React.ComponentPropsWithoutRef<"div">) {
  return <div className={cn("px-5 pb-5", className)} {...props} />;
}

/** A section label. Uppercase, tertiary, and never competing with the number it labels. */
export function Label({ className, ...props }: React.ComponentPropsWithoutRef<"span">) {
  return (
    <span
      className={cn(
        "text-label-s font-medium uppercase tracking-[0.09em] text-text-tertiary",
        className,
      )}
      {...props}
    />
  );
}

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 text-label-s " +
    "font-medium whitespace-nowrap",
  {
    variants: {
      tone: {
        neutral: "border-border-subtle bg-surface-sunken text-text-secondary",
        accent: "border-accent-muted bg-surface-sunken text-accent",
        positive: "border-positive/40 bg-surface-sunken text-positive",
        negative: "border-negative/40 bg-surface-sunken text-negative",
        warning: "border-warning/40 bg-surface-sunken text-warning",
        info: "border-info/40 bg-surface-sunken text-info",
        /** Low-chroma by design: an unavailable state is not an error. */
        unavailable: "border-border-subtle bg-surface-sunken text-unavailable",
        /** SYNTHETIC must be unmissable, not a tooltip. */
        synthetic: "border-warning bg-warning/15 text-warning",
        /** REPOSITORY_TRACKED is REAL and is visually distinct from SYNTHETIC. */
        tracked: "border-info/60 bg-info/12 text-info",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps
  extends React.ComponentPropsWithoutRef<"span">,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-sm text-label-m font-medium " +
    "transition-colors disabled:cursor-not-allowed disabled:opacity-60",
  {
    variants: {
      variant: {
        primary: "bg-accent text-text-inverse hover:bg-accent/90",
        subtle:
          "border border-border-subtle bg-surface-sunken text-text-secondary " +
          "hover:border-border-strong hover:text-text-primary",
        ghost: "text-text-secondary hover:bg-surface-sunken hover:text-text-primary",
      },
      size: {
        sm: "h-7 px-2.5",
        md: "h-9 px-3.5",
      },
    },
    defaultVariants: { variant: "subtle", size: "md" },
  },
);

export interface ButtonProps
  extends React.ComponentPropsWithoutRef<"button">,
    VariantProps<typeof buttonVariants> {}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  function Button({ className, variant, size, type = "button", ...props }, ref) {
    return (
      <button
        ref={ref}
        type={type}
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      />
    );
  },
);

/**
 * A loading skeleton. SHAPE ONLY -- it carries no digits and no plausible placeholder
 * value, so a screenshot taken mid-load is not mistakable for data (U7).
 */
export function Skeleton({ className, ...props }: React.ComponentPropsWithoutRef<"div">) {
  return (
    <div
      aria-hidden="true"
      data-testid="skeleton"
      className={cn("skeleton-shape h-4 w-full", className)}
      {...props}
    />
  );
}

export function Separator({ className, ...props }: React.ComponentPropsWithoutRef<"hr">) {
  return <hr className={cn("border-0 border-t border-border-subtle", className)} {...props} />;
}

/** A monospaced, tabular numeric. Every number, identifier, code and timestamp uses this. */
export function Numeric({
  className,
  size = "m",
  ...props
}: React.ComponentPropsWithoutRef<"span"> & { size?: "xl" | "l" | "m" | "s" }) {
  const sizes = {
    xl: "text-numeric-xl",
    l: "text-numeric-l",
    m: "text-numeric-m",
    s: "text-numeric-s",
  } as const;
  return (
    <span
      data-numeric=""
      className={cn("font-mono tabular-nums", sizes[size], className)}
      {...props}
    />
  );
}

/**
 * A horizontally scrollable region.
 *
 * Wide content scrolls inside its OWN container, and the page body never scrolls sideways.
 * A scrollable region must also be reachable by keyboard, so it is focusable and carries an
 * accessible name -- a scroll container a keyboard user cannot reach is content they cannot
 * read.
 */
export function ScrollRegion({
  label,
  className,
  ...props
}: React.ComponentPropsWithoutRef<"div"> & { label: string }) {
  return (
    <div
      role="region"
      aria-label={label}
      tabIndex={0}
      className={cn("overflow-x-auto", className)}
      {...props}
    />
  );
}
