/**
 * Collection semantics — `read-model-contracts.md` §5.1, §5.2 and §6.
 *
 * A page endpoint returns **a page**, and a page that does not say so is read as a
 * population. Three things travel with every collection in this application:
 *
 *   HOW MANY EXIST          `total`, a `CountValue`, so a producer that cannot count the
 *                           population says so with a state rather than reporting the page
 *                           size as the answer
 *   WHETHER IT WAS CUT      `truncated`. "A silently truncated result is a wrong answer
 *                           wearing a correct one's shape" (§5.2)
 *   HOW IT WAS ORDERED      the declared sort key and its **deterministic tiebreak**, so
 *                           two identical requests return identical order (§6)
 *
 * **There is no cursor here, and that is deliberate.** §5.2's cursor "encodes the projection
 * `snapshot_version`, the sort key, the tiebreak key and the full filter set", and it is
 * meaningful only against a transport that can continue a page. This application's read
 * client is a local fixture adapter that returns one page and never continues one, so
 * carrying an opaque cursor field would describe a capability nothing implements. The
 * declared page size is stated instead, and a page beyond it is a **refusal** at the
 * boundary rather than a silent truncation.
 */
import { z } from "zod";

import { countValue, reasonCoded } from "./values";

/**
 * The delivered page's own description.
 *
 * `page_size` is the declared maximum this read serves, and `total` is how many rows exist.
 * The two disagreeing is exactly what `truncated` records.
 */
export const pageMeta = z
  .object({
    /** The declared maximum for this endpoint (§5.1). Never a row offset. */
    page_size: z.number().int().positive(),
    /** How many rows EXIST, which the delivered length is not. */
    total: countValue,
    truncated: z.boolean(),
    /** The declared sort key this page was ordered by. */
    sort: reasonCoded,
    /** The deterministic tiebreak. Without one, two identical requests can differ. */
    tiebreak: reasonCoded,
  })
  .superRefine((candidate, ctx) => {
    if (typeof candidate.total.value !== "number") {
      return;
    }
    if (!candidate.truncated && candidate.total.value > candidate.page_size) {
      ctx.addIssue({
        code: "custom",
        message: "a page holding more rows than its page size is truncated, and says so",
      });
    }
  });
export type PageMeta = z.infer<typeof pageMeta>;

/**
 * Builds a collection payload: the delivered rows, the page that describes them, and
 * whatever else the read model states once for the whole collection.
 *
 * The extra shape is spread into ONE object rather than intersected with it. An
 * intersection of two schemas is two validators over one value, and the second one's
 * cross-field rules cannot see the first one's fields — which is precisely what a
 * collection's invariants need.
 */
export function collectionPayload<
  TItem extends z.ZodTypeAny,
  TExtra extends z.ZodRawShape = Record<never, never>,
>(item: TItem, extra: TExtra = {} as TExtra) {
  return z
    .object({ items: z.array(item), page: pageMeta, ...extra })
    .superRefine((value, ctx) => {
      /*
       * The parsed value of a spread generic shape is a mapped type TypeScript cannot
       * narrow by property access. The two fields this refinement reads are declared
       * literally above, so they are named once here rather than re-derived.
       */
      const candidate = value as unknown as { items: unknown[]; page: PageMeta };
      const page = candidate.page;
      const items = candidate.items;
      if (items.length > page.page_size) {
        ctx.addIssue({
          code: "custom",
          message: "a page never carries more rows than its declared page size",
        });
      }
      const total = page.total.value;
      if (typeof total !== "number") {
        return;
      }
      if (items.length > total) {
        ctx.addIssue({
          code: "custom",
          message: "a page never carries more rows than it states a total of",
        });
      }
      if (!page.truncated && total !== items.length) {
        ctx.addIssue({
          code: "custom",
          message: "an untruncated page delivers every row it states a total of",
        });
      }
    });
}
