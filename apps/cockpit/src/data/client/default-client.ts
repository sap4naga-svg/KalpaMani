/**
 * The C3 composition point.
 *
 * This is the ONLY module outside `src/data/fixtures/` that names the fixture adapter, so
 * PRESENTATION NEVER IMPORTS FIXTURE DATA. A later authorized cycle replaces the body of
 * this function with the versioned read-API client and changes nothing else.
 */
import { FixtureReadClient } from "@/data/fixtures/adapter";
import type { Clock } from "@/lib/clock";

import type { ReadClient } from "./read-client";

export function createDefaultReadClient(clock: Clock): ReadClient {
  return new FixtureReadClient({ clock });
}
