"use client";

import * as React from "react";

import { systemClock, type Clock } from "@/lib/clock";

const ClockContext = React.createContext<Clock>(systemClock);

export function ClockProvider({
  clock,
  children,
}: {
  clock: Clock;
  children: React.ReactNode;
}) {
  return <ClockContext.Provider value={clock}>{children}</ClockContext.Provider>;
}

/**
 * The injected clock.
 *
 * Test and demonstration scenarios inject a deterministic one. A DEMONSTRATION CLOCK IS
 * LABELLED AS ONE and is never presented as the current source time.
 */
export function useClock(): Clock {
  return React.useContext(ClockContext);
}
