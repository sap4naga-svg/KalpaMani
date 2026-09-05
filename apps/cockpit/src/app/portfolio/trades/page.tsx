import { NotImplementedPage } from "@/components/cockpit/not-implemented-page";

/**
 * A later-cycle route. It is REGISTERED AND REACHABLE so navigation is complete, and
 * it IMPLEMENTS NO PRODUCT AREA. The shared page names the area, its purpose, its
 * producer or dependency and its intended cycle.
 */
export default function Page() {
  return <NotImplementedPage href="/portfolio/trades" />;
}
