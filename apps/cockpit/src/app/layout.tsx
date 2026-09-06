import type { Metadata } from "next";
import { Suspense } from "react";

import { AppShell } from "@/components/shell/app-shell";
import { Providers } from "@/components/shell/providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "KalpaMani Cockpit",
  description:
    "The observational Cockpit foundation for KalpaMani. Read-only, synthetic and tracked " +
    "governance facts only.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <Suspense fallback={null}>
            <AppShell>{children}</AppShell>
          </Suspense>
        </Providers>
      </body>
    </html>
  );
}
