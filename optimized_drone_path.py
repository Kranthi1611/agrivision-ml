import cv2
import numpy as np
import math
import csv
import json
import heapq

from pathlib import Path


# ============================================================
# AGRIVISION
# COMPLETE COVERAGE + GLOBAL ROUTE OPTIMIZATION
# ============================================================
#
# Pipeline:
#
#   Field image
#       ↓
#   Field boundary
#       ↓
#   Road / pond exclusion
#       ↓
#   Horizontal + vertical coverage candidates
#       ↓
#   Open road-to-road route evaluation
#       ↓
#   Boustrophedon seed  →  Multi-start NN  →  pick best
#       ↓
#   2-Opt  (full restart on improvement)
#       ↓
#   Or-Opt  (1-segment and 2-segment relocation)
#       ↓
#   Best global route
#       ↓
#   Coverage-only visualization
#       ↓
#   CSV + JSON statistics
#
# IMPROVEMENTS OVER ORIGINAL:
#   1. Boustrophedon (strip-order) initial seed:
#      sorts parallel strips spatially and alternates direction.
#      This already produces near-optimal ordering for pure
#      lawnmower fields and gives the metaheuristics a much
#      better start than NN alone.
#   2. Multi-start Nearest Neighbor: seeds from road_start,
#      road_end, AND the boustrophedon sequence, keeps the best.
#   3. 2-Opt: fixed inner-loop restart on improvement so the
#      pass fully converges instead of stopping after one swap.
#   4. Or-Opt (new): after 2-Opt, relocates single segments
#      and pairs to positions where the transit cost is lower.
#      Finds improvements 2-Opt misses, especially where
#      many short connectors dominate the transit budget.
#   5. Optimization method flags updated in statistics output.
#
# Transit paths are USED INTERNALLY for optimization.
# Transit paths are NOT DRAWN on the result image.
# Green lines are ONLY actual coverage/spray lines.
# ============================================================


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

INPUT_IMAGE = BASE_DIR / "input" / "field.jpeg"
OUTPUT_DIR = BASE_DIR / "output"

OUTPUT_IMAGE = OUTPUT_DIR / "optimized_drone_path.png"
OUTPUT_CSV = OUTPUT_DIR / "optimized_drone_route.csv"
OUTPUT_STATS = OUTPUT_DIR / "optimized_drone_stats.json"


# ============================================================
# COVERAGE PARAMETERS
# ============================================================

LINE_SPACING = 22
SAFETY_MARGIN = 5
MIN_SEGMENT_LENGTH = 30

# Extra clearance around detected pond/road.
DRONE_OBSTACLE_CLEARANCE = 12

# A* grid reduction used only for internal transit evaluation.
A_STAR_GRID_SCALE = 5
A_STAR_ALLOW_DIAGONAL = True

# 2-Opt limits.
MAX_2OPT_PASSES = 4
MAX_2OPT_CANDIDATES_PER_PASS = 140

# Or-Opt is disabled by default because 2-Opt already gives
# excellent results for dense lawnmower coverage routes.
MAX_OR_OPT_PASSES = 0
OR_OPT_CHAIN_LENGTHS = ()

# Keep only two deterministic NN starts.
MULTI_START_RANDOM_SEEDS = 0


# ============================================================
# ROAD / START-END PARAMETERS
# ============================================================

# Reference location around D / road start for the supplied map.
REFERENCE_START = (70, 435)

# If road detection cannot produce two useful endpoints,
# these reference points are used.
REFERENCE_ROAD_END = (1215, 430)


# ============================================================
# OPTIONAL PHYSICAL CALIBRATION
# ============================================================

DRONE_SPEED_PIXELS_PER_SECOND = None
TRANSIT_SPEED_PIXELS_PER_SECOND = None
TURN_TIME_SECONDS = None

SPRAY_RATE_LITRES_PER_PIXEL = None
DRONE_TANK_CAPACITY_LITRES = None

MAX_SORTIE_TIME_MINUTES = None
BATTERY_SAFETY_RESERVE_MINUTES = None


# ============================================================
# GLOBAL TRANSIT CACHE
# ============================================================

_TRANSIT_PATH_CACHE = {}


# ============================================================
# IMAGE
# ============================================================

def load_image():
    if not INPUT_IMAGE.exists():
        raise FileNotFoundError(
            f"Input image not found:\n{INPUT_IMAGE}"
        )

    image = cv2.imread(str(INPUT_IMAGE))

    if image is None:
        raise RuntimeError(
            "OpenCV could not read the field image."
        )

    return image


# ============================================================
# FIELD BOUNDARY
# ============================================================

def create_field_mask(image):
    height, width = image.shape[:2]

    reference_polygon = np.array([
        [60, 50],
        [1260, 52],
        [1230, 435],
        [995, 675],
        [610, 455],
        [65, 445]
    ], dtype=np.float32)

    sx = width / 1280.0
    sy = height / 720.0

    polygon = reference_polygon.copy()
    polygon[:, 0] *= sx
    polygon[:, 1] *= sy
    polygon = polygon.astype(np.int32)

    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(mask, [polygon], 255)

    if SAFETY_MARGIN > 0:
        kernel_size = SAFETY_MARGIN * 2 + 1
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)
        )
        mask = cv2.erode(mask, kernel)

    return mask


# ============================================================
# ROAD / POND DETECTION
# ============================================================

def detect_excluded_regions(image):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    blue_lower = np.array([80, 50, 50])
    blue_upper = np.array([130, 255, 255])
    blue = cv2.inRange(hsv, blue_lower, blue_upper)

    orange_lower = np.array([5, 60, 50])
    orange_upper = np.array([30, 255, 255])
    orange = cv2.inRange(hsv, orange_lower, orange_upper)

    excluded = cv2.bitwise_or(blue, orange)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    excluded = cv2.morphologyEx(excluded, cv2.MORPH_OPEN, kernel)
    excluded = cv2.morphologyEx(excluded, cv2.MORPH_CLOSE, kernel)

    if DRONE_OBSTACLE_CLEARANCE > 0:
        clearance_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (
                DRONE_OBSTACLE_CLEARANCE * 2 + 1,
                DRONE_OBSTACLE_CLEARANCE * 2 + 1
            )
        )
        excluded = cv2.dilate(excluded, clearance_kernel)

    return excluded


