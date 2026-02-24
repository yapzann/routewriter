# RouteWriter – HVAC Route Optimizer

Optimizes the daily drive order for HVAC service contractors using the
Google Maps Distance Matrix API and Google OR-Tools TSP solver.

---

## Prerequisites

- Python 3.11+
- A Google Cloud project with billing enabled

---

## 1 · Get a Google Maps API Key

1. Go to [console.cloud.google.com](https://console.cloud.google.com/).
2. Create a new project (or select an existing one).
3. Open **APIs & Services → Library** and enable **both** of these APIs:
   - **Distance Matrix API**
   - **Geocoding API**
4. Open **APIs & Services → Credentials** and click **Create Credentials →
   API key**.
5. Copy the key – you will need it in step 3 below.

> **Cost note:** The Distance Matrix API is billed per element (origin ×
> destination pair). For a 10-stop route that is 110 elements per request.
> Google provides a free monthly credit of $200, which covers thousands of
> typical daily schedules.

---

## 2 · Install dependencies

```bash
pip install -r requirements.txt
```

> It is recommended to use a virtual environment:
> ```bash
> python -m venv .venv
> source .venv/bin/activate   # Windows: .venv\Scripts\activate
> pip install -r requirements.txt
> ```

---

## 3 · Set your API key

Export the key as an environment variable before starting the server:

```bash
# macOS / Linux
export GOOGLE_MAPS_API_KEY="YOUR_API_KEY_HERE"

# Windows (Command Prompt)
set GOOGLE_MAPS_API_KEY=YOUR_API_KEY_HERE

# Windows (PowerShell)
$env:GOOGLE_MAPS_API_KEY="YOUR_API_KEY_HERE"
```

---

## 4 · Run the app

```bash
python app.py
```

The Flask server starts on **http://localhost:8080**.

Open **http://localhost:8080** in your browser. Flask serves both the UI and
the API from the same process.

---

## Usage

1. Enter your **starting address** (warehouse, home base, etc.).
2. Paste your **job addresses**, one per line (up to 24 per run).
3. Click **Optimize Route**.
4. The numbered stop list and total estimated drive time appear below.

---

## API reference

### `POST /optimize`

**Request body (JSON)**

```json
{
  "start_location": "123 Main St, Austin, TX 78701",
  "job_locations": [
    "456 Oak Ave, Austin, TX 78702",
    "789 Pine Rd, Austin, TX 78703"
  ]
}
```

**Success response (200)**

```json
{
  "optimized_route": [
    "123 Main St, Austin, TX 78701",
    "789 Pine Rd, Austin, TX 78703",
    "456 Oak Ave, Austin, TX 78702"
  ],
  "total_drive_time_minutes": 34,
  "stop_count": 2
}
```

**Error response (4xx / 5xx)**

```json
{
  "error": "Human-readable description of what went wrong."
}
```

### `GET /health`

Returns `{"status": "ok"}` – useful for uptime monitoring.

---

## Project structure

```
routewriter/
├── app.py           # Flask backend (TSP solver + Maps API)
├── index.html       # Single-page frontend
├── requirements.txt # Python dependencies
└── README.md        # This file
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `GOOGLE_MAPS_API_KEY is not set` warning | Export the variable before running `python app.py` |
| `REQUEST_DENIED` from Maps API | Confirm both Distance Matrix and Geocoding APIs are enabled in your GCP project |
| Address not found / `NOT_FOUND` | Use full street addresses with city, state, and ZIP code |
| `Could not reach the server` in the UI | Make sure `python app.py` is running and no firewall blocks port 5000 |
| `ortools` install fails | Requires Python 3.9–3.12 and a 64-bit OS; upgrade pip first with `pip install --upgrade pip` |
