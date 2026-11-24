import { render, screen } from "@testing-library/react";
import { afterEach, describe, it, expect, vi } from "vitest";
import App from "../../src/App";
import { ThemeProvider } from "../../src/ThemeContext";

function stubServer(uploadEnabled: boolean) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      let body: unknown = [];
      if (url.includes("/api/config")) {
        body = { upload_enabled: uploadEnabled, max_upload_mb: 1024 };
      } else if (url.includes("/api/browse/sources")) {
        body = [{ name: "local", root: "/data" }];
      } else if (url.includes("/api/browse/list")) {
        body = { source: "local", current_path: "/data", parent_path: null, entries: [] };
      }
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
}

function renderApp() {
  return render(
    <ThemeProvider>
      <App />
    </ThemeProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("[REQ-01] renders the header", () => {
    stubServer(false);
    renderApp();
    expect(screen.getByText("PDS View")).toBeInTheDocument();
  });

  it("[REQ-01] shows supported file types hint", () => {
    stubServer(false);
    renderApp();
    expect(
      screen.getByText("Supports .xml and .lblx PDS4 label files"),
    ).toBeInTheDocument();
  });

  it("[REQ-17] hides upload when the server has it disabled", async () => {
    stubServer(false);
    renderApp();
    expect(
      await screen.findByText("Browse to a PDS4 label to get started"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Upload" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Browse Files" })).toBeInTheDocument();
  });

  it("[REQ-17] [REQ-01] shows upload when the server enables it", async () => {
    stubServer(true);
    renderApp();
    expect(
      await screen.findByRole("button", { name: "Upload" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Upload a PDS4 label to get started"),
    ).toBeInTheDocument();
  });
});