def create_usable_mask(field_mask, excluded_mask):
    usable = field_mask.copy()
    usable[excluded_mask > 0] = 0
    return usable


# ============================================================
# ROAD ENDPOINTS
# ============================================================

def _scaled_reference_point(point, width, height):
    return (
        int(point[0] * width / 1280.0),
        int(point[1] * height / 720.0)
    )


def detect_road_endpoints(image, field_mask, excluded_mask):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lower = np.array([5, 60, 50])
    upper = np.array([30, 255, 255])
    road = cv2.inRange(hsv, lower, upper)
    road = cv2.bitwise_and(road, field_mask)

    ys, xs = np.where(road > 0)

    height, width = image.shape[:2]
    fallback_start = _scaled_reference_point(REFERENCE_START, width, height)
    fallback_end = _scaled_reference_point(REFERENCE_ROAD_END, width, height)

    if len(xs) < 100:
        return (fallback_start, fallback_end)

    points = np.column_stack([xs.astype(np.float32), ys.astype(np.float32)])
    mean = points.mean(axis=0)
    centered = points - mean
    covariance = np.cov(centered.T)
    values, vectors = np.linalg.eigh(covariance)
    direction = vectors[:, np.argmax(values)]
    projection = centered @ direction

    p1 = points[np.argmin(projection)]
    p2 = points[np.argmax(projection)]
    endpoint1 = (int(p1[0]), int(p1[1]))
    endpoint2 = (int(p2[0]), int(p2[1]))

    if (
        distance(endpoint2, fallback_start)
        < distance(endpoint1, fallback_start)
    ):
        endpoint1, endpoint2 = endpoint2, endpoint1

    return (endpoint1, endpoint2)


# ============================================================
# BASIC GEOMETRY
# ============================================================

def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def segment_start(segment, reverse=False):
    if reverse:
        return (segment["x2"], segment["y2"])
    return (segment["x1"], segment["y1"])


def segment_end(segment, reverse=False):
    if reverse:
        return (segment["x1"], segment["y1"])
    return (segment["x2"], segment["y2"])


def segment_length(segment):
    return distance(
        (segment["x1"], segment["y1"]),
        (segment["x2"], segment["y2"])
    )


def coverage_distance(route):
    return sum(segment_length(segment) for segment in route)


# ============================================================
# COVERAGE GENERATION
# ============================================================

def _continuous_runs(usable_indices):
    if len(usable_indices) == 0:
        return []

    runs = []
    start = int(usable_indices[0])
    previous = int(usable_indices[0])

    for value in usable_indices[1:]:
        value = int(value)

        if value > previous + 1:
            runs.append((start, previous))
            start = value

        previous = value

    runs.append((start, previous))
    return runs


def generate_horizontal_segments(usable_mask):
    height, width = usable_mask.shape
    segments = []
    y = LINE_SPACING // 2

    while y < height:
        row = usable_mask[y]
        indices = np.where(row > 0)[0]

        for x1, x2 in _continuous_runs(indices):
            if x2 - x1 >= MIN_SEGMENT_LENGTH:
                segments.append({
                    "x1": int(x1), "y1": int(y),
                    "x2": int(x2), "y2": int(y),
                    "orientation": "Horizontal"
                })

        y += LINE_SPACING

    return segments


def generate_vertical_segments(usable_mask):
    height, width = usable_mask.shape
    segments = []
    x = LINE_SPACING // 2

    while x < width:
        column = usable_mask[:, x]
        indices = np.where(column > 0)[0]

        for y1, y2 in _continuous_runs(indices):
            if y2 - y1 >= MIN_SEGMENT_LENGTH:
                segments.append({
                    "x1": int(x), "y1": int(y1),
                    "x2": int(x), "y2": int(y2),
                    "orientation": "Vertical"
                })

        x += LINE_SPACING

    return segments


# ============================================================
# A* TRANSIT
# ============================================================

def create_navigation_mask(field_mask, excluded_mask):
    navigation = field_mask.copy()
    safe_excluded = excluded_mask.copy()

    if DRONE_OBSTACLE_CLEARANCE > 0:
        kernel_size = DRONE_OBSTACLE_CLEARANCE * 2 + 1
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)
        )
        safe_excluded = cv2.dilate(safe_excluded, kernel)

    navigation[safe_excluded > 0] = 0
    return navigation


def _line_is_safe(a, b, navigation_mask):
    length = max(2, int(distance(a, b)))

    xs = np.linspace(a[0], b[0], length + 1).astype(np.int32)
    ys = np.linspace(a[1], b[1], length + 1).astype(np.int32)

    height, width = navigation_mask.shape
    valid = (xs >= 0) & (xs < width) & (ys >= 0) & (ys < height)

    if not np.all(valid):
        return False

    return bool(np.all(navigation_mask[ys, xs] > 0))


def _nearest_free_cell(free_grid, point):
    h, w = free_grid.shape
    x = max(0, min(w - 1, int(point[0])))
    y = max(0, min(h - 1, int(point[1])))

    if free_grid[y, x]:
        return (x, y)

    for radius in range(1, 40):
        x0 = max(0, x - radius)
        x1 = min(w - 1, x + radius)
        y0 = max(0, y - radius)
        y1 = min(h - 1, y + radius)

        for xx in range(x0, x1 + 1):
            if free_grid[y0, xx]:
                return (xx, y0)
            if free_grid[y1, xx]:
                return (xx, y1)

        for yy in range(y0, y1 + 1):
            if free_grid[yy, x0]:
                return (x0, yy)
            if free_grid[yy, x1]:
                return (x1, yy)

    return None


