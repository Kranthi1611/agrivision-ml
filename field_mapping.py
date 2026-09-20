"""AgriVision Field Mapping backend - memory-optimized version.

Converts a cadastral field image + farmer data file into a structured,
farmer-linked field map while preserving the API-facing run_mapping()
contract and output filenames used by the original implementation.

Memory optimizations:
- No K x H x W seed-distance stack.
- No K x H x W cost stack or iterative full-image partition loop.
- Boundary term is not added to the nearest-seed cost because it is identical
  for every seed at a pixel and therefore cannot change argmin assignment.
- OCR uses yellow-label crops first and one capped-size fallback pass only if
  necessary, instead of 4 full-map versions at 2x/3x.
- Temporary full-size arrays are explicitly released between stages.
- No matplotlib figures are created during API execution.
- Overlap is computed incrementally instead of np.stack(all_masks).
- Structured-map panels are blended only over their local ROI instead of
  copying the entire image for every farmer.
"""

import gc
import json
import math
import os
import re
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

try:
    from IPython.display import display
except Exception:
    def display(obj):
        return None


OUTPUT_DIR = None
MAP_PATH = None
EXCEL_PATH = None


def _safe_json_value(value):
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _normalize_text(text):
    if text is None:
        return ""
    text = str(text).upper().strip()
    text = re.sub(r"\s+", "", text)
    for ch in ("-", "_", ".", "/"):
        text = text.replace(ch, "")
    return text


def _ocr_normalize(text):
    text = _normalize_text(text)
    return "".join({"O": "0", "I": "1", "L": "1"}.get(ch, ch) for ch in text)


def _land_to_acres(value):
    if pd.isna(value):
        return np.nan
    text = str(value).lower().strip().replace(",", "")
    m = re.search(r"([0-9]*\.?[0-9]+)\s*ac", text)
    if m:
        return float(m.group(1))
    m = re.search(r"([0-9]*\.?[0-9]+)\s*cent", text)
    if m:
        return float(m.group(1)) / 100.0
    m = re.search(r"([0-9]*\.?[0-9]+)", text)
    return float(m.group(1)) if m else np.nan


