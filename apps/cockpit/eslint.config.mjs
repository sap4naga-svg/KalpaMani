import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "playwright-report/**",
    "test-results/**",
    "screenshots/**",
  ]),
  {
    /*
     * The layering rule, enforced rather than documented.
     *
     * PRESENTATION MUST NOT IMPORT FIXTURE DATA. Components and pages talk to the typed
     * read-client boundary; `src/data/client/default-client.ts` is the one composition
     * point that names the fixture adapter.
     */
    files: ["src/app/**/*.{ts,tsx}", "src/components/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/data/fixtures/*", "**/data/fixtures/*"],
              message:
                "Presentation must not import fixture data. Use the read-client boundary " +
                "(@/data/client/hooks); the fixture adapter is composed in " +
                "@/data/client/default-client.",
            },
          ],
        },
      ],
    },
  },
]);

export default eslintConfig;