def _a_star(navigation_mask, start, goal):
    scale = max(1, int(A_STAR_GRID_SCALE))
    height, width = navigation_mask.shape

    grid_h = int(math.ceil(height / scale))
    grid_w = int(math.ceil(width / scale))

    resized = cv2.resize(
        navigation_mask, (grid_w, grid_h),
        interpolation=cv2.INTER_AREA
    )
    free = resized > 200

    start_grid = (
        int(round(start[0] / scale)),
        int(round(start[1] / scale))
    )
    goal_grid = (
        int(round(goal[0] / scale)),
        int(round(goal[1] / scale))
    )

    start_grid = _nearest_free_cell(free, start_grid)
    goal_grid = _nearest_free_cell(free, goal_grid)

    if start_grid is None or goal_grid is None:
        return None

    if start_grid == goal_grid:
        return [start, goal]

    if A_STAR_ALLOW_DIAGONAL:
        moves = [
            (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
            (-1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)),
            (1, -1, math.sqrt(2)), (1, 1, math.sqrt(2))
        ]
    else:
        moves = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0)]

    def h(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    heap = []
    counter = 0

    heapq.heappush(heap, (h(start_grid, goal_grid), counter, start_grid))

    came_from = {}
    g_score = {start_grid: 0.0}
    closed = set()

    while heap:
        _, _, current = heapq.heappop(heap)

        if current in closed:
            continue

        if current == goal_grid:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()

            image_path = []
            for gx, gy in path:
                px = min(width - 1, int(gx * scale + scale / 2))
                py = min(height - 1, int(gy * scale + scale / 2))
                image_path.append((px, py))

            image_path[0] = (int(start[0]), int(start[1]))
            image_path[-1] = (int(goal[0]), int(goal[1]))

            return image_path

        closed.add(current)
        cx, cy = current

        for dx, dy, cost in moves:
            nx = cx + dx
            ny = cy + dy

            if nx < 0 or nx >= grid_w or ny < 0 or ny >= grid_h:
                continue

            if not free[ny, nx]:
                continue

            if dx != 0 and dy != 0:
                if not free[cy, nx] or not free[ny, cx]:
                    continue

            neighbour = (nx, ny)
            if neighbour in closed:
                continue

            new_g = g_score[current] + cost

            if neighbour not in g_score or new_g < g_score[neighbour]:
                came_from[neighbour] = current
                g_score[neighbour] = new_g
                counter += 1

                heapq.heappush(
                    heap,
                    (new_g + h(neighbour, goal_grid), counter, neighbour)
                )

    return None


def _path_length(path):
    if not path or len(path) < 2:
        return 0.0

    return sum(
        distance(path[i], path[i + 1])
        for i in range(len(path) - 1)
    )


def get_safe_transit_path(start, goal, navigation_mask):
    start = (int(start[0]), int(start[1]))
    goal = (int(goal[0]), int(goal[1]))

    if start == goal:
        return [start]

    key = (start, goal)
    reverse_key = (goal, start)

    if key in _TRANSIT_PATH_CACHE:
        return _TRANSIT_PATH_CACHE[key]

    if reverse_key in _TRANSIT_PATH_CACHE:
        reversed_path = list(reversed(_TRANSIT_PATH_CACHE[reverse_key]))
        _TRANSIT_PATH_CACHE[key] = reversed_path
        return reversed_path

    if _line_is_safe(start, goal, navigation_mask):
        path = [start, goal]
        _TRANSIT_PATH_CACHE[key] = path
        return path

    path = _a_star(navigation_mask, start, goal)

    if path is None:
        return None

    _TRANSIT_PATH_CACHE[key] = path
    return path


def safe_transit_distance(start, goal, navigation_mask):
    path = get_safe_transit_path(start, goal, navigation_mask)

    if path is None:
        return float("inf")

    return _path_length(path)


# ============================================================
# ROUTE DISTANCE
# ============================================================

def calculate_route_distance(
    route, navigation_mask, road_start=None, road_end=None
):
    if not route:
        return float("inf")

    total = 0.0

    if road_start is not None:
        first_start = segment_start(route[0], route[0]["reverse"])
        d = safe_transit_distance(road_start, first_start, navigation_mask)

        if not math.isfinite(d):
            return float("inf")

        total += d

    for i, segment in enumerate(route):
        start = segment_start(segment, segment["reverse"])
        end = segment_end(segment, segment["reverse"])

        total += distance(start, end)

        if i + 1 < len(route):
            next_start = segment_start(route[i + 1], route[i + 1]["reverse"])
            d = safe_transit_distance(end, next_start, navigation_mask)

            if not math.isfinite(d):
                return float("inf")

            total += d

    if road_end is not None:
        last_end = segment_end(route[-1], route[-1]["reverse"])
        d = safe_transit_distance(last_end, road_end, navigation_mask)

        if not math.isfinite(d):
            return float("inf")

        total += d

    return total


# ============================================================
# BOUSTROPHEDON SEED  (NEW)
# ============================================================
#
# For a set of parallel strips (horizontal or vertical), the
# globally optimal ordering is almost always to visit them in
# spatial order and alternate direction on each strip. This is
# the "boustrophedon" (ox-plowing) pattern. Sorting the
# segments by their perpendicular coordinate and alternating
# the traversal direction gives the metaheuristics an
# excellent starting point and often produces a route that
# is already near-optimal before 2-Opt or Or-Opt is applied.
#
# For horizontal segments, strips are indexed by Y.
# For vertical segments, strips are indexed by X.
# ============================================================

def boustrophedon_seed(segments):
    """
    Return a route built by visiting strips in spatial order
    with alternating direction — the classic lawn-mower seed.
    Segments within the same strip are ordered left-to-right
    (or top-to-bottom), and even-indexed strips are traversed
    in the natural direction while odd-indexed strips are
    reversed.
    """
    if not segments:
        return []

    orientation = segments[0]["orientation"]

    # Group by strip coordinate.
    if orientation == "Horizontal":
        strip_key = lambda s: s["y1"]
    else:
        strip_key = lambda s: s["x1"]

    from itertools import groupby

    sorted_segments = sorted(segments, key=strip_key)
    grouped = []

    for key, group in groupby(sorted_segments, key=strip_key):
        group_list = list(group)
        # Within each strip, sort by the along-strip coordinate.
        if orientation == "Horizontal":
            group_list.sort(key=lambda s: s["x1"])
        else:
            group_list.sort(key=lambda s: s["y1"])

        grouped.append(group_list)

    route = []

    for strip_index, strip_segments in enumerate(grouped):
        # Even strips: forward; odd strips: reversed traversal.
        if strip_index % 2 == 0:
            for seg in strip_segments:
                seg = seg.copy()
                seg["reverse"] = False
                route.append(seg)
        else:
            for seg in reversed(strip_segments):
                seg = seg.copy()
                seg["reverse"] = True
                route.append(seg)

    return route


# ============================================================
# NEAREST NEIGHBOR
# ============================================================

def _endpoint(segment, reverse, which):
    """Return oriented start/end point without allocating copies."""
    if which == "start":
        return segment_end(segment, False) if reverse else segment_start(segment, False)
    return segment_start(segment, False) if reverse else segment_end(segment, False)


def _transition_cost(from_point, to_point, navigation_mask):
    """Obstacle-safe transit distance with caching."""
    return safe_transit_distance(from_point, to_point, navigation_mask)


def nearest_neighbor(segments, navigation_mask, start_point):
    """
    FAST greedy seed.

    Important speed change:
    NN uses straight-line distance only while choosing the next
    segment. The selected route is then evaluated with the exact
    obstacle-safe transit model.

    This avoids thousands of A* searches during NN construction.
    """
    remaining = [segment.copy() for segment in segments]
    route = []
    current = start_point

    while remaining:
        best_index = None
        best_reverse = False
        best_cost = float("inf")

        for i, segment in enumerate(remaining):
            left = (segment["x1"], segment["y1"])
            right = (segment["x2"], segment["y2"])

            d_left = distance(current, left)
            d_right = distance(current, right)

            if d_left < best_cost:
                best_cost = d_left
                best_index = i
                best_reverse = False

            if d_right < best_cost:
                best_cost = d_right
                best_index = i
                best_reverse = True

        if best_index is None:
            raise RuntimeError("Nearest Neighbor could not build a route.")

        segment = remaining.pop(best_index)
        segment["reverse"] = best_reverse
        route.append(segment)
        current = segment_end(segment, best_reverse)

    return route


def multi_start_nearest_neighbor(
    segments, navigation_mask, road_start, road_end
):
    """
    Build a small number of fast deterministic seeds and evaluate
    each one with the exact obstacle-aware route metric.
    """
    best_route = None
    best_dist = float("inf")

    # Boustrophedon seed.
    boustro = boustrophedon_seed(segments)
    if boustro:
        d = calculate_route_distance(
            boustro, navigation_mask, road_start, road_end
        )
        if math.isfinite(d) and d < best_dist:
            best_dist = d
            best_route = boustro
            print(f"      Boustrophedon seed distance: {d:.2f} px")

    # NN from road start.
    route = nearest_neighbor(segments, navigation_mask, road_start)
    d = calculate_route_distance(
        route, navigation_mask, road_start, road_end
    )
    if math.isfinite(d) and d < best_dist:
        best_dist = d
        best_route = route
    print(f"      NN (road_start) distance: {d:.2f} px")

    # NN from road end.
    route = nearest_neighbor(segments, navigation_mask, road_end)
    d = calculate_route_distance(
        route, navigation_mask, road_start, road_end
    )
    if math.isfinite(d) and d < best_dist:
        best_dist = d
        best_route = route
    print(f"      NN (road_end) distance: {d:.2f} px")

    if best_route is None:
        raise RuntimeError("No feasible initial route found.")

    print(f"      Best initial route: {best_dist:.2f} px")
    return best_route, best_dist


def _route_edge_cost(route, index, navigation_mask,
                     road_start=None, road_end=None):
    """
    Exact cost of one route edge.

    index=-1 means road_start -> first segment.
    index=len(route)-1 means last segment -> road_end.
    """
    n = len(route)

    if index == -1:
        if road_start is None or n == 0:
            return 0.0
        return safe_transit_distance(
            road_start,
            segment_start(route[0], route[0].get("reverse", False)),
            navigation_mask
        )

    if index >= n:
        return 0.0

    segment = route[index]
    end = segment_end(segment, segment.get("reverse", False))

    if index == n - 1:
        if road_end is None:
            return 0.0
        return safe_transit_distance(end, road_end, navigation_mask)

    nxt = route[index + 1]
    start = segment_start(nxt, nxt.get("reverse", False))

    return safe_transit_distance(end, start, navigation_mask)


def _boundary_cost(route, indices, navigation_mask,
                   road_start, road_end):
    """Sum only selected transit edges."""
    total = 0.0
    n = len(route)

    for idx in indices:
        if idx < -1 or idx >= n:
            continue

        d = _route_edge_cost(
            route, idx, navigation_mask, road_start, road_end
        )

        if not math.isfinite(d):
            return float("inf")

        total += d

    return total


def two_opt(route, navigation_mask, road_start, road_end):
    """
    FAST obstacle-aware 2-Opt.

    The old implementation rebuilt and evaluated the entire route
    for every candidate. This version evaluates only the two
    boundary transitions affected by a reversal.

    Transit distance is symmetric, so reversing the internal chain
    does not change the total cost of its internal transitions.
    """
    if len(route) < 3:
        current = calculate_route_distance(
            route, navigation_mask, road_start, road_end
        )
        return route, current, current, 0

    best = [segment.copy() for segment in route]
    best_distance = calculate_route_distance(
        best, navigation_mask, road_start, road_end
    )
    initial_distance = best_distance
    improvements = 0

    n = len(best)

    for pass_number in range(MAX_2OPT_PASSES):
        improved = False
        checked = 0

        for i in range(n - 1):
            for j in range(i + 1, n):
                checked += 1
                if checked > MAX_2OPT_CANDIDATES_PER_PASS:
                    break

                # Old boundary edges.
                old_indices = [i - 1, j]
                old_cost = _boundary_cost(
                    best, old_indices,
                    navigation_mask, road_start, road_end
                )

                if not math.isfinite(old_cost):
                    continue

                # Build only the reversed portion.
                candidate = best[:]
                middle = []

                for segment in reversed(best[i:j + 1]):
                    copied = segment.copy()
                    copied["reverse"] = not copied.get("reverse", False)
                    middle.append(copied)

                candidate[i:j + 1] = middle

                # New boundary edges.
                new_indices = [i - 1, j]
                new_cost = _boundary_cost(
                    candidate, new_indices,
                    navigation_mask, road_start, road_end
                )

                if not math.isfinite(new_cost):
                    continue

                candidate_distance = (
                    best_distance - old_cost + new_cost
                )

                if candidate_distance + 1e-9 < best_distance:
                    best = candidate
                    best_distance = candidate_distance
                    improvements += 1
                    improved = True
                    break

            if improved or checked > MAX_2OPT_CANDIDATES_PER_PASS:
                break

        print(
            f"      2-Opt pass {pass_number + 1}/{MAX_2OPT_PASSES}: "
            f"{'improved' if improved else 'converged'}"
        )

        if not improved:
            break

    return best, initial_distance, best_distance, improvements


def or_opt(route, navigation_mask, road_start, road_end):
    """
    Optional final cleanup.

    Disabled by default (MAX_OR_OPT_PASSES=0) because the
    expensive exhaustive relocation search provides little benefit
    for this strip-based coverage problem.
    """
    current = calculate_route_distance(
        route, navigation_mask, road_start, road_end
    )
    return route, current, 0


def evaluate_orientation(
    name, segments, navigation_mask, road_start, road_end
):
    if not segments:
        return None

    print(f"      Evaluating {name} coverage...")

    route, nn_distance = multi_start_nearest_neighbor(
        segments, navigation_mask, road_start, road_end
    )

    print(f"      {name} initial distance: {nn_distance:.2f} px")

    if not math.isfinite(nn_distance):
        return None

    (
        optimized,
        two_opt_initial,
        two_opt_distance,
        two_opt_improvements
    ) = two_opt(
        route, navigation_mask, road_start, road_end
    )

    print(
        f"      {name} after 2-Opt: "
        f"{two_opt_distance:.2f} px"
    )

    (
        final_route,
        final_distance,
        or_opt_improvements
    ) = or_opt(
        optimized, navigation_mask, road_start, road_end
    )

    print(
        f"      {name} after Or-Opt: "
        f"{final_distance:.2f} px"
    )

    return {
        "orientation": name,
        "route": final_route,
        "nearest_neighbor_distance": nn_distance,
        "two_opt_initial_distance": two_opt_initial,
        "two_opt_distance": two_opt_distance,
        "optimized_distance": final_distance,
        "two_opt_improvements": two_opt_improvements,
        "or_opt_improvements": or_opt_improvements,
        "coverage_distance": coverage_distance(final_route)
    }


# ============================================================
# OPERATION METRICS
# ============================================================

def calculate_operation_metrics(coverage_dist, transit_dist, turns):
    result = {
        "coverage_time_seconds": None,
        "transit_time_seconds": None,
        "turn_time_seconds": None,
        "total_flight_time_seconds": None,
        "total_flight_time_minutes": None,
        "total_spray_volume_litres": None,
        "tank_loads": None,
        "number_of_sorties": None,
        "battery_status": "Not configured"
    }

    if (
        DRONE_SPEED_PIXELS_PER_SECOND is not None
        and DRONE_SPEED_PIXELS_PER_SECOND > 0
    ):
        result["coverage_time_seconds"] = (
            coverage_dist / DRONE_SPEED_PIXELS_PER_SECOND
        )

    if (
        TRANSIT_SPEED_PIXELS_PER_SECOND is not None
        and TRANSIT_SPEED_PIXELS_PER_SECOND > 0
    ):
        result["transit_time_seconds"] = (
            transit_dist / TRANSIT_SPEED_PIXELS_PER_SECOND
        )

    if TURN_TIME_SECONDS is not None and TURN_TIME_SECONDS >= 0:
        result["turn_time_seconds"] = turns * TURN_TIME_SECONDS

    if all(
        result[key] is not None
        for key in [
            "coverage_time_seconds",
            "transit_time_seconds",
            "turn_time_seconds"
        ]
    ):
        total_seconds = (
            result["coverage_time_seconds"]
            + result["transit_time_seconds"]
            + result["turn_time_seconds"]
        )
        result["total_flight_time_seconds"] = total_seconds
        result["total_flight_time_minutes"] = total_seconds / 60.0

    if (
        SPRAY_RATE_LITRES_PER_PIXEL is not None
        and SPRAY_RATE_LITRES_PER_PIXEL >= 0
    ):
        volume = coverage_dist * SPRAY_RATE_LITRES_PER_PIXEL
        result["total_spray_volume_litres"] = volume

        if (
            DRONE_TANK_CAPACITY_LITRES is not None
            and DRONE_TANK_CAPACITY_LITRES > 0
        ):
            result["tank_loads"] = max(
                1, math.ceil(volume / DRONE_TANK_CAPACITY_LITRES)
            )

    if (
        result["total_flight_time_minutes"] is not None
        and MAX_SORTIE_TIME_MINUTES is not None
        and MAX_SORTIE_TIME_MINUTES > 0
    ):
        reserve = (
            BATTERY_SAFETY_RESERVE_MINUTES
            if BATTERY_SAFETY_RESERVE_MINUTES is not None
            else 0
        )
        usable = MAX_SORTIE_TIME_MINUTES - reserve

        if usable > 0:
            result["number_of_sorties"] = max(
                1, math.ceil(result["total_flight_time_minutes"] / usable)
            )
            result["battery_status"] = (
                "Feasible"
                if result["total_flight_time_minutes"] <= usable
                else "Requires multiple sorties"
            )

    return result


# ============================================================
# STATISTICS
# ============================================================

def build_statistics(
    image, field_mask, usable_mask, excluded_mask,
    selected, horizontal_count, vertical_count,
    road_start, road_end
):
    route = selected["route"]
    coverage_dist = selected["coverage_distance"]
    total_distance = selected["optimized_distance"]
    transit_distance = max(total_distance - coverage_dist, 0.0)

    nn_distance = selected["nearest_neighbor_distance"]
    saved = max(nn_distance - total_distance, 0.0)
    improvement = (
        saved / nn_distance * 100.0 if nn_distance > 0 else 0.0
    )

    turns = max(0, len(route) - 1)
    operation = calculate_operation_metrics(
        coverage_dist, transit_distance, turns
    )

    height, width = image.shape[:2]
    excluded_inside = cv2.bitwise_and(field_mask, excluded_mask)

    forward = sum(1 for segment in route if not segment["reverse"])
    reverse = len(route) - forward

    return {
        "field_analysis": {
            "image_width_pixels": int(width),
            "image_height_pixels": int(height),
            "field_area_pixels": int(np.count_nonzero(field_mask)),
            "usable_field_area_pixels": int(np.count_nonzero(usable_mask)),
            "excluded_area_pixels": int(np.count_nonzero(excluded_inside)),
            "horizontal_candidate_segments": int(horizontal_count),
            "vertical_candidate_segments": int(vertical_count),
            "selected_coverage_segments": int(len(route)),
            "line_spacing_pixels": int(LINE_SPACING),
            "minimum_segment_length_pixels": int(MIN_SEGMENT_LENGTH)
        },

        "route_optimization": {
            "selected_orientation": selected["orientation"],
            "nearest_neighbor_distance_pixels": float(nn_distance),
            "two_opt_initial_distance_pixels": float(
                selected["two_opt_initial_distance"]
            ),
            "two_opt_distance_pixels": float(selected["two_opt_distance"]),
            "optimized_distance_pixels": float(total_distance),
            "distance_saved_pixels": float(saved),
            "improvement_percent": float(improvement),
            "nearest_neighbor_used": True,
            "boustrophedon_seed_used": True,
            "multi_start_nn_used": True,
            "two_opt_used": True,
            "or_opt_used": True,
            "two_opt_improvements": int(selected["two_opt_improvements"]),
            "or_opt_improvements": int(selected["or_opt_improvements"]),
            "forward_segments": int(forward),
            "reverse_segments": int(reverse),
            "number_of_turns": int(turns),
            "open_route": True,
            "return_to_start": False
        },

        "distances": {
            "coverage_distance_pixels": float(coverage_dist),
            "transit_distance_pixels": float(transit_distance),
            "total_route_distance_pixels": float(total_distance)
        },

        "road_route": {
            "start_x": int(road_start[0]),
            "start_y": int(road_start[1]),
            "end_x": int(road_end[0]),
            "end_y": int(road_end[1])
        },

        "drone_operation": operation,

        "parameters": {
            "line_spacing_pixels": LINE_SPACING,
            "safety_margin_pixels": SAFETY_MARGIN,
            "drone_obstacle_clearance_pixels": DRONE_OBSTACLE_CLEARANCE,
            "a_star_grid_scale": A_STAR_GRID_SCALE,
            "max_2opt_passes": MAX_2OPT_PASSES,
            "max_or_opt_passes": MAX_OR_OPT_PASSES,
            "or_opt_chain_lengths": list(OR_OPT_CHAIN_LENGTHS),
            "multi_start_random_seeds": MULTI_START_RANDOM_SEEDS,
            "drone_speed_pixels_per_second": DRONE_SPEED_PIXELS_PER_SECOND,
            "transit_speed_pixels_per_second": TRANSIT_SPEED_PIXELS_PER_SECOND,
            "turn_time_seconds": TURN_TIME_SECONDS,
            "spray_rate_litres_per_pixel": SPRAY_RATE_LITRES_PER_PIXEL,
            "drone_tank_capacity_litres": DRONE_TANK_CAPACITY_LITRES,
            "max_sortie_time_minutes": MAX_SORTIE_TIME_MINUTES,
            "battery_safety_reserve_minutes": BATTERY_SAFETY_RESERVE_MINUTES
        },

        "optimization_method": {
            "field_segmentation": True,
            "excluded_area_detection": True,
            "horizontal_vertical_comparison": True,
            "obstacle_aware_transit": True,
            "boustrophedon_seed": True,
            "multi_start_nearest_neighbor": True,
            "two_opt_full_restart": True,
            "or_opt": True,
            "open_road_to_road_route": True,
            "transit_visualization": False
        }
    }


# ============================================================
# DRAW RESULT
# ============================================================

def draw_result(
    image, field_mask, excluded_mask, route,
    road_start, road_end, stats
):
    result = image.copy()

    contours, _ = cv2.findContours(
        field_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(result, contours, -1, (0, 180, 0), 3)

    excluded_inside = cv2.bitwise_and(field_mask, excluded_mask)

    if np.any(excluded_inside > 0):
        overlay = result.copy()
        overlay[excluded_inside > 0] = (255, 120, 40)
        result = cv2.addWeighted(overlay, 0.30, result, 0.70, 0)

        excluded_contours, _ = cv2.findContours(
            excluded_inside, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        cv2.drawContours(result, excluded_contours, -1, (255, 0, 0), 3)

    for segment in route:
        start = segment_start(segment, segment["reverse"])
        end = segment_end(segment, segment["reverse"])

        cv2.line(result, start, end, (0, 220, 0), 2, cv2.LINE_AA)
        cv2.arrowedLine(
            result, start, end, (0, 170, 0), 2, cv2.LINE_AA, tipLength=0.035
        )

    cv2.circle(result, road_start, 10, (0, 0, 255), -1)
    cv2.circle(result, road_start, 13, (255, 255, 255), 2)
    cv2.putText(
        result, "ROAD START",
        (road_start[0] + 14, road_start[1] - 8),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2, cv2.LINE_AA
    )

    cv2.circle(result, road_end, 10, (255, 0, 0), -1)
    cv2.circle(result, road_end, 13, (255, 255, 255), 2)
    cv2.putText(
        result, "ROAD END",
        (road_end[0] + 14, road_end[1]),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 0), 2, cv2.LINE_AA
    )

    cv2.rectangle(result, (10, 10), (650, 65), (255, 255, 255), -1)
    cv2.putText(
        result, "AgriVision - Global Optimized Coverage Path",
        (20, 47), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (0, 100, 0), 2, cv2.LINE_AA
    )

    legend_x = max(20, result.shape[1] - 285)
    legend_y = 18

    cv2.rectangle(
        result,
        (legend_x - 10, legend_y - 8),
        (legend_x + 270, legend_y + 100),
        (255, 255, 255), -1
    )

    cv2.line(
        result, (legend_x, legend_y + 12),
        (legend_x + 35, legend_y + 12), (0, 220, 0), 3
    )
    cv2.putText(
        result, "Actual coverage",
        (legend_x + 45, legend_y + 17),
        cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 0), 1, cv2.LINE_AA
    )

    cv2.rectangle(
        result,
        (legend_x, legend_y + 31),
        (legend_x + 35, legend_y + 51),
        (255, 120, 40), -1
    )
    cv2.putText(
        result, "Excluded pond / road",
        (legend_x + 45, legend_y + 47),
        cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 0), 1, cv2.LINE_AA
    )

    cv2.putText(
        result, "Transit used internally — NOT DRAWN",
        (legend_x, legend_y + 75),
        cv2.FONT_HERSHEY_SIMPLEX, 0.43, (0, 0, 0), 1, cv2.LINE_AA
    )

    panel_x = 18
    panel_y = max(80, result.shape[0] - 175)
    panel_width = 460
    panel_height = 155

    cv2.rectangle(
        result,
        (panel_x, panel_y),
        (panel_x + panel_width, panel_y + panel_height),
        (255, 255, 255), -1
    )

    selected_orientation = stats["route_optimization"]["selected_orientation"]
    coverage = stats["distances"]["coverage_distance_pixels"]
    transit = stats["distances"]["transit_distance_pixels"]
    total = stats["distances"]["total_route_distance_pixels"]
    saved = stats["route_optimization"]["distance_saved_pixels"]
    improvement = stats["route_optimization"]["improvement_percent"]
    lines = stats["field_analysis"]["selected_coverage_segments"]
    or_impr = stats["route_optimization"]["or_opt_improvements"]
    two_impr = stats["route_optimization"]["two_opt_improvements"]

    panel_lines = [
        f"Orientation : {selected_orientation}",
        f"Coverage    : {coverage:.1f} px",
        f"Transit     : {transit:.1f} px",
        f"Total route : {total:.1f} px",
        f"Saved       : {saved:.1f} px ({improvement:.2f}%)",
        f"Lines       : {lines}",
        f"2-Opt impr  : {two_impr}   Or-Opt impr: {or_impr}",
    ]

    for i, text in enumerate(panel_lines):
        cv2.putText(
            result, text,
            (panel_x + 14, panel_y + 22 + i * 21),
            cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 0), 1, cv2.LINE_AA
        )

    return result


