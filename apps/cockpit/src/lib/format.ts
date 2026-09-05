/**
 * Rendering a closed-vocabulary code as prose.
 *
 * Reason codes are SCREAMING_SNAKE_CASE members of closed vocabularies. Lowercasing them
 * wholesale turns `USD` into "usd" and `RUN_A` into "Run a", which reads as sloppy on a
 * governance screen. The tokens below keep their own casing; everything else is ordinary
 * prose with the first word capitalized.
 */
const PRESERVED: Readonly<Record<string, string>> = {
  KALPAMANI: "KalpaMani",
  USD: "USD",
  PIT: "PIT",
  AI: "AI",
  ADR: "ADR",
  INC: "INC",
  CONTROL: "CONTROL",
  A: "A",
  B: "B",
  R: "R",
};

export function humanizeCode(code: string): string {
  const words = code.split("_").map((token) => {
    const preserved = PRESERVED[token];
    if (preserved !== undefined) return preserved;
    // Gate and provider-test identifiers keep their own shape: G1, P9.
    if (/^[GP]\d$/.test(token)) return token;
    return token.toLowerCase();
  });

  const [first, ...rest] = words;
  if (first === undefined) return code;
  const leading =
    PRESERVED[code.split("_")[0]] !== undefined || /^[GP]\d$/.test(code.split("_")[0])
      ? first
      : first.charAt(0).toUpperCase() + first.slice(1);
  return [leading, ...rest].join(" ");
}
