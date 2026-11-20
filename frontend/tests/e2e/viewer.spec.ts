import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect, type Page } from "@playwright/test";
import { trace } from "./trace";

// Requires the backend on :8000 with PDS_LOCAL_ROOT=<repo>/test_data (see playwright.config.ts).
const TEST_DATA = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../test_data");

async function openFromBrowser(page: Page, dir: string, label: string | RegExp) {
  await page.goto("/");
  await page.getByText(dir, { exact: true }).click();
  await page.getByText(label).click();
  await page.getByRole("button", { name: "Open", exact: true }).click();
}

test("shows header and empty state", trace("REQ-01", "REQ-16", "BUG-08"), async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("PDS View")).toBeVisible();
  await expect(page.getByText("Upload a PDS4 label to get started")).toBeVisible();
});

test("uploads a label with its data file and lists structures", trace("REQ-01", "REQ-03"), async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByText("Drop label + data files here")).toBeVisible();
  await page.locator('input[type="file"]').first().setInputFiles([
    path.join(TEST_DATA, "table_character/Table_Character_Example.xml"),
    path.join(TEST_DATA, "table_character/Table_Character_Example.tab"),
  ]);
  await page.getByRole("button", { name: "View Data" }).click();
  await expect(page.getByText("DATA STRUCTURES", { exact: false })).toBeVisible();
  await expect(page.getByText(/Table_Character/).first()).toBeVisible();
});

test("browses the configured source and cannot leave its root", trace("REQ-02", "REQ-14", "BUG-02"), async ({ page }) => {
  await page.goto("/");
  for (const dir of ["array_2d_image", "array_3d_spectrum", "table_character", "table_character_cal"]) {
    await expect(page.getByText(dir, { exact: true })).toBeVisible();
  }
  // At the configured root there is no way up.
  await expect(page.getByText("Parent directory")).toHaveCount(0);
  const resp = await page.request.get("/api/browse/list", { params: { source: "local", path: "/etc" } });
  expect(resp.status()).toBe(404);
});

test(
  "renders a 2D image with statistics in physical units, colormap and pixel values",
  trace("REQ-07", "REQ-08", "REQ-10", "BUG-10"),
  async ({ page }) => {
  await openFromBrowser(page, "array_2d_image", "thermal_neutron_map.xml");
  await page.getByRole("button", { name: "Image", exact: true }).click();
  await expect(page.getByText("720 × 360")).toBeVisible();
  const img = page.locator("img[src^='blob:']");
  await expect(img).toBeVisible();
  // Stored bytes 0-255 scaled by the label's scaling_factor 0.222860 → max 56.83
  await expect(page.getByText(/Max:\s*56\.83/)).toBeVisible();

  const firstSrc = await img.getAttribute("src");
  await page.locator("select").first().selectOption("viridis");
  await expect(img).not.toHaveAttribute("src", firstSrc!);

  await img.hover({ position: { x: 200, y: 60 } });
  await expect(page.getByText(/\(\d+, \d+\) = [\d.]+/)).toBeVisible();
  },
);

test(
  "renders bands of an LSB 3D cube with scaling and special constants",
  trace("REQ-07", "REQ-08", "REQ-10", "REQ-11", "BUG-03", "BUG-07"),
  async ({ page }) => {
    await openFromBrowser(page, "array_3d_spectrum", "synthetic_cube.xml");
    await page.getByRole("button", { name: "Image", exact: true }).click();
    await expect(page.getByText(/64 × 48 × 3 bands/)).toBeVisible();
    // Values are scaled by 0.5 (raw range ~100-300 → ~50-150); -9999 fill is excluded, not the minimum.
    const min = Number((await page.getByText(/Min:/).innerText()).match(/-?[\d.]+/)![0]);
    expect(min).toBeGreaterThan(40);
    expect(min).toBeLessThan(60);

    const img = page.locator("img[src^='blob:']");
    await expect(img).toBeVisible();
    const band0 = await img.getAttribute("src");
    await page.getByLabel(/Band/).fill("2");
    await expect(img).not.toHaveAttribute("src", band0!);

    // Top-left 8x8 block is the missing_constant → null pixel value.
    const box = (await img.boundingBox())!;
    await img.hover({ position: { x: box.width * 0.03, y: box.height * 0.03 } });
    await expect(page.getByText(/\(\d, \d\) = null/)).toBeVisible();
  },
);

test("pages through a character table", trace("REQ-04"), async ({ page }) => {
  await openFromBrowser(page, "table_character_cal", /ch3_cht_cal.*\.xml/);
  await expect(page.getByText("Showing 1–100 of 3,252")).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Showing 101–200 of 3,252")).toBeVisible();
});

test("exports the full table as CSV", trace("REQ-05", "BUG-09"), async ({ page }) => {
  await openFromBrowser(page, "table_character_cal", /ch3_cht_cal.*\.xml/);
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Export CSV" }).click(),
  ]);
  const text = await (await download.createReadStream()).toArray().then((c) => Buffer.concat(c).toString());
  expect(text.trim().split(/\r?\n/)).toHaveLength(3252 + 1);
});

test("plots a histogram of a table column", trace("REQ-06"), async ({ page }) => {
  await openFromBrowser(page, "table_character_cal", /ch3_cht_cal.*\.xml/);
  await page.getByRole("button", { name: "Plot", exact: true }).click();
  await page.getByRole("button", { name: "Generate Plot" }).click();
  await expect(page.locator(".js-plotly-plot")).toBeVisible();
  await expect(page.locator(".js-plotly-plot .bars path").first()).toBeVisible();
});

test("shows the label XML tree", trace("REQ-09"), async ({ page }) => {
  await openFromBrowser(page, "array_2d_image", "thermal_neutron_map.xml");
  await page.getByRole("button", { name: "Label", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Identification" })).toBeVisible();
  await expect(page.getByText("Product_Observational").first()).toBeVisible();
});