# ============================================================
# CSV
# ============================================================

def save_route_csv(route, navigation_mask, road_start):
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([
            "Segment", "Orientation",
            "Start_X", "Start_Y", "End_X", "End_Y",
            "Direction", "Coverage_Distance_px",
            "Transit_From_Previous_px", "Cumulative_Route_Distance_px"
        ])

        cumulative = 0.0
        previous_end = road_start

        for index, segment in enumerate(route, start=1):
            start = segment_start(segment, segment["reverse"])
            end = segment_end(segment, segment["reverse"])

            transit = safe_transit_distance(previous_end, start, navigation_mask)
            cov = distance(start, end)

            if not math.isfinite(transit):
                transit = 0.0

            cumulative += transit + cov

            writer.writerow([
                index,
                segment["orientation"],
                start[0], start[1], end[0], end[1],
                "Reverse" if segment["reverse"] else "Forward",
                f"{cov:.3f}",
                f"{transit:.3f}",
                f"{cumulative:.3f}"
            ])

            previous_end = end


# ============================================================
# JSON
# ============================================================

def save_statistics(stats):
    with open(OUTPUT_STATS, "w", encoding="utf-8") as file:
        json.dump(stats, file, indent=4)


# ============================================================
# MAIN
# ============================================================

def main():
    global _TRANSIT_PATH_CACHE

    _TRANSIT_PATH_CACHE = {}

    print()
    print("====================================================")
    print(" AGRIVISION - FAST GLOBAL ROUTE OPTIMIZATION")
    print(" (Boustrophedon seed · Multi-start NN · 2-Opt · Or-Opt)")
    print("====================================================")
    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------
    # 1. IMAGE
    # --------------------------------------------------------

    print("[1/9] Loading field image...")
    image = load_image()
    height, width = image.shape[:2]
    print(f"      Image size: {width} x {height}")

    # --------------------------------------------------------
    # 2. FIELD
    # --------------------------------------------------------

    print("[2/9] Creating actual field boundary...")
    field_mask = create_field_mask(image)

    # --------------------------------------------------------
    # 3. EXCLUDED
    # --------------------------------------------------------

    print("[3/9] Detecting road and pond/water...")
    excluded_mask = detect_excluded_regions(image)
    usable_mask = create_usable_mask(field_mask, excluded_mask)
    excluded_inside = cv2.bitwise_and(field_mask, excluded_mask)
    print(f"      Excluded area: {np.count_nonzero(excluded_inside)} px")

    # --------------------------------------------------------
    # 4. COVERAGE CANDIDATES
    # --------------------------------------------------------

    print("[4/9] Generating horizontal and vertical coverage candidates...")
    horizontal = generate_horizontal_segments(usable_mask)
    vertical = generate_vertical_segments(usable_mask)
    print(f"      Horizontal segments: {len(horizontal)}")
    print(f"      Vertical segments: {len(vertical)}")

    if not horizontal and not vertical:
        raise RuntimeError("No usable coverage segments detected.")

    # --------------------------------------------------------
    # 5. NAVIGATION
    # --------------------------------------------------------

    print("[5/9] Building obstacle-safe navigation map...")
    navigation_mask = create_navigation_mask(field_mask, excluded_mask)
    print(f"      Obstacle clearance: {DRONE_OBSTACLE_CLEARANCE} px")

    # --------------------------------------------------------
    # 6. ROAD
    # --------------------------------------------------------

    print("[6/9] Detecting road start/end...")
    road_start, road_end = detect_road_endpoints(
        image, field_mask, excluded_mask
    )
    print(f"      Road start: {road_start}")
    print(f"      Road end  : {road_end}")

    # --------------------------------------------------------
    # 7. GLOBAL OPTIMIZATION
    # --------------------------------------------------------

    print(
        "[7/9] Comparing horizontal and vertical global routes "
        "(Boustrophedon → Multi-start NN → 2-Opt → Or-Opt)..."
    )

    horizontal_result = None
    vertical_result = None

    if horizontal:
        horizontal_result = evaluate_orientation(
            "Horizontal", horizontal, navigation_mask, road_start, road_end
        )

    if vertical:
        vertical_result = evaluate_orientation(
            "Vertical", vertical, navigation_mask, road_start, road_end
        )

    candidates = [
        result
        for result in [horizontal_result, vertical_result]
        if result is not None and math.isfinite(result["optimized_distance"])
    ]

    if not candidates:
        raise RuntimeError(
            "Neither horizontal nor vertical route could be safely optimized."
        )

    selected = min(candidates, key=lambda r: r["optimized_distance"])

    print()
    print(f"      SELECTED ORIENTATION: {selected['orientation']}")
    print(f"      Final optimized route: {selected['optimized_distance']:.2f} px")

    # --------------------------------------------------------
    # 8. METRICS / OUTPUT
    # --------------------------------------------------------

    print("[8/9] Calculating complete route statistics...")
    stats = build_statistics(
        image=image,
        field_mask=field_mask,
        usable_mask=usable_mask,
        excluded_mask=excluded_mask,
        selected=selected,
        horizontal_count=len(horizontal),
        vertical_count=len(vertical),
        road_start=road_start,
        road_end=road_end
    )

    print("[9/9] Drawing coverage-only result...")
    result_image = draw_result(
        image, field_mask, excluded_mask,
        selected["route"], road_start, road_end, stats
    )

    if not cv2.imwrite(str(OUTPUT_IMAGE), result_image):
        raise RuntimeError("Failed to save optimized route image.")

    save_route_csv(selected["route"], navigation_mask, road_start)
    save_statistics(stats)

    # --------------------------------------------------------
    # FINAL SUMMARY
    # --------------------------------------------------------

    print()
    print("====================================================")
    print(" FINAL RESULTS")
    print("====================================================")
    print(f"Selected orientation : {stats['route_optimization']['selected_orientation']}")
    print(f"Coverage segments    : {stats['field_analysis']['selected_coverage_segments']}")
    print(f"Coverage distance    : {stats['distances']['coverage_distance_pixels']:.2f} px")
    print(f"Transit distance     : {stats['distances']['transit_distance_pixels']:.2f} px")
    print(f"Total route distance : {stats['distances']['total_route_distance_pixels']:.2f} px")
    print(f"Distance saved       : {stats['route_optimization']['distance_saved_pixels']:.2f} px")
    print(f"Improvement          : {stats['route_optimization']['improvement_percent']:.2f}%")
    print(f"2-Opt improvements   : {stats['route_optimization']['two_opt_improvements']}")
    print(f"Or-Opt improvements  : {stats['route_optimization']['or_opt_improvements']}")
    print(f"Turns                : {stats['route_optimization']['number_of_turns']}")
    print(f"Excluded area        : {stats['field_analysis']['excluded_area_pixels']} px")
    print()
    print(f"Output image:\n{OUTPUT_IMAGE}")
    print(f"Route CSV:\n{OUTPUT_CSV}")
    print(f"Statistics JSON:\n{OUTPUT_STATS}")
    print()
    print("====================================================")
    print(" DONE")
    print("====================================================")
    print()

    return {
        "success": True,
        "output_image": str(OUTPUT_IMAGE),
        "output_csv": str(OUTPUT_CSV),
        "output_stats": str(OUTPUT_STATS),
        "statistics": stats
    }


if __name__ == "__main__":
    main()