def _load_inputs(map_path, farmer_path, output_dir):
    global OUTPUT_DIR, MAP_PATH, EXCEL_PATH
    OUTPUT_DIR = str(output_dir)
    MAP_PATH = str(map_path)
    EXCEL_PATH = str(farmer_path)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    suffix = Path(EXCEL_PATH).suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(EXCEL_PATH)
    elif suffix == ".csv":
        df = pd.read_csv(EXCEL_PATH)
    else:
        raise ValueError("Farmer data must be .csv, .xlsx or .xls.")

    df.columns = df.columns.astype(str).str.strip()
    required = ["Survey Number", "Farmer Name", "Total land", "Mobile number", "Field"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError("Missing required farmer-data columns: " + ", ".join(missing))

    df["Survey Number"] = (
        df["Survey Number"].astype(str).str.strip().str.upper().str.replace(r"\.0$", "", regex=True)
    )
    df["Farmer Name"] = df["Farmer Name"].astype(str).str.strip()
    df["Field"] = df["Field"].astype(str).str.strip()
    df["Mobile number"] = df["Mobile number"].astype(str).str.strip()

    text_cols = ["Survey Number", "Farmer Name", "Total land", "Mobile number", "Field"]
    road_mask_rows = df[text_cols].fillna("").astype(str).apply(
        lambda row: row.str.lower().str.contains("road", regex=False).any(), axis=1
    )
    df["Is_Road"] = road_mask_rows

    road_df = df.loc[df["Is_Road"]].copy()
    farmer_df = df.loc[~df["Is_Road"]].copy()
    farmer_df["Original_Area_Acres"] = farmer_df["Total land"].apply(_land_to_acres)

    master_df = farmer_df[
        ["Survey Number", "Farmer Name", "Total land", "Original_Area_Acres", "Mobile number", "Field"]
    ].copy()
    master_df["Map_Matched"] = False
    master_df["Map_X"] = np.nan
    master_df["Map_Y"] = np.nan
    master_df["Map_Area_Pixels"] = np.nan
    master_df["Map_Area_Acres"] = np.nan
    master_df["Usable_Area_Acres"] = np.nan
    master_df["Disease_1"] = ""
    master_df["Disease_2"] = ""
    master_df["Treatment_Status"] = "Pending"
    master_df["Manager_Approval"] = "Pending"

    map_bgr = cv2.imread(MAP_PATH, cv2.IMREAD_COLOR)
    if map_bgr is None:
        raise ValueError("OpenCV could not read the uploaded field image.")
    map_rgb = cv2.cvtColor(map_bgr, cv2.COLOR_BGR2RGB)
    h, w = map_rgb.shape[:2]

    return master_df, road_df, map_bgr, map_rgb, h, w


def _prepare_masks(map_bgr, output_dir):
    """Build road/pond/red exclusion masks without retaining unnecessary copies."""
    hsv = cv2.cvtColor(map_bgr, cv2.COLOR_BGR2HSV)
    kernel = np.ones((5, 5), np.uint8)

    orange = cv2.inRange(hsv, np.array([5, 80, 80], np.uint8), np.array([30, 255, 255], np.uint8))
    blue = cv2.inRange(hsv, np.array([85, 60, 50], np.uint8), np.array([140, 255, 255], np.uint8))
    red1 = cv2.inRange(hsv, np.array([0, 80, 70], np.uint8), np.array([10, 255, 255], np.uint8))
    red2 = cv2.inRange(hsv, np.array([170, 80, 70], np.uint8), np.array([180, 255, 255], np.uint8))
    red = cv2.bitwise_or(red1, red2)
    del hsv, red1, red2

    orange = cv2.morphologyEx(orange, cv2.MORPH_OPEN, kernel)
    orange = cv2.morphologyEx(orange, cv2.MORPH_CLOSE, kernel)
    blue = cv2.morphologyEx(blue, cv2.MORPH_OPEN, kernel)
    blue = cv2.morphologyEx(blue, cv2.MORPH_CLOSE, kernel)
    red = cv2.morphologyEx(red, cv2.MORPH_OPEN, kernel)
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, kernel)

    excluded = cv2.bitwise_or(orange, blue)
    excluded = cv2.bitwise_or(excluded, red)
    excluded = np.ascontiguousarray(excluded, dtype=np.uint8)
    usable = cv2.bitwise_not(excluded)
    usable = np.ascontiguousarray(usable, dtype=np.uint8)
    road_mask = np.ascontiguousarray((orange > 0).astype(np.uint8))

    cv2.imwrite(os.path.join(output_dir, "road_mask.png"), orange)
    cv2.imwrite(os.path.join(output_dir, "pond_mask.png"), blue)
    cv2.imwrite(os.path.join(output_dir, "red_not_use_mask.png"), red)
    cv2.imwrite(os.path.join(output_dir, "excluded_mask.png"), excluded)
    cv2.imwrite(os.path.join(output_dir, "usable_land_mask.png"), usable)

    cleaned = map_bgr.copy()
    cleaned[excluded > 0] = 0
    cv2.imwrite(os.path.join(output_dir, "cleaned_map.png"), cleaned)

    del orange, blue, red, cleaned, kernel
    gc.collect()
    return excluded, usable, road_mask


def _load_ocr_reader():
    try:
        import easyocr
    except ImportError as exc:
        raise RuntimeError("EasyOCR is required for Field Mapping. Add easyocr to requirements.txt.") from exc

    # CPU mode avoids GPU memory use. verbose=False reduces log noise.
    return easyocr.Reader(["en"], gpu=False, verbose=False)


def _detect_yellow_regions(map_bgr):
    hsv = cv2.cvtColor(map_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([15, 50, 80], np.uint8), np.array([45, 255, 255], np.uint8))
    del hsv
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    del kernel

    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    boxes = []
    for i in range(1, n):
        x = int(stats[i, cv2.CC_STAT_LEFT])
        y = int(stats[i, cv2.CC_STAT_TOP])
        w = int(stats[i, cv2.CC_STAT_WIDTH])
        h = int(stats[i, cv2.CC_STAT_HEIGHT])
        area = int(stats[i, cv2.CC_STAT_AREA])
        if 5 <= area <= 5000 and w >= 3 and h >= 3:
            boxes.append((x, y, w, h, area))
    del labels, stats
    return mask, boxes


