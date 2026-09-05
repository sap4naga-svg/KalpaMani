/**
 * A clock, injected rather than read from the ambient environment.
 *
 * Test and demonstration scenarios use a DETERMINISTIC clock. A demonstration clock is
 * LABELLED as one and is never presented as the current source time.
 */
export interface Clock {
  now(): number;
  readonly kind: "system" | "fixed";
}

export const systemClock: Clock = {
  now: () => Date.now(),
  kind: "system",
};

export function fixedClock(instant: string | number): Clock {
  const fixed = typeof instant === "number" ? instant : Date.parse(instant);
  return { now: () => fixed, kind: "fixed" };
}
