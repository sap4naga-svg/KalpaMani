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

const DECIMAL_PARTS = /^(-?)(\d+)(?:\.(\d+))?$/;

/**
 * Renders a decimal string WITHOUT going through a binary float.
 *
 * `Number("80000.00").toLocaleString(...)` round-trips money through a `double`, which is
 * exactly what "decimal string, never binary floating point" (4.2) exists to prevent. Money
 * is carried as a decimal string precisely so the value that was measured is the value that
 * is shown, and parsing it to re-format it discards that guarantee at the last step.
 *
 * The digits are never recomputed here: they are grouped, padded to the metric's stated
 * precision, and signed.
 */
export function formatDecimal(
  value: string,
  options: { readonly minimumFractionDigits?: number; readonly signed?: boolean } = {},
): string | null {
  const parts = DECIMAL_PARTS.exec(value);
  if (parts === null) {
    return null;
  }
  const [, sign, whole, fraction = ""] = parts;
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const padded = fraction.padEnd(options.minimumFractionDigits ?? 0, "0");
  const body = padded.length > 0 ? `${grouped}.${padded}` : grouped;
  const nonZero = /[1-9]/.test(whole + fraction);
  const lead = sign === "-" && nonZero ? "-" : options.signed === true && nonZero ? "+" : "";
  return `${lead}${body}`;
}

/** The sign of a decimal string, decided on its DIGITS rather than on a parsed float. */
export function decimalSign(value: string): -1 | 0 | 1 {
  const parts = DECIMAL_PARTS.exec(value);
  if (parts === null) {
    return 0;
  }
  const [, sign, whole, fraction = ""] = parts;
  if (!/[1-9]/.test(whole + fraction)) {
    return 0;
  }
  return sign === "-" ? -1 : 1;
}
