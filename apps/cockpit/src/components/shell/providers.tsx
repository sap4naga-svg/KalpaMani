"use client";

import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { createDefaultReadClient } from "@/data/client/default-client";
import type { ReadClient } from "@/data/client/read-client";
import { systemClock, type Clock } from "@/lib/clock";

import { ClockProvider } from "./clock-provider";

const ReadClientContext = React.createContext<ReadClient | null>(null);

export function useReadClient(): ReadClient {
  const client = React.useContext(ReadClientContext);
  if (client === null) {
    throw new Error("useReadClient requires a ReadClientProvider");
  }
  return client;
}

/**
 * A configured cache TTL may SHORTEN and never extend a source fact's remaining budget
 * (ADR-0029 section 2.2). This TTL is deliberately short, and it is a CEILING ON REUSE
 * rather than a grant of freshness: the absolute per-input deadline is evaluated
 * separately, on every render, by `useLiveFreshness`.
 */
const CONFIGURED_STALE_TIME_MS = 15_000;

export function Providers({
  children,
  clock = systemClock,
  readClient,
}: {
  children: React.ReactNode;
  clock?: Clock;
  readClient?: ReadClient;
}) {
  const [queryClient] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: CONFIGURED_STALE_TIME_MS,
            retry: false,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );
  const [client] = React.useState<ReadClient>(
    () => readClient ?? createDefaultReadClient(clock),
  );

  return (
    <ClockProvider clock={clock}>
      <ReadClientContext.Provider value={client}>
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      </ReadClientContext.Provider>
    </ClockProvider>
  );
}