def _run_ocr(map_bgr, map_rgb, survey_numbers, h, w, output_dir):
    """OCR only likely survey-label regions plus a capped fallback if needed."""
    normalized = {_normalize_text(s): s for s in survey_numbers}
    ocr_normalized = {_ocr_normalize(s): s for s in survey_numbers}

    yellow_mask, boxes = _detect_yellow_regions(map_bgr)
    cv2.imwrite(os.path.join(output_dir, "ocr_yellow_label_mask.png"), yellow_mask)

    reader = _load_ocr_reader()
    records = []
    allowlist = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-/"

    # Cap crop enlargement. This is deliberately much smaller than the original 5x.
    for idx, (x, y, bw, bh, _) in enumerate(boxes):
        x1 = max(0, x - 12)
        y1 = max(0, y - 10)
        x2 = min(w, x + bw + 12)
        y2 = min(h, y + bh + 10)
        crop = map_bgr[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        scale = min(3.0, max(1.5, 120.0 / max(1, max(crop.shape[:2]))))
        crop_big = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        try:
            results = reader.readtext(crop_big, detail=1, paragraph=False, allowlist=allowlist)
        except Exception:
            results = []
        del crop_big, crop

        for bbox, text, confidence in results:
            text = str(text).strip()
            if not text:
                continue
            records.append({
                "Source": "yellow_region",
                "Region_ID": idx + 1,
                "OCR_Text": text,
                "Confidence": float(confidence),
                "Map_X": int(x + bw / 2),
                "Map_Y": int(y + bh / 2),
                "Crop_X1": x1,
                "Crop_Y1": y1,
                "Crop_X2": x2,
                "Crop_Y2": y2,
            })

    # Only run one small fallback pass if yellow-label OCR produced no candidate.
    if not records and h > 0 and w > 0:
        max_dim = 1600
        scale = min(1.0, max_dim / float(max(h, w)))
        small = cv2.resize(map_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else map_bgr
        try:
            results = reader.readtext(small, detail=1, paragraph=False, allowlist=allowlist)
        except Exception:
            results = []
        if scale < 1:
            del small
        inv = 1.0 / scale
        for bbox, text, confidence in results:
            text = str(text).strip()
            if not text:
                continue
            pts = np.asarray(bbox, dtype=np.float32) * inv
            cx = int(np.mean(pts[:, 0]))
            cy = int(np.mean(pts[:, 1]))
            records.append({
                "Source": "full_map_fallback",
                "Region_ID": -1,
                "OCR_Text": text,
                "Confidence": float(confidence),
                "Map_X": cx,
                "Map_Y": cy,
            })

    # Release the EasyOCR model before heavy segmentation.
    del reader, yellow_mask, boxes
    gc.collect()

    yellow_df = pd.DataFrame(records)
    if yellow_df.empty:
        yellow_df = pd.DataFrame(columns=["Source", "Region_ID", "OCR_Text", "Confidence", "Map_X", "Map_Y"])

    yellow_df.to_csv(os.path.join(output_dir, "yellow_region_ocr.csv"), index=False)

    def best_match(text, threshold=0.55):
        norm = _ocr_normalize(text)
        if not norm:
            return None, 0.0
        if norm in ocr_normalized:
            return ocr_normalized[norm], 1.0
        if norm in normalized:
            return normalized[norm], 1.0
        best_survey, best_score = None, 0.0
        for survey in survey_numbers:
            score = SequenceMatcher(None, norm, _ocr_normalize(survey)).ratio()
            if score > best_score:
                best_survey, best_score = survey, score
        return (best_survey, best_score) if best_score >= threshold else (None, best_score)

    candidates = []
    for _, row in yellow_df.iterrows():
        survey, score = best_match(row["OCR_Text"])
        if survey is not None:
            candidates.append({
                "Survey Number": survey,
                "OCR_Text": row["OCR_Text"],
                "OCR_Confidence": float(row["Confidence"]),
                "Match_Score": float(score),
                "Map_X": int(row["Map_X"]),
                "Map_Y": int(row["Map_Y"]),
                "Source": row["Source"],
            })

    candidate_df = pd.DataFrame(candidates)
    if candidate_df.empty:
        survey_map_df = pd.DataFrame(columns=["Survey Number", "OCR_Text", "OCR_Confidence", "Match_Score", "Map_X", "Map_Y", "Source"])
    else:
        candidate_df["Combined_Score"] = candidate_df["OCR_Confidence"] * candidate_df["Match_Score"]
        survey_map_df = (
            candidate_df.sort_values("Combined_Score", ascending=False)
            .drop_duplicates("Survey Number", keep="first")
            .reset_index(drop=True)
        )

    combined = survey_map_df.copy()
    candidate_df.to_csv(os.path.join(output_dir, "survey_match_candidates.csv"), index=False)
    survey_map_df.to_csv(os.path.join(output_dir, "survey_map_matches.csv"), index=False)
    combined.to_csv(os.path.join(output_dir, "combined_ocr_results.csv"), index=False)

    return survey_map_df


def _nearest_seed_labels(field_seeds, h, w, usable_mask):
    """Memory-safe nearest-seed partition.

    The original code added the same boundary penalty to every seed at a given
    pixel. That term cancels in argmin, so the repeated 8-iteration KxHxW
    cost stack is unnecessary. We keep only one minimum-distance image and
    one integer label image.
    """
    surveys = field_seeds["Survey Number"].tolist()
    labels = np.zeros((h, w), dtype=np.int32)
    min_dist = np.full((h, w), np.inf, dtype=np.float32)

    yy = np.arange(h, dtype=np.float32)[:, None]
    xx = np.arange(w, dtype=np.float32)[None, :]

    for index, row in enumerate(field_seeds.itertuples(index=False), start=1):
        sx = float(row.Map_X)
        sy = float(row.Map_Y)
        # One temporary HxW float32 array at a time.
        dist = (xx - sx) ** 2 + (yy - sy) ** 2
        better = dist < min_dist
        labels[better] = index
        min_dist[better] = dist[better]
        del dist, better

    labels[usable_mask == 0] = 0
    del min_dist, yy, xx
    gc.collect()
    return surveys, np.ascontiguousarray(labels, dtype=np.int32)


def _keep_seed_component(mask, sx, sy, h, w):
    mask = np.ascontiguousarray(mask, dtype=np.uint8)
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        del labels, stats, centroids
        return mask
    sx = int(np.clip(sx, 0, w - 1))
    sy = int(np.clip(sy, 0, h - 1))
    seed_label = int(labels[sy, sx])
    if seed_label == 0:
        best_label, best_dist = 0, np.inf
        for label_id in range(1, n):
            cx, cy = centroids[label_id]
            d = (cx - sx) ** 2 + (cy - sy) ** 2
            if d < best_dist:
                best_dist, best_label = d, label_id
        seed_label = best_label
    if seed_label == 0:
        result = np.zeros_like(mask)
    else:
        result = (labels == seed_label).astype(np.uint8)
    del labels, stats, centroids
    return np.ascontiguousarray(result, dtype=np.uint8)


def _build_geometry(field_seeds, field_masks, excluded_mask, h, w):
    field_pixel_areas = {}
    field_centroids = {}
    field_contours = {}
    field_polygons = {}
    geometry_records = []

    combined_usable = np.zeros((h, w), dtype=np.uint8)
    overlap_counter = np.zeros((h, w), dtype=np.uint16)

    for _, row in field_seeds.iterrows():
        survey = str(row["Survey Number"])
        mask = field_masks[survey]
        area = int(np.count_nonzero(mask))
        field_pixel_areas[survey] = area
        combined_usable[mask > 0] = 1
        overlap_counter[mask > 0] += 1

        moments = cv2.moments(mask)
        if moments["m00"] > 0:
            cx = moments["m10"] / moments["m00"]
            cy = moments["m01"] / moments["m00"]
        else:
            cx = cy = np.nan
        field_centroids[survey] = (cx, cy)

        mask255 = np.ascontiguousarray(mask * 255, dtype=np.uint8)
        contours, _ = cv2.findContours(mask255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            contour = polygon = None
            contour_area = perimeter = 0.0
        else:
            contour = max(contours, key=cv2.contourArea)
            contour_area = float(cv2.contourArea(contour))
            perimeter = float(cv2.arcLength(contour, True))
            polygon = cv2.approxPolyDP(contour, 0.003 * perimeter, True)
        field_contours[survey] = contour
        field_polygons[survey] = polygon

        ys, xs = np.where(mask > 0)
        if len(xs):
            min_x, max_x = int(xs.min()), int(xs.max())
            min_y, max_y = int(ys.min()), int(ys.max())
        else:
            min_x = max_x = min_y = max_y = -1

        geometry_records.append({
            "Survey_Number": survey,
            "Seed_X": int(row["Map_X"]),
            "Seed_Y": int(row["Map_Y"]),
            "Min_X": min_x,
            "Max_X": max_x,
            "Min_Y": min_y,
            "Max_Y": max_y,
            "Width_Pixels": max_x - min_x + 1 if max_x >= 0 else 0,
            "Height_Pixels": max_y - min_y + 1 if max_y >= 0 else 0,
            "Pixel_Area": area,
            "Contour_Area": contour_area,
            "Perimeter_Pixels": perimeter,
            "Centroid_X": cx,
            "Centroid_Y": cy,
        })
        del mask255, contours, xs, ys

    combined_usable[excluded_mask > 0] = 0
    overlap_pixels = int(np.count_nonzero(overlap_counter > 1))
    total_usable_pixels = int(np.count_nonzero(combined_usable))
    del overlap_counter

    geometry_df = pd.DataFrame(geometry_records)
    if total_usable_pixels:
        geometry_df["Percentage_of_Usable_Area"] = geometry_df["Pixel_Area"] / total_usable_pixels * 100
    else:
        geometry_df["Percentage_of_Usable_Area"] = 0.0

    distances = []
    for _, r in geometry_df.iterrows():
        distances.append(math.hypot(r["Seed_X"] - r["Centroid_X"], r["Seed_Y"] - r["Centroid_Y"]))
    geometry_df["Seed_to_Centroid_Distance"] = distances

    median_area = max(float(np.median(geometry_df["Pixel_Area"])) if len(geometry_df) else 1.0, 1.0)
    geometry_df["Area_Ratio_to_Median"] = geometry_df["Pixel_Area"] / median_area
    geometry_df["Geometry_QC"] = "OK"
    for i, r in geometry_df.iterrows():
        review = (
            r["Area_Ratio_to_Median"] > 2.5
            or r["Seed_to_Centroid_Distance"] > 250
            or (r["Width_Pixels"] > 0.75 * w and r["Height_Pixels"] > 0.75 * h)
        )
        if review:
            geometry_df.loc[i, "Geometry_QC"] = "REVIEW"

    # Seed status.
    statuses = []
    for _, r in geometry_df.iterrows():
        survey = str(r["Survey_Number"])
        x = int(np.clip(r["Seed_X"], 0, w - 1))
        y = int(np.clip(r["Seed_Y"], 0, h - 1))
        statuses.append("OK" if field_masks[survey][y, x] > 0 else "NOT INSIDE")
    geometry_df["Seed_Status"] = statuses

    return (
        field_pixel_areas,
        field_centroids,
        field_contours,
        field_polygons,
        geometry_df,
        combined_usable,
        total_usable_pixels,
        overlap_pixels,
    )


def _draw_structured_map(map_rgb, field_seeds, field_contours, geometry_df, master_df, output_path):
    overlay_bgr = cv2.cvtColor(np.ascontiguousarray(map_rgb), cv2.COLOR_RGB2BGR)
    h, w = map_rgb.shape[:2]
    title_height = max(55, int(h * 0.07))
    cv2.rectangle(overlay_bgr, (0, 0), (w, title_height), (245, 250, 245), -1)
    cv2.putText(overlay_bgr, "AgriVision - Structured Field Map", (20, max(38, int(title_height * 0.68))),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (30, 90, 60), 2, cv2.LINE_AA)

    merged = master_df.merge(geometry_df, left_on="Survey Number", right_on="Survey_Number", how="left")
    rng = np.random.default_rng(20260909)
    farmer_by_survey = {str(r["Survey Number"]): r for _, r in master_df.iterrows()}

    for _, row in geometry_df.iterrows():
        survey = str(row["Survey_Number"])
        if pd.isna(row.get("Centroid_X")) or pd.isna(row.get("Centroid_Y")):
            continue
        cx, cy = int(round(float(row["Centroid_X"]))), int(round(float(row["Centroid_Y"])))
        contour = field_contours.get(survey)
        if contour is not None:
            color = rng.integers(40, 220, size=3).astype(int)
            cv2.polylines(overlay_bgr, [np.ascontiguousarray(contour, dtype=np.int32)], True,
                          (int(color[2]), int(color[1]), int(color[0])), 3, cv2.LINE_AA)

        farmer = farmer_by_survey.get(survey)
        if farmer is None:
            continue
        lines = [
            f"Survey: {survey}",
            f"Farmer: {farmer['Farmer Name']}",
            f"Land: {farmer['Total land']}",
            f"Crop: {farmer['Field']}",
        ]
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = max(0.42, min(0.62, w / 2100.0))
        line_height = max(19, int(28 * font_scale / 0.55))
        sizes = [cv2.getTextSize(line, font, font_scale, 1)[0] for line in lines]
        box_width = min(max(s[0] for s in sizes) + 22, max(180, int(w * 0.28)))
        box_height = line_height * len(lines) + 18
        x1 = int(np.clip(cx - box_width // 2, 5, max(5, w - box_width - 5)))
        y1 = int(np.clip(cy - box_height // 2, title_height + 5, max(title_height + 5, h - box_height - 5)))
        x2, y2 = x1 + box_width, y1 + box_height

        # Blend only the panel ROI; avoid copying the entire image.
        roi = overlay_bgr[y1:y2, x1:x2]
        panel = np.full_like(roi, (255, 255, 255))
        cv2.addWeighted(panel, 0.78, roi, 0.22, 0, dst=roi)
        cv2.rectangle(overlay_bgr, (x1, y1), (x2, y2), (60, 120, 80), 2)
        cv2.circle(overlay_bgr, (cx, cy), 6, (0, 180, 80), -1)
        for i, line in enumerate(lines):
            cv2.putText(overlay_bgr, line, (x1 + 10, y1 + 22 + i * line_height), font,
                        font_scale, (20, 70, 45), 2 if i == 1 else 1, cv2.LINE_AA)

    cv2.putText(overlay_bgr, "Colored polygons = farmer-linked fields", (18, h - 32),
                cv2.FONT_HERSHEY_SIMPLEX, 0.52, (30, 70, 50), 1, cv2.LINE_AA)
    cv2.imwrite(output_path, overlay_bgr)
    return merged, overlay_bgr


def run_mapping(map_path, farmer_path, output_dir):
    """Run the memory-optimized AgriVision field-mapping pipeline."""
    master_df, road_df, map_bgr, map_rgb, h, w = _load_inputs(map_path, farmer_path, output_dir)

    print("=" * 80)
    print("AGRIVISION FIELD MAPPING - MEMORY OPTIMIZED")
    print(f"Map size: {w} x {h}")
    print(f"Farmer fields: {len(master_df)}")
    print("=" * 80)

    excluded_mask, usable_mask, road_mask = _prepare_masks(map_bgr, output_dir)

    survey_numbers = master_df["Survey Number"].dropna().astype(str).str.strip().tolist()
    survey_map_df = _run_ocr(map_bgr, map_rgb, survey_numbers, h, w, output_dir)

    # Seed data comes only from OCR matches. If OCR misses a field, it remains unmatched.
    if survey_map_df.empty:
        field_seeds = pd.DataFrame(columns=["Survey Number", "Map_X", "Map_Y"])
    else:
        field_seeds = survey_map_df[["Survey Number", "Map_X", "Map_Y"]].copy()
        field_seeds["Survey Number"] = field_seeds["Survey Number"].astype(str).str.strip()
        field_seeds["Map_X"] = pd.to_numeric(field_seeds["Map_X"], errors="coerce")
        field_seeds["Map_Y"] = pd.to_numeric(field_seeds["Map_Y"], errors="coerce")
        field_seeds = field_seeds.dropna(subset=["Survey Number", "Map_X", "Map_Y"])
        field_seeds = field_seeds.drop_duplicates("Survey Number", keep="first").reset_index(drop=True)
        field_seeds["Map_X"] = field_seeds["Map_X"].round().astype(int).clip(0, w - 1)
        field_seeds["Map_Y"] = field_seeds["Map_Y"].round().astype(int).clip(0, h - 1)

    field_masks = {}
    if len(field_seeds):
        surveys, labels = _nearest_seed_labels(field_seeds, h, w, usable_mask)
        for idx, survey in enumerate(surveys, start=1):
            mask = (labels == idx).astype(np.uint8)
            row = field_seeds.iloc[idx - 1]
            mask = _keep_seed_component(mask, int(row["Map_X"]), int(row["Map_Y"]), h, w)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
            mask[excluded_mask > 0] = 0
            field_masks[survey] = np.ascontiguousarray(mask, dtype=np.uint8)
            del mask
        del labels
        gc.collect()
    else:
        surveys = []

    (
        field_pixel_areas,
        field_centroids,
        field_contours,
        field_polygons,
        field_geometry_df,
        combined_usable_mask,
        total_usable_pixels,
        overlap_pixels,
    ) = _build_geometry(field_seeds, field_masks, excluded_mask, h, w)

    # Save geometry tables.
    field_geometry_df.to_csv(os.path.join(output_dir, "field_geometry_v6.csv"), index=False)
    field_geometry_df.to_excel(os.path.join(output_dir, "field_geometry_v6.xlsx"), index=False)
    field_seeds.to_csv(os.path.join(output_dir, "part3_survey_seeds_used.csv"), index=False)

    polygon_records = []
    routing_records = []
    for survey in surveys:
        polygon = field_polygons.get(survey)
        if polygon is None:
            continue
        points = polygon.reshape(-1, 2).tolist()
        polygon_records.append({"Survey_Number": survey, "Polygon_Pixel_Coordinates": str(points)})
        cx, cy = field_centroids[survey]
        routing_records.append({
            "Survey_Number": survey,
            "Centroid_X": cx,
            "Centroid_Y": cy,
            "Pixel_Area": field_pixel_areas[survey],
            "Polygon_Pixel_Coordinates": str(points),
        })

    pd.DataFrame(polygon_records).to_csv(os.path.join(output_dir, "field_polygon_coordinates_v6.csv"), index=False)
    pd.DataFrame(routing_records).to_csv(os.path.join(output_dir, "drone_routing_input_v6.csv"), index=False)

    cv2.imwrite(os.path.join(output_dir, "boundary_evidence_v6.png"), excluded_mask)
    cv2.imwrite(os.path.join(output_dir, "combined_usable_area_v6.png"), combined_usable_mask * 255)
    for survey in surveys:
        safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", str(survey))
        cv2.imwrite(os.path.join(output_dir, f"{safe_name}_field_mask_v6.png"), field_masks[survey] * 255)

    structured_path = os.path.join(output_dir, "structured_field_map.png")
    merged, final_bgr = _draw_structured_map(map_rgb, field_seeds, field_contours, field_geometry_df, master_df, structured_path)
    del merged, final_bgr

    geometry_lookup = {str(r["Survey_Number"]): r for _, r in field_geometry_df.iterrows()}
    ocr_lookup = {str(r["Survey Number"]): r for _, r in survey_map_df.iterrows()}
    farmer_records = []

    for _, farmer in master_df.iterrows():
        survey = str(farmer["Survey Number"])
        geom = geometry_lookup.get(survey, {})
        ocr = ocr_lookup.get(survey, {})
        polygon = field_polygons.get(survey)
        farmer_records.append({
            "survey_number": survey,
            "farmer_name": str(farmer["Farmer Name"]),
            "land": str(farmer["Total land"]),
            "land_acres": _safe_json_value(farmer["Original_Area_Acres"]),
            "mobile_number": str(farmer["Mobile number"]),
            "crop": str(farmer["Field"]),
            "map_matched": survey in ocr_lookup,
            "map_x": _safe_json_value(ocr.get("Map_X", np.nan)),
            "map_y": _safe_json_value(ocr.get("Map_Y", np.nan)),
            "ocr_text": str(ocr.get("OCR_Text", "")) if len(ocr) else "",
            "ocr_confidence": _safe_json_value(ocr.get("OCR_Confidence", np.nan)),
            "match_score": _safe_json_value(ocr.get("Match_Score", np.nan)),
            "pixel_area": _safe_json_value(geom.get("Pixel_Area", np.nan)),
            "centroid_x": _safe_json_value(geom.get("Centroid_X", np.nan)),
            "centroid_y": _safe_json_value(geom.get("Centroid_Y", np.nan)),
            "width_pixels": _safe_json_value(geom.get("Width_Pixels", np.nan)),
            "height_pixels": _safe_json_value(geom.get("Height_Pixels", np.nan)),
            "perimeter_pixels": _safe_json_value(geom.get("Perimeter_Pixels", np.nan)),
            "geometry_qc": str(geom.get("Geometry_QC", "NOT_AVAILABLE")),
            "seed_status": str(geom.get("Seed_Status", "NOT_AVAILABLE")),
            "polygon_coordinates": polygon.reshape(-1, 2).tolist() if polygon is not None else [],
        })

    farmer_field_df = pd.DataFrame(farmer_records)
    farmer_field_df.to_csv(os.path.join(output_dir, "farmer_field_mapping.csv"), index=False)
    farmer_field_df.to_excel(os.path.join(output_dir, "farmer_field_mapping.xlsx"), index=False)

    matched_count = sum(bool(r["map_matched"]) for r in farmer_records)
    review_count = int((field_geometry_df["Geometry_QC"] == "REVIEW").sum()) if not field_geometry_df.empty else 0

    output = {
        "success": True,
        "module": "Field Mapping",
        "structured_image": "structured_field_map.png",
        "farmer_table": "farmer_field_mapping.csv",
        "geometry_table": "field_geometry_v6.csv",
        "polygon_coordinates": "field_polygon_coordinates_v6.csv",
        "summary": {
            "input_map_width": int(w),
            "input_map_height": int(h),
            "total_farmer_fields": int(len(master_df)),
            "survey_numbers_matched": int(matched_count),
            "survey_numbers_unmatched": int(len(master_df) - matched_count),
            "total_usable_pixels": int(total_usable_pixels),
            "overlap_pixels": int(overlap_pixels),
            "fields_requiring_review": int(review_count),
        },
        "fields": farmer_records,
    }

    with open(os.path.join(output_dir, "mapping_result.json"), "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=_safe_json_value)

    # Release large arrays before returning to FastAPI.
    del excluded_mask, usable_mask, road_mask, combined_usable_mask
    del map_bgr, map_rgb
    del field_masks, field_contours, field_polygons, field_seeds
    del master_df, road_df
    gc.collect()

    return output


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AgriVision memory-optimized field mapping")
    parser.add_argument("--image", required=True)
    parser.add_argument("--farmers", required=True)
    parser.add_argument("--output", default="output/field_mapping")
    args = parser.parse_args()
    result = run_mapping(args.image, args.farmers, args.output)
    print(json.dumps(result.get("summary", {}), indent=2, default=_safe_json_value))
