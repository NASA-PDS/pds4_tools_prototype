/**
 * Requirement / bug traceability for Playwright tests.
 *
 *   test("does X", trace("REQ-07", "BUG-07"), async ({ page }) => { ... })
 *
 * Adds `@REQ-07` tags (filter with `--grep @REQ-07`) and annotations. With the
 * JUnit reporter's `embedAnnotationsAsProperties`, each annotation becomes a
 * <property> in test-results/junit-e2e.xml:
 *   requirement=REQ-07, bug=BUG-07, issue=NASA-PDS/pds4_tools_prototype#12,
 *   testrail_case_field=refs:NASA-PDS/pds4_tools_prototype#12,...
 * which traceability/trace_matrix.py and TestRail (trcli) consume.
 */
import traceability from "../../../traceability/traceability.json" with { type: "json" };

type Item = { type: string; issue: number | null };
const items = traceability.items as Record<string, Item>;

export function trace(...keys: string[]) {
  const annotation: { type: string; description: string }[] = [];
  const refs: string[] = [];
  for (const key of keys) {
    const item = items[key];
    if (!item) throw new Error(`Unknown traceability key ${key}`);
    annotation.push({ type: item.type === "requirement" ? "requirement" : "bug", description: key });
    if (item.issue) {
      const ref = `${traceability.repository}#${item.issue}`;
      refs.push(ref);
      annotation.push({ type: "issue", description: ref });
    }
  }
  if (refs.length) annotation.push({ type: "testrail_case_field", description: `refs:${refs.join(",")}` });
  return { tag: keys.map((k) => `@${k}`), annotation };
}
