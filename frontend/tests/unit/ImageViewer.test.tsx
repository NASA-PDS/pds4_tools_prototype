import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import ImageViewer from "../../src/components/ImageViewer";

vi.mock("../../src/services/api", () => ({
  getImageMetadata: vi.fn().mockResolvedValue({
    label_id: "test-id",
    structure_index: 0,
    name: "Test Image",
    structure_type: "Array_2D_Image",
    dimensions: [360, 720],
    element_data_type: "UnsignedByte",
    width: 720,
    height: 360,
    bands: 1,
    band_axis: null,
  }),
  getImageStatistics: vi.fn().mockResolvedValue({
    min: 0,
    max: 255,
    mean: 128,
    std: 40,
    shape: [360, 720],
    dtype: "uint8",
    percentiles: {
      "1": 5,
      "5": 15,
      "25": 80,
      "50": 130,
      "75": 175,
      "95": 220,
      "99": 245,
    },
  }),
  renderImage: vi.fn().mockResolvedValue(new Blob(["test"], { type: "image/png" })),
  getPixelValue: vi.fn().mockResolvedValue({ x: 0, y: 0, band: 0, value: 42 }),
}));

import * as api from "../../src/services/api";

describe("ImageViewer", () => {
  it("[REQ-07] renders loading state initially", () => {
    render(<ImageViewer labelId="test-id" structureIndex={0} />);
    expect(screen.getByText("Loading image metadata...")).toBeInTheDocument();
  });

  it("[REQ-07] renders image header after metadata loads", async () => {
    render(<ImageViewer labelId="test-id" structureIndex={0} />);
    expect(await screen.findByText("Test Image")).toBeInTheDocument();
  });

  it("[REQ-07] shows image dimensions", async () => {
    render(<ImageViewer labelId="test-id" structureIndex={0} />);
    expect(await screen.findByText(/720 × 360/)).toBeInTheDocument();
  });

  it("[REQ-07] shows colormap selector", async () => {
    render(<ImageViewer labelId="test-id" structureIndex={0} />);
    await screen.findByText("Test Image");
    expect(screen.getByText("Colormap")).toBeInTheDocument();
  });

  it("[REQ-07] shows stretch selector", async () => {
    render(<ImageViewer labelId="test-id" structureIndex={0} />);
    await screen.findByText("Test Image");
    expect(screen.getByText("Stretch")).toBeInTheDocument();
  });

  it("[REQ-08] shows statistics after loading", async () => {
    render(<ImageViewer labelId="test-id" structureIndex={0} />);
    expect(await screen.findByText(/Min:/)).toBeInTheDocument();
    expect(screen.getByText(/Max:/)).toBeInTheDocument();
    expect(screen.getByText(/Mean:/)).toBeInTheDocument();
  });

  it("[REQ-07] hides the band selector for 2D images", async () => {
    render(<ImageViewer labelId="test-id" structureIndex={0} />);
    await screen.findByText("Test Image");
    expect(screen.queryByLabelText(/Band/)).not.toBeInTheDocument();
  });

  it("[REQ-07] [BUG-07] renders and computes statistics for the selected band of a 3D cube", async () => {
    vi.mocked(api.getImageMetadata).mockResolvedValueOnce({
      label_id: "cube",
      structure_index: 0,
      name: "Cube",
      structure_type: "Array_3D_Spectrum",
      dimensions: [4, 360, 720],
      element_data_type: "SignedMSB2",
      width: 720,
      height: 360,
      bands: 4,
      band_axis: 0,
    });
    render(<ImageViewer labelId="cube" structureIndex={0} />);
    expect(await screen.findByText(/× 4 bands/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Band/), { target: { value: "2" } });
    await waitFor(() =>
      expect(api.renderImage).toHaveBeenLastCalledWith("cube", 0, expect.objectContaining({ band: 2 })),
    );
    await waitFor(() => expect(api.getImageStatistics).toHaveBeenLastCalledWith("cube", 0, 2));
  });
});
