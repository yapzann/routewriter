import io
import os
import logging
from datetime import date

from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
import googlemaps
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

from models import db, Customer, Quote
from quote_pdf import generate_quote_pdf
from email_service import send_reminders_bulk

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Render's PostgreSQL URLs start with "postgres://" but SQLAlchemy needs "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL:
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
else:
    # Fallback to local SQLite for local development without a DB set up
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///routewriter_dev.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

with app.app_context():
    db.create_all()

# ── Google Maps ───────────────────────────────────────────────────────────────
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")


def get_gmaps_client():
    if not GOOGLE_MAPS_API_KEY:
        raise ValueError(
            "GOOGLE_MAPS_API_KEY environment variable is not set."
        )
    return googlemaps.Client(key=GOOGLE_MAPS_API_KEY)


# ── VRP helpers ───────────────────────────────────────────────────────────────
def build_distance_matrix(addresses: list[str]) -> list[list[int]]:
    gmaps = get_gmaps_client()
    n = len(addresses)
    matrix = [[0] * n for _ in range(n)]

    chunk_size = 10
    for i_start in range(0, n, chunk_size):
        origins = addresses[i_start: i_start + chunk_size]
        for j_start in range(0, n, chunk_size):
            destinations = addresses[j_start: j_start + chunk_size]

            response = gmaps.distance_matrix(
                origins=origins,
                destinations=destinations,
                mode="driving",
                units="imperial",
            )

            for i_offset, row in enumerate(response["rows"]):
                for j_offset, element in enumerate(row["elements"]):
                    if element["status"] != "OK":
                        addr_from = addresses[i_start + i_offset]
                        addr_to   = addresses[j_start + j_offset]
                        raise ValueError(
                            f"Could not get drive time between "
                            f"'{addr_from}' and '{addr_to}'. "
                            f"Status: {element['status']}"
                        )
                    matrix[i_start + i_offset][j_start + j_offset] = (
                        element["duration"]["value"]
                    )

    return matrix


def solve_vrp(
    distance_matrix: list[list[int]],
    n_technicians: int,
    n_jobs: int,
) -> list[tuple[list[int], int]]:
    n      = n_technicians + n_jobs
    starts = list(range(n_technicians))
    ends   = list(range(n_technicians))

    manager = pywrapcp.RoutingIndexManager(n, n_technicians, starts, ends)
    routing = pywrapcp.RoutingModel(manager)

    def time_callback(from_index, to_index):
        return distance_matrix[manager.IndexToNode(from_index)][
            manager.IndexToNode(to_index)
        ]

    transit_idx = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    routing.AddConstantDimension(1, n, True, "count")
    count_dim = routing.GetDimensionOrDie("count")
    count_dim.SetGlobalSpanCostCoefficient(100)

    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_params.time_limit.seconds = 15

    solution = routing.SolveWithParameters(search_params)
    if not solution:
        raise RuntimeError("OR-Tools could not find a valid route solution.")

    results = []
    for vehicle in range(n_technicians):
        route_nodes: list[int] = []
        index      = routing.Start(vehicle)
        route_time = 0

        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            route_nodes.append(node)
            next_index  = solution.Value(routing.NextVar(index))
            route_time += distance_matrix[node][manager.IndexToNode(next_index)]
            index       = next_index

        job_nodes = [n for n in route_nodes if n >= n_technicians]
        results.append((job_nodes, route_time))

    return results


