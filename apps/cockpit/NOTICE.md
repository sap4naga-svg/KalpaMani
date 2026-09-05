# Third-party notices — KalpaMani Cockpit

This application uses the third-party components below. Their licences apply to their own
code, and this notice is retained as those licences require.

## Copied component patterns

**shadcn/ui** — MIT License, Copyright (c) 2023 shadcn.
<https://github.com/shadcn-ui/ui>

shadcn/ui is a copy-in component pattern rather than a runtime dependency. The primitives in
[`src/components/ui/primitives.tsx`](src/components/ui/primitives.tsx) are authored in that
pattern — the `cn` class-merge helper in [`src/lib/utils.ts`](src/lib/utils.ts), the
`class-variance-authority` variant style, and the composition of Radix primitives with
Tailwind utility classes. They are written for this repository so they can be reviewed here,
and the attribution is recorded because the pattern is derived work.

## Runtime dependencies

| Component | Licence |
|---|---|
| React, React DOM | MIT |
| Next.js | MIT |
| Radix UI primitives | MIT |
| cmdk | MIT |
| TanStack Query, TanStack Table | MIT |
| Zod | MIT |
| Tailwind CSS | MIT |
| class-variance-authority | Apache-2.0 |
| clsx, tailwind-merge | MIT |
| lucide-react | ISC |

Each package ships its own licence text in `node_modules/<package>/LICENSE`. The complete,
resolved dependency set is recorded in `package-lock.json`.

## Fonts

**No font is downloaded at runtime or at build time.** The interface uses locally available
system font stacks declared in [`src/app/globals.css`](src/app/globals.css). There is no
runtime font dependency, no CDN request and no third-party telemetry of any kind.
