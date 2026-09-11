import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * The typographic size tokens `globals.css` declares under `@theme` (`--text-numeric-xl` …
 * `--text-label-s`), which Tailwind v4 turns into `text-numeric-xl` … `text-label-s` utilities.
 *
 * THEY ARE REGISTERED HERE BECAUSE tailwind-merge DID NOT KNOW THEM, AND IT WAS DROPPING THEM.
 *
 * tailwind-merge classifies `text-*` by value: a known size (`text-sm`, `text-[2rem]`) is a
 * font-size, and anything else is a text COLOUR. `text-numeric-l` is not a size it knows, so
 * `cn("text-numeric-l", "text-positive")` was two colours in conflict, the last one won, and
 * the size was silently removed from the class list. Measured on the rendered Executive
 * Overview at exact `main`: every tier-1 figure, every tile subject, every badge, every tier-2
 * figure and every panel heading computed to 16px -- the body size -- because each passes a
 * colour through `cn` after its size. The h1, whose classes never went through `cn`, was the
 * one element at its token size. The accepted numeric hierarchy (`ui-ux-specification.md`
 * §4.4, "three sizes, not five") and the label scale never reached the screen anywhere, on any
 * route; this is the defect behind "primary values are too small relative to their cards" and
 * "badges compete with the headline answers".
 *
 * Registering the six tokens as the `font-size` class group makes them what they are: a size
 * and a colour no longer conflict, and a size later in the list still overrides an earlier one.
 * Nothing about colours, spacing or any other group changes.
 */
const TEXT_SIZE_TOKENS = ["numeric-xl", "numeric-l", "numeric-m", "numeric-s", "label-m", "label-s"];

const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: TEXT_SIZE_TOKENS }],
    },
  },
});

/** The shadcn/ui class-merge helper. See NOTICE.md for third-party attribution. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
