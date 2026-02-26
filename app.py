import os
import logging
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import googlemaps
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")


def get_gmaps_client():
    if not GOOGLE_MAPS_API_KEY:
        raise ValueError(
            "GOOGLE_MAPS_API_KEY environment variable is not set."
        )
    return googlemaps.Client(key=GOOGLE_MAPS_API_KEY)


def build_distance_matrix(addresses: list[str]) -> list[list[int]]:
    """
    Fetch drive times (seconds) between all address pairs via the Google Maps
    Distance Matrix API.  Returns a square matrix where matrix[i][j] is the
    travel time from addresses[i] to addresses[j].
    """
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
                        addr_to = addresses[j_start + j_offset]
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
    """
    Solve the Vehicle Routing Problem with OR-Tools.

    Node layout in the distance matrix:
      [0 .. n_technicians-1]          → technician depot nodes
      [n_technicians .. n_tech+n_jobs-1] → job nodes

    Each vehicle (technician) starts and ends at its own depot (round-trip).
    A count dimension penalises uneven job distribution across technicians.

    Returns a list of (route, travel_seconds) tuples, one per technician.
    route is an ordered list of node indices (depot → jobs → depot,
    but we strip the trailing depot return in the result).
    """
    n = n_technicians + n_jobs
    starts = list(range(n_technicians))
    ends = list(range(n_technicians))  # round-trip

    manager = pywrapcp.RoutingIndexManager(n, n_technicians, starts, ends)
    routing = pywrapcp.RoutingModel(manager)

    # ── Arc cost: travel time ────────────────────────────────────────────────
    def time_callback(from_index, to_index):
        return distance_matrix[manager.IndexToNode(from_index)][
            manager.IndexToNode(to_index)
        ]

    transit_idx = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    # ── Count dimension: penalise imbalanced job counts ──────────────────────
    # Each node visited costs 1 unit; depot nodes cost 0 (handled by
    # disjunction / natural exclusion of depot-to-depot arcs).
    routing.AddConstantDimension(
        1,      # increment per arc traversal
        n,      # safe upper bound (n_jobs arcs + 1 return arc per vehicle)
        True,   # fix start cumul to zero
        "count",
    )
    count_dim = routing.GetDimensionOrDie("count")
    count_dim.SetGlobalSpanCostCoefficient(100)

    # ── Search parameters ────────────────────────────────────────────────────
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

    # ── Extract routes ───────────────────────────────────────────────────────
    results = []
    for vehicle in range(n_technicians):
        route_nodes: list[int] = []
        index = routing.Start(vehicle)
        route_time = 0

        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            route_nodes.append(node)
            next_index = solution.Value(routing.NextVar(index))
            route_time += distance_matrix[node][manager.IndexToNode(next_index)]
            index = next_index

        # Strip the depot node at position 0 (technician's own start)
        job_nodes = [n for n in route_nodes if n >= n_technicians]
        results.append((job_nodes, route_time))

    return results


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/optimize", methods=["POST"])
def optimize():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON."}), 400

    technicians = data.get("technicians", [])
    jobs = data.get("jobs", [])

    # ── Validation ────────────────────────────────────────────────────────────
    if not isinstance(technicians, list) or not technicians:
        return jsonify({"error": "At least one technician is required."}), 400

    if not isinstance(jobs, list) or not jobs:
        return jsonify({"error": "At least one job is required."}), 400

    if len(technicians) > 10:
        return jsonify({"error": "Maximum 10 technicians per request."}), 400

    if len(jobs) > 24:
        return jsonify({"error": "Maximum 24 jobs per request."}), 400

    # Normalise technicians
    cleaned_techs = []
    for i, t in enumerate(technicians):
        name = str(t.get("name", "") or "").strip() or f"Technician {i + 1}"
        start = str(t.get("start_location", "") or "").strip()
        if not start:
            return jsonify(
                {"error": f"Technician '{name}' is missing a start location."}
            ), 400
        cleaned_techs.append({"name": name, "start_location": start})

    # Normalise jobs
    cleaned_jobs = []
    for i, j in enumerate(jobs):
        job_name = str(j.get("name", "") or "").strip() or f"Job {i + 1}"
        location = str(j.get("location", "") or "").strip()
        if not location:
            return jsonify(
                {"error": f"Job '{job_name}' is missing a location."}
            ), 400
        cleaned_jobs.append({"name": job_name, "location": location})

    # ── Build address list: technician depots first, then job locations ───────
    tech_addresses = [t["start_location"] for t in cleaned_techs]
    job_addresses = [j["location"] for j in cleaned_jobs]
    all_addresses = tech_addresses + job_addresses

    n_technicians = len(cleaned_techs)
    n_jobs = len(cleaned_jobs)

    try:
        logger.info(
            "Building distance matrix for %d nodes (%d techs + %d jobs).",
            len(all_addresses), n_technicians, n_jobs,
        )
        distance_matrix = build_distance_matrix(all_addresses)

        logger.info("Running VRP solver (%d vehicles, %d jobs).", n_technicians, n_jobs)
        vrp_results = solve_vrp(distance_matrix, n_technicians, n_jobs)

        # ── Build response ────────────────────────────────────────────────────
        assignments = []
        total_seconds = 0

        for vehicle_idx, (job_nodes, travel_seconds) in enumerate(vrp_results):
            tech = cleaned_techs[vehicle_idx]
            stops = []
            for node in job_nodes:
                job_idx = node - n_technicians
                stops.append({
                    "job_name": cleaned_jobs[job_idx]["name"],
                    "location": cleaned_jobs[job_idx]["location"],
                })

            total_seconds += travel_seconds
            assignments.append({
                "technician": tech["name"],
                "start_location": tech["start_location"],
                "stops": stops,
                "drive_time_minutes": round(travel_seconds / 60),
            })

        return jsonify({
            "assignments": assignments,
            "total_drive_time_minutes": round(total_seconds / 60),
            "total_jobs": n_jobs,
        })

    except ValueError as exc:
        logger.warning("Validation/address error: %s", exc)
        return jsonify({"error": str(exc)}), 422

    except googlemaps.exceptions.ApiError as exc:
        logger.error("Google Maps API error: %s", exc)
        return jsonify({"error": f"Google Maps API error: {exc}"}), 502

    except googlemaps.exceptions.TransportError:
        logger.error("Google Maps transport error.")
        return jsonify(
            {"error": "Could not reach Google Maps API. Check your network."}
        ), 503

    except RuntimeError as exc:
        logger.error("Solver error: %s", exc)
        return jsonify({"error": str(exc)}), 500

    except Exception:
        logger.exception("Unexpected error during optimization.")
        return jsonify({"error": "An unexpected server error occurred."}), 500


if __name__ == "__main__":
    if not GOOGLE_MAPS_API_KEY:
        logger.warning(
            "GOOGLE_MAPS_API_KEY is not set. "
            "Set it before making optimization requests."
        )
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=False, host="0.0.0.0", port=port)