# ── Static / index ────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ── Route optimiser ───────────────────────────────────────────────────────────
@app.route("/optimize", methods=["POST"])
def optimize():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON."}), 400

    technicians = data.get("technicians", [])
    jobs        = data.get("jobs", [])

    if not isinstance(technicians, list) or not technicians:
        return jsonify({"error": "At least one technician is required."}), 400
    if not isinstance(jobs, list) or not jobs:
        return jsonify({"error": "At least one job is required."}), 400
    if len(technicians) > 10:
        return jsonify({"error": "Maximum 10 technicians per request."}), 400
    if len(jobs) > 24:
        return jsonify({"error": "Maximum 24 jobs per request."}), 400

    cleaned_techs = []
    for i, t in enumerate(technicians):
        name  = str(t.get("name", "") or "").strip() or f"Technician {i + 1}"
        start = str(t.get("start_location", "") or "").strip()
        if not start:
            return jsonify({"error": f"Technician '{name}' is missing a start location."}), 400
        cleaned_techs.append({"name": name, "start_location": start})

    cleaned_jobs = []
    for i, j in enumerate(jobs):
        job_name = str(j.get("name", "") or "").strip() or f"Job {i + 1}"
        location = str(j.get("location", "") or "").strip()
        if not location:
            return jsonify({"error": f"Job '{job_name}' is missing a location."}), 400
        cleaned_jobs.append({"name": job_name, "location": location})

    tech_addresses = [t["start_location"] for t in cleaned_techs]
    job_addresses  = [j["location"]        for j in cleaned_jobs]
    all_addresses  = tech_addresses + job_addresses
    n_technicians  = len(cleaned_techs)
    n_jobs         = len(cleaned_jobs)

    try:
        logger.info(
            "Building distance matrix for %d nodes (%d techs + %d jobs).",
            len(all_addresses), n_technicians, n_jobs,
        )
        distance_matrix = build_distance_matrix(all_addresses)

        logger.info("Running VRP solver (%d vehicles, %d jobs).", n_technicians, n_jobs)
        vrp_results = solve_vrp(distance_matrix, n_technicians, n_jobs)

        assignments  = []
        total_seconds = 0

        for vehicle_idx, (job_nodes, travel_seconds) in enumerate(vrp_results):
            tech  = cleaned_techs[vehicle_idx]
            stops = []
            for node in job_nodes:
                job_idx = node - n_technicians
                stops.append({
                    "job_name": cleaned_jobs[job_idx]["name"],
                    "location": cleaned_jobs[job_idx]["location"],
                })

            total_seconds += travel_seconds
            assignments.append({
                "technician":        tech["name"],
                "start_location":    tech["start_location"],
                "stops":             stops,
                "drive_time_minutes": round(travel_seconds / 60),
            })

        return jsonify({
            "assignments":            assignments,
            "total_drive_time_minutes": round(total_seconds / 60),
            "total_jobs":             n_jobs,
        })

    except ValueError as exc:
        logger.warning("Validation/address error: %s", exc)
        return jsonify({"error": str(exc)}), 422
    except googlemaps.exceptions.ApiError as exc:
        logger.error("Google Maps API error: %s", exc)
        return jsonify({"error": f"Google Maps API error: {exc}"}), 502
    except googlemaps.exceptions.TransportError:
        logger.error("Google Maps transport error.")
        return jsonify({"error": "Could not reach Google Maps API. Check your network."}), 503
    except RuntimeError as exc:
        logger.error("Solver error: %s", exc)
        return jsonify({"error": str(exc)}), 500
    except Exception:
        logger.exception("Unexpected error during optimization.")
        return jsonify({"error": "An unexpected server error occurred."}), 500


# ── Quotes ────────────────────────────────────────────────────────────────────
@app.route("/quotes", methods=["GET"])
def list_quotes():
    quotes = Quote.query.order_by(Quote.created_at.desc()).all()
    return jsonify([q.to_dict() for q in quotes])


