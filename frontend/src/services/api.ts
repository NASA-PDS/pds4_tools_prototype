const API_BASE = "/api";

const LABEL_ID_RE = /^[A-Za-z0-9_-]+$/;

/** Validated, URL-encoded label id for use as a path segment. */
function labelSeg(labelId: string): string {
  if (!LABEL_ID_RE.test(labelId)) throw new Error(`Invalid label id: ${labelId}`);
  return encodeURIComponent(labelId);
}

/** Validated non-negative integer for use as a path segment or query value. */
function intSeg(value: number, name: string): string {
  if (!Number.isInteger(value) || value < 0) throw new Error(`Invalid ${name}: ${value}`);
  return encodeURIComponent(String(value));
}

/** Validated `<labelId>/<structureIndex>` path. */
function structureSeg(labelId: string, structureIndex: number): string {
  return `${labelSeg(labelId)}/${intSeg(structureIndex, "structure index")}`;
}

/**
 * Resolve an API path to an absolute same-origin URL under /api/. Every request goes
 * through this, so user-controlled values can never redirect a request elsewhere.
 */
function apiUrl(path: string): string {
  const origin = globalThis.location?.origin ?? "http://localhost";
  const url = new URL(`${API_BASE}${path}`, origin);
  if (url.origin !== origin || !url.pathname.startsWith(`${API_BASE}/`)) {
    throw new Error(`Refusing request outside the API: ${path}`);
  }
  return url.toString();
}

/* ---- Browse / Storage Backend types ---- */

export interface StorageSource {
  name: string;
  root: string;
}

export interface FileEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size: number | null;
  is_label: boolean;
}

export interface BrowseResponse {
  source: string;
  current_path: string;
  parent_path: string | null;
  entries: FileEntry[];
}

export async function getStorageSources(): Promise<StorageSource[]> {
  const resp = await fetch(apiUrl(`/browse/sources`));
  if (!resp.ok) throw new Error("Failed to fetch storage sources");
  return resp.json();
}

export async function browseDirectory(
  source: string,
  path?: string,
): Promise<BrowseResponse> {
  const params = new URLSearchParams({ source });
  if (path) params.set("path", path);
  const resp = await fetch(apiUrl(`/browse/list?${params}`));
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || "Failed to browse directory");
  }
  return resp.json();
}

export async function openLabelFromStorage(
  source: string,
  path: string,
): Promise<LabelUploadResponse> {
  const params = new URLSearchParams({ source, path });
  const resp = await fetch(apiUrl(`/browse/open?${params}`), {
    method: "POST",
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || "Failed to open label");
  }
  return resp.json();
}

/* ---- Data types ---- */

export interface StructureSummary {
  index: number;
  name: string;
  local_identifier: string | null;
  structure_type: string;
  record_count: number | null;
  field_count: number | null;
  dimensions: number[] | null;
}

export interface LabelUploadResponse {
  label_id: string;
  filename: string;
  structures: StructureSummary[];
}

export interface LabelMetadata {
  label_id: string;
  filename: string;
  xml_tree: XmlNode;
}

export interface XmlNode {
  tag: string;
  text?: string;
  attributes?: Record<string, string>;
  children?: XmlNode[];
}

export interface FieldInfo {
  name: string;
  field_number: number;
  data_type: string;
  unit: string | null;
  description: string | null;
}

export interface TableMetadata {
  label_id: string;
  structure_index: number;
  name: string;
  structure_type: string;
  record_count: number;
  fields: FieldInfo[];
}

export interface TableDataResponse {
  label_id: string;
  structure_index: number;
  total_records: number;
  offset: number;
  limit: number;
  columns: string[];
  data: unknown[][];
}

export interface PlotSpec {
  plot_type: "histogram" | "line" | "scatter" | "heatmap";
  x_column?: number;
  y_column?: number;
  color_column?: number;
  nbins?: number;
  title?: string;
  trace_color?: string;
}

export interface PlotDataResponse {
  plot_type: string;
  data: { traces: Plotly.Data[] };
  layout: Partial<Plotly.Layout>;
}

export interface ImageMetadata {
  label_id: string;
  structure_index: number;
  name: string;
  structure_type: string;
  dimensions: number[];
  axis_names?: string[];
  element_data_type: string;
  width: number;
  height: number;
  bands: number;
  band_axis: number | null;
}

export interface ImageStatistics {
  min: number;
  max: number;
  mean: number;
  std: number;
  shape: number[];
  dtype: string;
  percentiles: Record<string, number>;
  valid_count?: number;
}

