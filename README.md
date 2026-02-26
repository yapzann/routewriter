# RouteWriter – HVAC Route Optimizer

Optimizes daily routes for **entire HVAC service teams**. A dispatcher enters
the technicians (with their starting locations) and the day's jobs (with
addresses). The solver assigns jobs to technicians and optimizes each
individual route — minimizing total drive time and distributing work evenly
across the team.

**Algorithm:** Google OR-Tools Vehicle Routing Problem (VRP) solver +
Google Maps Distance Matrix API.

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
5. Copy the key — you will need it in step 3 below.

> **Cost note:** The Distance Matrix API is billed per element (origin ×
> destination pair). A team of 3 technicians and 10 jobs = 169 elements per
> request. Google provides a $200 free monthly credit.

---

## 2 · Install dependencies

```bash
pip install -r requirements.txt
```

> Recommended: use a virtual environment first:
> ```bash
> python -m venv .venv
> source .venv/bin/activate   # Windows: .venv\Scripts\activate
> pip install -r requirements.txt
> ```

---

## 3 · Set your API key

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

The Flask server starts on **http://localhost:8080**. Flask serves both the
UI and the API from the same process.

---

## Usage

1. **Add technicians** — enter each tech's name and their starting address
   (home, warehouse, etc.). Click **+ Add Technician** for more rows.
2. **Add jobs** — enter each job's name (optional) and location. Click
   **+ Add Job** for more rows.
3. Click **Optimize Routes**.
4. Results appear as one card per technician showing their assigned stops in
   order and estimated drive time. A summary shows the total drive time
   across the whole team.

**Limits:** up to 10 technicians and 24 jobs per request.

---

## API reference

### `POST /optimize`

**Request body (JSON)**

```json
{
  "technicians": [
    {"name": "Alice", "start_location": "123 Main St, Austin, TX 78701"},
    {"name": "Bob",   "start_location": "456 Oak Ave, Austin, TX 78702"}
  ],
  "jobs": [
    {"name": "AC Repair",    "location": "789 Pine Rd, Austin, TX 78703"},
    {"name": "HVAC Install", "location": "321 Elm St, Austin, TX 78704"}
  ]
}
```

`name` fields are optional — default labels are used if omitted.

**Success response (200)**

```json
{
  "assignments": [
    {
      "technician": "Alice",
      "start_location": "123 Main St, Austin, TX 78701",
      "stops": [
        {"job_name": "AC Repair", "location": "789 Pine Rd, Austin, TX 78703"}
      ],
      "drive_time_minutes": 18
    },
    {
      "technician": "Bob",
      "start_location": "456 Oak Ave, Austin, TX 78702",
      "stops": [
        {"job_name": "HVAC Install", "location": "321 Elm St, Austin, TX 78704"}
      ],
      "drive_time_minutes": 12
    }
  ],
  "total_drive_time_minutes": 30,
  "total_jobs": 2
}
```

**Error response (4xx / 5xx)**

```json
{"error": "Human-readable description of what went wrong."}
```

### `GET /health`

Returns `{"status": "ok"}` — useful for uptime monitoring.

---

## Project structure

```
routewriter/
├── app.py           # Flask backend (VRP solver + Maps API)
├── index.html       # Single-page frontend
├── requirements.txt # Python dependencies
└── README.md        # This file
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `GOOGLE_MAPS_API_KEY is not set` warning | Export the variable before running `python app.py` |
| `REQUEST_DENIED` from Maps API | Confirm both Distance Matrix and Geocoding APIs are enabled |
| Address not found / `NOT_FOUND` | Use full street addresses with city, state, and ZIP |
| `Could not reach the server` in the UI | Make sure `python app.py` is running and nothing blocks port 8080 |
| `ortools` install fails | Requires Python 3.9–3.12 and a 64-bit OS; run `pip install --upgrade pip` first |
