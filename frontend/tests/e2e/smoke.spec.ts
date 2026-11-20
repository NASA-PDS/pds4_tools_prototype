import { test, expect } from "@playwright/test";

// Requires the backend on :8000 with PDS_LOCAL_ROOT pointing at ../test_data.

test("homepage loads with header and empty state", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("PDS View")).toBeVisible();
  await expect(page.getByText("Upload a PDS4 label to get started")).toBeVisible();
});

test("upload tab shows drop zone", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByText("Drop label + data files here")).toBeVisible();
});

test("browse and render an Array_2D_Image", async ({ page }) => {
  await page.goto("/");
  await page.getByText("array_2d_image", { exact: true }).click();
  await page.getByText("thermal_neutron_map.xml").click();
  await page.getByRole("button", { name: "Open", exact: true }).click();
  await expect(page.getByText("Mercury Thermal Neutron Map").first()).toBeVisible();
  await page.getByRole("button", { name: "Image", exact: true }).click();
  await expect(page.getByText("720 × 360")).toBeVisible();
  await expect(page.locator("img[src^='blob:']")).toBeVisible();
});

test("browse a Table_Character, page it, and plot a histogram", async ({ page }) => {
  await page.goto("/");
  await page.getByText("table_character_cal", { exact: true }).click();
  await page.getByText(/ch3_cht_cal.*\.xml/).click();
  await page.getByRole("button", { name: "Open", exact: true }).click();
  await expect(page.getByText("Showing 1–100 of 3,252")).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByText("Showing 101–200 of 3,252")).toBeVisible();
  await page.getByRole("button", { name: "Plot", exact: true }).click();
  await page.getByRole("button", { name: "Generate Plot" }).click();
  await expect(page.locator(".js-plotly-plot")).toBeVisible();
});