@app.route("/quotes", methods=["POST"])
def create_quote():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON."}), 400

    customer_name = str(data.get("customer_name", "") or "").strip()
    if not customer_name:
        return jsonify({"error": "customer_name is required."}), 400

    line_items = data.get("line_items", [])
    if not isinstance(line_items, list) or not line_items:
        return jsonify({"error": "At least one line item is required."}), 400

    # Validate + calculate
    cleaned_items = []
    subtotal = 0.0
    for i, item in enumerate(line_items):
        desc = str(item.get("desc", "") or "").strip() or f"Item {i + 1}"
        try:
            qty        = float(item.get("qty", 1))
            unit_price = float(item.get("unit_price", 0))
        except (TypeError, ValueError):
            return jsonify({"error": f"Invalid qty or unit_price in item '{desc}'."}), 400
        line_total = qty * unit_price
        subtotal  += line_total
        cleaned_items.append({"desc": desc, "qty": qty, "unit_price": unit_price})

    try:
        tax_rate = float(data.get("tax_rate", 0) or 0)
    except (TypeError, ValueError):
        tax_rate = 0.0

    total = subtotal + subtotal * tax_rate

    quote = Quote(
        customer_name  = customer_name,
        customer_email = str(data.get("customer_email", "") or "").strip() or None,
        job_type       = str(data.get("job_type", "") or "").strip() or None,
        line_items     = cleaned_items,
        tax_rate       = tax_rate,
        subtotal       = round(subtotal, 2),
        total          = round(total, 2),
        notes          = str(data.get("notes", "") or "").strip() or None,
    )
    db.session.add(quote)
    db.session.commit()

    # Generate PDF and return as download
    try:
        pdf_bytes = generate_quote_pdf(quote)
    except Exception:
        logger.exception("PDF generation failed for quote %s", quote.id)
        return jsonify({"error": "Quote saved but PDF generation failed."}), 500

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"quote-{quote.id}.pdf",
    )


# ── Customers ─────────────────────────────────────────────────────────────────
@app.route("/customers", methods=["GET"])
def list_customers():
    customers = Customer.query.order_by(Customer.name).all()
    return jsonify([c.to_dict() for c in customers])


@app.route("/customers", methods=["POST"])
def create_customer():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON."}), 400

    name = str(data.get("name", "") or "").strip()
    if not name:
        return jsonify({"error": "name is required."}), 400

    last_service_date = None
    if data.get("last_service_date"):
        try:
            last_service_date = date.fromisoformat(data["last_service_date"])
        except ValueError:
            return jsonify({"error": "last_service_date must be YYYY-MM-DD."}), 400

    customer = Customer(
        name              = name,
        email             = str(data.get("email", "") or "").strip() or None,
        phone             = str(data.get("phone", "") or "").strip() or None,
        address           = str(data.get("address", "") or "").strip() or None,
        last_service_date = last_service_date,
        notes             = str(data.get("notes", "") or "").strip() or None,
    )
    db.session.add(customer)
    db.session.commit()
    return jsonify(customer.to_dict()), 201


@app.route("/customers/<int:customer_id>", methods=["PUT"])
def update_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    data = request.get_json(silent=True) or {}

    if "name" in data:
        name = str(data["name"] or "").strip()
        if not name:
            return jsonify({"error": "name cannot be empty."}), 400
        customer.name = name

    for field in ("email", "phone", "address", "notes"):
        if field in data:
            setattr(customer, field, str(data[field] or "").strip() or None)

    if "last_service_date" in data:
        if data["last_service_date"]:
            try:
                customer.last_service_date = date.fromisoformat(data["last_service_date"])
            except ValueError:
                return jsonify({"error": "last_service_date must be YYYY-MM-DD."}), 400
        else:
            customer.last_service_date = None

    db.session.commit()
    return jsonify(customer.to_dict())


@app.route("/customers/<int:customer_id>", methods=["DELETE"])
def delete_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    db.session.delete(customer)
    db.session.commit()
    return jsonify({"deleted": customer_id})


# ── Reminders ─────────────────────────────────────────────────────────────────
@app.route("/reminders/due", methods=["GET"])
def reminders_due():
    customers = Customer.query.all()
    due = [c.to_dict() for c in customers if c.is_due()]
    return jsonify(due)


@app.route("/reminders/send", methods=["POST"])
def send_reminders():
    customers = Customer.query.all()
    due       = [c for c in customers if c.is_due()]

    if not due:
        return jsonify({"message": "No customers are currently due.", "sent": 0})

    try:
        result = send_reminders_bulk(due)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception:
        logger.exception("Unexpected error sending reminders.")
        return jsonify({"error": "An unexpected error occurred while sending reminders."}), 500

    return jsonify({
        "message": f"Done. {result['sent']} reminder(s) sent.",
        **result,
    })


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not GOOGLE_MAPS_API_KEY:
        logger.warning(
            "GOOGLE_MAPS_API_KEY is not set. "
            "Set it before making optimization requests."
        )
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=False, host="0.0.0.0", port=port)