export interface ImageRenderParams {
  colormap?: string;
  stretch?: string;
  vmin?: number | null;
  vmax?: number | null;
  percentile_low?: number;
  percentile_high?: number;
  band?: number | null;
}

export async function uploadLabel(
  labelFile: File,
  dataFiles?: File[],
): Promise<LabelUploadResponse> {
  const form = new FormData();
  form.append("label_file", labelFile);
  if (dataFiles) {
    for (const df of dataFiles) {
      form.append("data_files", df);
    }
  }
  const resp = await fetch(apiUrl(`/labels/upload`), {
    method: "POST",
    body: form,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || "Upload failed");
  }
  return resp.json();
}

export async function getLabels(): Promise<
  { label_id: string; filename: string }[]
> {
  const resp = await fetch(apiUrl(`/labels`));
  if (!resp.ok) throw new Error("Failed to fetch labels");
  return resp.json();
}

export async function getLabelDetail(
  labelId: string,
): Promise<LabelMetadata> {
  const resp = await fetch(apiUrl(`/labels/${labelSeg(labelId)}`));
  if (!resp.ok) throw new Error("Failed to fetch label");
  return resp.json();
}

export async function getStructures(
  labelId: string,
): Promise<StructureSummary[]> {
  const resp = await fetch(apiUrl(`/labels/${labelSeg(labelId)}/structures`));
  if (!resp.ok) throw new Error("Failed to fetch structures");
  return resp.json();
}

export async function getTableMetadata(
  labelId: string,
  structureIndex: number,
): Promise<TableMetadata> {
  const resp = await fetch(
    apiUrl(`/tables/${structureSeg(labelId, structureIndex)}`),
  );
  if (!resp.ok) throw new Error("Failed to fetch table metadata");
  return resp.json();
}

/** URL for the streamed CSV export of a table structure. */
export function tableCsvUrl(labelId: string, structureIndex: number): string {
  return apiUrl(`/tables/${structureSeg(labelId, structureIndex)}/data?format=csv`);
}

export async function getTableData(
  labelId: string,
  structureIndex: number,
  offset = 0,
  limit = 100,
): Promise<TableDataResponse> {
  const resp = await fetch(
    apiUrl(`/tables/${structureSeg(labelId, structureIndex)}/data?offset=${intSeg(offset, "offset")}&limit=${intSeg(limit, "limit")}`),
  );
  if (!resp.ok) throw new Error("Failed to fetch table data");
  return resp.json();
}

export async function getPlotData(
  labelId: string,
  structureIndex: number,
  spec: PlotSpec,
): Promise<PlotDataResponse> {
  const resp = await fetch(
    apiUrl(`/tables/${structureSeg(labelId, structureIndex)}/plot`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(spec),
    },
  );
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || "Plot generation failed");
  }
  return resp.json();
}

export async function getImageMetadata(
  labelId: string,
  structureIndex: number,
): Promise<ImageMetadata> {
  const resp = await fetch(
    apiUrl(`/images/${structureSeg(labelId, structureIndex)}`),
  );
  if (!resp.ok) throw new Error("Failed to fetch image metadata");
  return resp.json();
}

export async function getImageStatistics(
  labelId: string,
  structureIndex: number,
  band = 0,
): Promise<ImageStatistics> {
  const resp = await fetch(
    apiUrl(`/images/${structureSeg(labelId, structureIndex)}/statistics?band=${intSeg(band, "band")}`),
  );
  if (!resp.ok) throw new Error("Failed to fetch image statistics");
  return resp.json();
}

export async function renderImage(
  labelId: string,
  structureIndex: number,
  params: ImageRenderParams,
): Promise<Blob> {
  const resp = await fetch(
    apiUrl(`/images/${structureSeg(labelId, structureIndex)}/render`),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    },
  );
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || "Image render failed");
  }
  return resp.blob();
}

export interface PixelValue {
  x: number;
  y: number;
  band: number;
  value: number | null;
}

export async function getPixelValue(
  labelId: string,
  structureIndex: number,
  x: number,
  y: number,
  band = 0,
): Promise<PixelValue> {
  const params = new URLSearchParams({ x: String(x), y: String(y), band: String(band) });
  const resp = await fetch(apiUrl(`/images/${structureSeg(labelId, structureIndex)}/pixel?${params}`));
  if (!resp.ok) throw new Error("Failed to fetch pixel value");
  return resp.json();
}
