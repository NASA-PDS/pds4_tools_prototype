# PDS4 Viewer

A modern web application for viewing, exploring, and plotting NASA PDS4 data products. Built with FastAPI (Python) and React (TypeScript), styled to NASA's Horizon Design System.

## Features

- **Table Data Viewer**: Display PDS4 table data (Character, Binary, Delimited) with sorting, filtering, and virtual scrolling
- **Interactive Plotting**: Histogram, line, scatter, and heatmap plots with Plotly.js
- **Image Viewer**: 2D image display with colormap controls, brightness/contrast stretching, and RGB composite (coming soon)
- **Label Explorer**: Navigate PDS4 XML label metadata in a tree view
- **NASA HDS Theme**: Dark-themed UI following NASA's Horizon Design System

## Architecture

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+ / FastAPI |
| Frontend | React 18 / TypeScript / Vite |
| Plotting | Plotly.js |
| Styling | Tailwind CSS (NASA HDS tokens) |
| Testing | pytest / Vitest / Playwright |

## Quick Start

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
```

CI, Docker and the devcontainer install from the hashed lock files `requirements.lock`
(runtime + S3) and `requirements-dev.lock` (adds dev tools). After changing dependencies
in `pyproject.toml`, regenerate them from `backend/`:

```bash
uv pip compile pyproject.toml build-reqs.in --extra s3 --universal --python-version 3.11 --generate-hashes -o requirements.lock
uv pip compile pyproject.toml build-reqs.in --extra s3 --extra dev --universal --python-version 3.11 --generate-hashes -o requirements-dev.lock
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend dev server runs on `http://localhost:5173` and proxies API requests to `http://localhost:8000`.

## Usage

1. Open the app in your browser
2. Browse a configured source and open a PDS4 label file (`.xml` or `.lblx`), or upload one if the server has `PDS_ENABLE_UPLOAD` turned on
3. Browse the data structures described in the label
4. View table data, create plots, or explore images

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PDS_LOCAL_ROOT` | repo `test_data/` | Local directory exposed as the `local` browse source (access is confined to it) |
| `PDS_S3_BUCKET`, `PDS_S3_PREFIX`, `PDS_S3_REGION` | unset | Optional `s3` source. Data is read in place with ranged GETs. Credentials come from the standard AWS chain. Requires `pip install ".[s3]"` |
| `PDS_CACHE_DIR` | `$TMPDIR/pds4_viewer` | Label records and uploads. Share it across workers and replicas |
| `PDS_CACHE_TTL_SECONDS` | `86400` | Idle labels and uploads expire after this |
| `PDS_DATA_CACHE_MB` | `512` | Per-process cache of decoded images and tables |
| `PDS_PLOT_MAX_POINTS` | `50000` | Line and scatter plots are decimated above this |
| `PDS_ENABLE_UPLOAD` | `false` | Allow users to upload their own label and data files. Off by default, so users can only open labels from the configured sources above. When off, the upload API returns 403 and the UI hides the Upload tab |
| `PDS_MAX_UPLOAD_MB` | `1024` | Per-file upload limit | (only when uploads are enabled)
| `PDS_CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed origins |
| `PDS_STATIC_DIR` | unset | Serve the built frontend from the API (single-container deploys) |

## Try it without a local setup

- **GitHub Codespaces** (works from a browser or iPad): **Code → Codespaces → Create codespace**.
  Dependencies install and both servers start automatically. Open the forwarded port 5173.
- **Docker**: `docker build -t pds4-viewer . && docker run -p 8000:8000 pds4-viewer`, then open http://localhost:8000.
  CI builds this image and smoke-tests it on every push.

### Smoke-testing a deployment

`scripts/smoke_test.py` checks that a running viewer serves the UI, opens and renders products,
reads tables, and rejects paths outside its root. Use it on a container, a Codespace, or production:

```bash
python scripts/smoke_test.py http://localhost:8000
python scripts/smoke_test.py https://<prod-host> --label <dir>/<product>.xml --table-label <dir>/<table>.xml
```

## Testing

### Backend Tests
```bash
cd backend
pytest -x -q
```

### Frontend Tests
```bash
cd frontend
npm test
```

### E2E Tests
```bash
cd frontend
npx playwright install chromium
npx playwright test            # starts the backend (test_data) and Vite automatically
```

### Requirements traceability
Tests are tagged with requirement and bug keys (`REQ-xx`, `BUG-xx`) that map to GitHub
issues. Every run writes JUnit reports carrying those keys, and CI publishes a traceability
matrix. See [traceability/README.md](traceability/README.md), which also covers the
TestRail upload.

## License

Apache-2.0. See [LICENSE.md](LICENSE.md).
