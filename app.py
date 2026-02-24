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
    Fetch drive times (in seconds) between all address pairs using the
    Google Maps Distance Matrix API.  Returns a square matrix where
    matrix[i][j] is the travel time from addresses[i] to addresses[j].
    """
    gmaps = get_gmaps_client()
    n = len(addresses)
    matrix = [[0] * n for _ in range(n)]

    # The API accepts up to 10 origins × 10 destinations per call.
    # We chunk to stay within that limit.
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
                    duration_seconds = element["duration"]["value"]
                    matrix[i_start + i_offset][j_start + j_offset] = (
                        duration_seconds
                    )

    return matrix


def solve_tsp(distance_matrix: list[list[int]]) -> tuple[list[int], int]:
    """
    Solve the Traveling Salesman Problem with OR-Tools.
    Node 0 is the depot (start location).
    Returns (ordered list of node indices, total travel time in seconds).
    """
    n = len(distance_matrix)

    if n == 1:
        return [0], 0

    manager = pywrapcp.RoutingIndexManager(n, 1, 0)
    routing = pywrapcp.RoutingModel(manager)

    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return distance_matrix[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_params.time_limit.seconds = 10

    solution = routing.SolveWithParameters(search_params)

    if not solution:
        raise RuntimeError("OR-Tools could not find a valid route solution.")

    route = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        route.append(manager.IndexToNode(index))
        index = solution.Value(routing.NextVar(index))

    total_seconds = solution.ObjectiveValue()
    return route, total_seconds


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

    start_location = (data.get("start_location") or "").strip()
    job_locations = data.get("job_locations", [])

    # ── Validation ──────────────────────────────────────────────────────────
    if not start_location:
        return jsonify({"error": "start_location is required."}), 400

    if not isinstance(job_locations, list):
        return jsonify({"error": "job_locations must be an array."}), 400

    job_locations = [a.strip() for a in job_locations if a.strip()]

    if not job_locations:
        return jsonify({"error": "At least one job location is required."}), 400

    if len(job_locations) > 24:
        return jsonify(
            {"error": "Maximum 24 job locations are supported per request."}
        ), 400

    # ── Build full address list (depot first) ────────────────────────────────
    all_addresses = [start_location] + job_locations

    try:
        logger.info(
            "Building distance matrix for %d addresses.", len(all_addresses)
        )
        distance_matrix = build_distance_matrix(all_addresses)

        logger.info("Running TSP solver.")
        route_indices, total_seconds = solve_tsp(distance_matrix)

        # Map indices back to human-readable addresses
        ordered_stops = [all_addresses[i] for i in route_indices]
        total_minutes = round(total_seconds / 60)

        return jsonify(
            {
                "optimized_route": ordered_stops,
                "total_drive_time_minutes": total_minutes,
                "stop_count": len(job_locations),
            }
        )

    except ValueError as exc:
        logger.warning("Validation/address error: %s", exc)
        return jsonify({"error": str(exc)}), 422

    except googlemaps.exceptions.ApiError as exc:
        logger.error("Google Maps API error: %s", exc)
        return jsonify(
            {"error": f"Google Maps API error: {exc}"}
        ), 502

    except googlemaps.exceptions.TransportError as exc:
        logger.error("Google Maps transport error: %s", exc)
        return jsonify(
            {"error": "Could not reach Google Maps API. Check your network."}
        ), 503

    except RuntimeError as exc:
        logger.error("Solver error: %s", exc)
        return jsonify({"error": str(exc)}), 500

    except Exception as exc:
        logger.exception("Unexpected error during optimization.")
        return jsonify(
            {"error": "An unexpected server error occurred."}
        ), 500


if __name__ == "__main__":
    if not GOOGLE_MAPS_API_KEY:
        logger.warning(
            "GOOGLE_MAPS_API_KEY is not set. "
            "Set it before making optimization requests."
        )
    port = int(os.environ.get("PORT", 8080))
    app.run(debug=False, host="0.0.0.0", port=port)
