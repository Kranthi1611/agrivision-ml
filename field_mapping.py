
"""
AgriVision Field Mapping backend.

This module converts a cadastral field image + farmer data file into a
structured, farmer-linked field map.

The segmentation/OCR stages are based on the user's SIH_Mapping.ipynb:
- Farmer-data normalization
- Road / pond / red-area exclusion
- Multi-scale OCR
- Fuzzy survey-number matching
- Seed-constrained field partitioning
- Polygon and geometry extraction

The API-facing wrapper adds:
- Farmer details on each mapped field
- JSON result
- CSV/XLSX farmer-field table
- Structured PNG map
"""

import os
import re
import json
import math
from pathlib import Path
from difflib import SequenceMatcher

import cv2
import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    from IPython.display import display
except Exception:
    def display(obj):
        return None

# EasyOCR is imported lazily inside run_mapping so CLI --help and
# syntax checks can run even when OCR dependencies are not installed yet.


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


def _initialize_inputs(map_path, farmer_path, output_dir):
    global OUTPUT_DIR, MAP_PATH, EXCEL_PATH
    global df, farmer_df, road_df, master_df
    global map_bgr, map_rgb, H, W

    OUTPUT_DIR = str(output_dir)
    MAP_PATH = str(map_path)
    EXCEL_PATH = str(farmer_path)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    suffix = Path(EXCEL_PATH).suffix.lower()

    if suffix in [".xlsx", ".xls"]:
        df = pd.read_excel(EXCEL_PATH)
    elif suffix == ".csv":
        df = pd.read_csv(EXCEL_PATH)
    else:
        raise ValueError(
            "Farmer data must be .csv, .xlsx or .xls."
        )

    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
    )

    required_columns = [
        "Survey Number",
        "Farmer Name",
        "Total land",
        "Mobile number",
        "Field"
    ]

    missing_columns = [
        c for c in required_columns
        if c not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "Missing required farmer-data columns: "
            + ", ".join(missing_columns)
        )

    df["Survey Number"] = (
        df["Survey Number"]
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"\.0$", "", regex=True)
    )

    df["Farmer Name"] = (
        df["Farmer Name"]
        .astype(str)
        .str.strip()
    )

    df["Field"] = (
        df["Field"]
        .astype(str)
        .str.strip()
    )

    df["Mobile number"] = (
        df["Mobile number"]
        .astype(str)
        .str.strip()
    )

    def is_road_row(row):
        values = [
            str(row["Survey Number"]).lower(),
            str(row["Farmer Name"]).lower(),
            str(row["Total land"]).lower(),
            str(row["Mobile number"]).lower(),
            str(row["Field"]).lower()
        ]
        return any("road" in value for value in values)

    df["Is_Road"] = df.apply(
        is_road_row,
        axis=1
    )

    road_df = df[
        df["Is_Road"]
    ].copy()

    farmer_df = df[
        ~df["Is_Road"]
    ].copy()

    def land_to_acres(value):
        if pd.isna(value):
            return np.nan

        text = (
            str(value)
            .lower()
            .strip()
            .replace(",", "")
        )

        match = re.search(
            r"([0-9]*\.?[0-9]+)\s*ac",
            text
        )

        if match:
            return float(match.group(1))

        match = re.search(
            r"([0-9]*\.?[0-9]+)\s*cent",
            text
        )

        if match:
            return float(match.group(1)) / 100.0

        match = re.search(
            r"([0-9]*\.?[0-9]+)",
            text
        )

        if match:
            return float(match.group(1))

        return np.nan

    farmer_df["Original_Area_Acres"] = (
        farmer_df["Total land"]
        .apply(land_to_acres)
    )

    master_df = farmer_df[
        [
            "Survey Number",
            "Farmer Name",
            "Total land",
            "Original_Area_Acres",
            "Mobile number",
            "Field"
        ]
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

    map_bgr = cv2.imread(
        MAP_PATH
    )

    if map_bgr is None:
        raise ValueError(
            "OpenCV could not read the uploaded field image."
        )

    map_rgb = cv2.cvtColor(
        map_bgr,
        cv2.COLOR_BGR2RGB
    )

    H, W = map_rgb.shape[:2]


def _prepare_map_cleaning_masks():
    """Create the Part-2 exclusion/usable masks for standalone execution."""
    global map_hsv, orange_mask, blue_mask, red_mask
    global orange_mask_clean, blue_mask_clean, red_mask_clean
    global excluded_mask, usable_mask, road_mask

    print("\n" + "=" * 80)
    print("PART-2 : AUTOMATIC MAP CLEANING")
    print("=" * 80)
    print(f"Map path : {MAP_PATH}")
    print(f"Map size : {W} x {H}")

    map_hsv = cv2.cvtColor(map_bgr, cv2.COLOR_BGR2HSV)

    # Orange = road
    orange_mask = cv2.inRange(
        map_hsv,
        np.array([5, 80, 80], dtype=np.uint8),
        np.array([30, 255, 255], dtype=np.uint8)
    )

    # Blue = pond / water
    blue_mask = cv2.inRange(
        map_hsv,
        np.array([85, 60, 50], dtype=np.uint8),
        np.array([140, 255, 255], dtype=np.uint8)
    )

    # Red = not usable
    red_1 = cv2.inRange(
        map_hsv,
        np.array([0, 80, 70], dtype=np.uint8),
        np.array([10, 255, 255], dtype=np.uint8)
    )
    red_2 = cv2.inRange(
        map_hsv,
        np.array([170, 80, 70], dtype=np.uint8),
        np.array([180, 255, 255], dtype=np.uint8)
    )
    red_mask = cv2.bitwise_or(red_1, red_2)

    kernel = np.ones((5, 5), np.uint8)

    orange_mask_clean = cv2.morphologyEx(orange_mask, cv2.MORPH_OPEN, kernel)
    orange_mask_clean = cv2.morphologyEx(orange_mask_clean, cv2.MORPH_CLOSE, kernel)

    blue_mask_clean = cv2.morphologyEx(blue_mask, cv2.MORPH_OPEN, kernel)
    blue_mask_clean = cv2.morphologyEx(blue_mask_clean, cv2.MORPH_CLOSE, kernel)

    red_mask_clean = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, kernel)
    red_mask_clean = cv2.morphologyEx(red_mask_clean, cv2.MORPH_CLOSE, kernel)

    excluded_mask = cv2.bitwise_or(orange_mask_clean, blue_mask_clean)
    excluded_mask = cv2.bitwise_or(excluded_mask, red_mask_clean)
    excluded_mask = np.ascontiguousarray(excluded_mask, dtype=np.uint8)

    usable_mask = cv2.bitwise_not(excluded_mask)
    usable_mask = np.ascontiguousarray(usable_mask, dtype=np.uint8)

    # Keep a binary road mask available for downstream modules.
    road_mask = (orange_mask_clean > 0).astype(np.uint8)

    # Save useful debugging masks.
    cv2.imwrite(os.path.join(OUTPUT_DIR, "road_mask.png"), orange_mask_clean)
    cv2.imwrite(os.path.join(OUTPUT_DIR, "pond_mask.png"), blue_mask_clean)
    cv2.imwrite(os.path.join(OUTPUT_DIR, "red_not_use_mask.png"), red_mask_clean)
    cv2.imwrite(os.path.join(OUTPUT_DIR, "excluded_mask.png"), excluded_mask)
    cv2.imwrite(os.path.join(OUTPUT_DIR, "usable_land_mask.png"), usable_mask)

    cleaned_map = map_rgb.copy()
    cleaned_map[excluded_mask > 0] = [0, 0, 0]
    cv2.imwrite(
        os.path.join(OUTPUT_DIR, "cleaned_map.png"),
        cv2.cvtColor(cleaned_map, cv2.COLOR_RGB2BGR)
    )

    total_pixels = H * W
    print(f"Road pixels        : {np.count_nonzero(orange_mask_clean):,}")
    print(f"Pond pixels        : {np.count_nonzero(blue_mask_clean):,}")
    print(f"Red/not-use pixels : {np.count_nonzero(red_mask_clean):,}")
    print(f"Excluded pixels    : {np.count_nonzero(excluded_mask):,}")
    print(f"Usable pixels      : {np.count_nonzero(usable_mask):,}")
    print(f"Usable percentage  : {(np.count_nonzero(usable_mask) / total_pixels) * 100:.2f}%")
    print("✓ Part-2 masks prepared.")


def run_mapping(map_path, farmer_path, output_dir):
    # Part-4 reuses the masks created by Part-2. Because this function
    # also normalizes excluded_mask later, explicitly bind these names
    # to the module-level variables created by _prepare_map_cleaning_masks().
    global excluded_mask, usable_mask, road_mask

    _initialize_inputs(
        map_path,
        farmer_path,
        output_dir
    )
    # The original notebook expected Part-1 and Part-2 cells to have
    # already been executed. The backend runs this file directly, so
    # prepare those variables here before executing Part-3/Part-4.
    _prepare_map_cleaning_masks()

    # ============================================================
    # PART-3 FIXED
    # AUTOMATIC SURVEY NUMBER -> MAP MATCHING
    # ============================================================
    #
    # IMPORTANT:
    # Survey numbers are taken ONLY from the XLSX.
    #
    # No survey number is hard-coded.
    # No survey order is assumed.
    #
    # Improvements:
    #   1. Multi-scale OCR
    #   2. Multiple image preprocessing methods
    #   3. Automatic detection of yellow survey labels
    #   4. OCR on detected label regions
    #   5. Fuzzy matching against XLSX survey numbers
    #   6. Duplicate handling
    #
    # ============================================================

    import cv2
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    import re
    import os
    from difflib import SequenceMatcher

    print("=" * 80)
    print("PART-3 : FIXED AUTOMATIC SURVEY NUMBER MAP MATCHING")
    print("=" * 80)


    # ============================================================
    # 1. CHECK PART-1 AND PART-2
    # ============================================================

    required_variables = [
        "master_df",
        "map_rgb",
        "map_bgr",
        "H",
        "W",
        "excluded_mask",
        "usable_mask"
    ]

    missing = [x for x in required_variables if x not in globals()]

    if missing:
        raise RuntimeError(
            "Standalone initialization failed. Missing variables: "
            + ", ".join(missing)
        )


    # ============================================================
    # 2. READ SURVEY NUMBERS DIRECTLY FROM XLSX
    # ============================================================
    #
    # THIS IS THE SOURCE OF TRUTH.
    #
    # We do not create a manual list.
    # ============================================================

    excel_survey_numbers = (
        master_df["Survey Number"]
        .dropna()
        .astype(str)
        .str.strip()
    )

    # Remove blank values
    excel_survey_numbers = [
        x for x in excel_survey_numbers
        if x != ""
    ]

    print("\nSurvey numbers obtained from XLSX:")

    for survey in excel_survey_numbers:
        print("   ", survey)

    print(
        f"\nTotal surveys from XLSX: "
        f"{len(excel_survey_numbers)}"
    )


    # ============================================================
    # 3. NORMALIZATION
    # ============================================================

    def normalize_text(text):

        if text is None:
            return ""

        text = str(text).upper().strip()

        # Remove spaces
        text = re.sub(r"\s+", "", text)

        # Remove OCR punctuation
        text = text.replace("-", "")
        text = text.replace("_", "")
        text = text.replace(".", "")
        text = text.replace("/", "")

        return text


    def ocr_normalize(text):

        text = normalize_text(text)

        # Common OCR substitutions
        replacements = {
            "O": "0",
            "I": "1",
            "L": "1"
        }

        result = ""

        for ch in text:

            result += replacements.get(
                ch,
                ch
            )

        return result


    # Original normalized surveys
    survey_normalized = {
        normalize_text(s): s
        for s in excel_survey_numbers
    }

    # OCR-normalized surveys
    survey_ocr_normalized = {
        ocr_normalize(s): s
        for s in excel_survey_numbers
    }


    # ============================================================
    # 4. INSTALL / IMPORT EASY OCR
    # ============================================================

    try:

        import easyocr

    except ImportError:

        print("\nInstalling EasyOCR...")


        import easyocr


    # ============================================================
    # 5. INITIALIZE OCR
    # ============================================================

    print("\nInitializing OCR...")

    reader = easyocr.Reader(
        ["en"],
        gpu=False
    )

    print("OCR ready.")


    # ============================================================
    # 6. CREATE DIFFERENT MAP VERSIONS
    # ============================================================

    original = map_bgr.copy()

    gray = cv2.cvtColor(
        original,
        cv2.COLOR_BGR2GRAY
    )


    # ------------------------------------------------------------
    # Contrast enhancement
    # ------------------------------------------------------------

    clahe = cv2.createCLAHE(
        clipLimit=2.5,
        tileGridSize=(8, 8)
    )

    enhanced = clahe.apply(gray)


    # ------------------------------------------------------------
    # Threshold versions
    # ------------------------------------------------------------

    _, binary = cv2.threshold(
        enhanced,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )


    adaptive = cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        7
    )


    # ============================================================
    # 7. AUTOMATIC YELLOW LABEL DETECTION
    # ============================================================
    #
    # Your map has survey labels highlighted in yellow.
    #
    # Instead of searching for "4A" manually, we detect the
    # yellow label regions automatically.
    #
    # This works regardless of survey number.
    # ============================================================

    hsv = cv2.cvtColor(
        original,
        cv2.COLOR_BGR2HSV
    )


    # Yellow HSV range
    lower_yellow = np.array(
        [15, 50, 80]
    )

    upper_yellow = np.array(
        [45, 255, 255]
    )

    yellow_mask = cv2.inRange(
        hsv,
        lower_yellow,
        upper_yellow
    )


    # Clean mask
    yellow_kernel = np.ones(
        (3, 3),
        np.uint8
    )

    yellow_mask = cv2.morphologyEx(
        yellow_mask,
        cv2.MORPH_OPEN,
        yellow_kernel
    )

    yellow_mask = cv2.morphologyEx(
        yellow_mask,
        cv2.MORPH_CLOSE,
        yellow_kernel
    )


    # ============================================================
    # 8. FIND YELLOW LABEL COMPONENTS
    # ============================================================

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        yellow_mask,
        connectivity=8
    )


    yellow_boxes = []


    for i in range(1, num_labels):

        x = stats[i, cv2.CC_STAT_LEFT]
        y = stats[i, cv2.CC_STAT_TOP]

        w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]

        area = stats[i, cv2.CC_STAT_AREA]

        # Ignore tiny noise
        if area < 5:
            continue

        # Ignore extremely large regions
        if area > 5000:
            continue

        # Keep plausible label dimensions
        if w >= 3 and h >= 3:

            yellow_boxes.append(
                (x, y, w, h, area)
            )


    print(
        f"\nAutomatically detected "
        f"{len(yellow_boxes)} yellow regions."
    )


    # ============================================================
    # 9. VISUALIZE YELLOW DETECTIONS
    # ============================================================

    debug_yellow = map_rgb.copy()

    for i, (x, y, w, h, area) in enumerate(yellow_boxes):

        cv2.rectangle(
            debug_yellow,
            (x, y),
            (x + w, y + h),
            (255, 255, 0),
            2
        )

        cv2.putText(
            debug_yellow,
            str(i + 1),
            (x, max(10, y - 3)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 0, 255),
            1
        )


    plt.figure(figsize=(18, 10))

    plt.imshow(debug_yellow)

    plt.title(
        "Automatically Detected Yellow Label Regions"
    )

    plt.axis("off")

    plt.close('all')


    # ============================================================
    # 10. OCR EACH YELLOW REGION
    # ============================================================
    #
    # Expand each box because the black survey text may extend
    # slightly outside the yellow background.
    # ============================================================

    label_ocr_results = []


    padding_x = 15
    padding_y = 12


    for idx, (x, y, w, h, area) in enumerate(
        yellow_boxes
    ):

        x1 = max(
            0,
            x - padding_x
        )

        y1 = max(
            0,
            y - padding_y
        )

        x2 = min(
            W,
            x + w + padding_x
        )

        y2 = min(
            H,
            y + h + padding_y
        )


        crop = original[
            y1:y2,
            x1:x2
        ]


        if crop.size == 0:
            continue


        # --------------------------------------------------------
        # Upscale crop
        # --------------------------------------------------------

        crop_big = cv2.resize(
            crop,
            None,
            fx=5,
            fy=5,
            interpolation=cv2.INTER_CUBIC
        )


        # --------------------------------------------------------
        # Run OCR
        # --------------------------------------------------------

        try:

            results = reader.readtext(
                crop_big,
                detail=1,
                paragraph=False,
                allowlist="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-"
            )

        except Exception as e:

            print(
                f"OCR error in region {idx}: {e}"
            )

            continue


        # --------------------------------------------------------
        # Store every OCR result
        # --------------------------------------------------------

        for result in results:

            bbox, text, confidence = result

            text = str(text).strip()

            if text == "":
                continue


            label_ocr_results.append({

                "Region_ID": idx + 1,

                "OCR_Text": text,

                "Confidence": float(
                    confidence
                ),

                "Map_X": int(
                    x + w / 2
                ),

                "Map_Y": int(
                    y + h / 2
                ),

                "Crop_X1": x1,
                "Crop_Y1": y1,
                "Crop_X2": x2,
                "Crop_Y2": y2

            })


    # ============================================================
    # 11. OCR RESULTS
    # ============================================================

    yellow_ocr_df = pd.DataFrame(
        label_ocr_results
    )


    print("\n" + "=" * 80)
    print("OCR FROM AUTOMATICALLY DETECTED LABELS")
    print("=" * 80)


    if len(yellow_ocr_df) > 0:

        display(
            yellow_ocr_df[
                [
                    "Region_ID",
                    "OCR_Text",
                    "Confidence",
                    "Map_X",
                    "Map_Y"
                ]
            ]
        )

    else:

        print(
            "No text detected inside yellow regions."
        )


    # ============================================================
    # 12. ALSO RUN OCR ON FULL MAP
    # ============================================================
    #
    # Yellow-region OCR is our main method.
    # Full-map OCR is a backup.
    # ============================================================

    all_ocr_records = []


    map_versions = {

        "original": original,

        "enhanced": enhanced,

        "binary": binary,

        "adaptive": adaptive
    }


    scale_factors = [
        2,
        3
    ]


    for version_name, image in map_versions.items():

        for scale in scale_factors:

            print(
                f"Running OCR: "
                f"{version_name}, scale={scale}"
            )


            resized = cv2.resize(
                image,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_CUBIC
            )


            try:

                results = reader.readtext(
                    resized,
                    detail=1,
                    paragraph=False,
                    allowlist="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-"
                )

            except Exception:

                continue


            for result in results:

                bbox, text, confidence = result

                text = str(text).strip()

                if text == "":
                    continue


                points = np.array(
                    bbox,
                    dtype=np.float32
                )

                points /= scale


                x_min = int(
                    np.min(points[:, 0])
                )

                x_max = int(
                    np.max(points[:, 0])
                )

                y_min = int(
                    np.min(points[:, 1])
                )

                y_max = int(
                    np.max(points[:, 1])
                )


                center_x = int(
                    (x_min + x_max) / 2
                )

                center_y = int(
                    (y_min + y_max) / 2
                )


                all_ocr_records.append({

                    "Source": version_name,

                    "Scale": scale,

                    "OCR_Text": text,

                    "Confidence": float(
                        confidence
                    ),

                    "Map_X": center_x,

                    "Map_Y": center_y

                })


    full_ocr_df = pd.DataFrame(
        all_ocr_records
    )


    # ============================================================
    # 13. COMBINE OCR SOURCES
    # ============================================================

    combined_ocr = []


    # Yellow-region OCR
    if len(yellow_ocr_df) > 0:

        for _, row in yellow_ocr_df.iterrows():

            combined_ocr.append({

                "Source": "yellow_region",

                "OCR_Text": row["OCR_Text"],

                "Confidence": row["Confidence"],

                "Map_X": row["Map_X"],

                "Map_Y": row["Map_Y"]

            })


    # Full map OCR
    if len(full_ocr_df) > 0:

        for _, row in full_ocr_df.iterrows():

            combined_ocr.append({

                "Source": row["Source"],

                "OCR_Text": row["OCR_Text"],

                "Confidence": row["Confidence"],

                "Map_X": row["Map_X"],

                "Map_Y": row["Map_Y"]

            })


    combined_ocr_df = pd.DataFrame(
        combined_ocr
    )


    # ============================================================
    # 14. FUZZY MATCH FUNCTION
    # ============================================================

    def similarity(a, b):

        return SequenceMatcher(
            None,
            a,
            b
        ).ratio()


    def find_best_survey_match(
        ocr_text,
        threshold=0.55
    ):

        normalized = ocr_normalize(
            ocr_text
        )

        if normalized == "":
            return None, 0


        best_survey = None
        best_score = 0


        for survey in excel_survey_numbers:

            survey_norm = ocr_normalize(
                survey
            )

            score = similarity(
                normalized,
                survey_norm
            )


            if score > best_score:

                best_score = score

                best_survey = survey


        if best_score >= threshold:

            return (
                best_survey,
                best_score
            )


        return None, best_score


    # ============================================================
    # 15. MATCH ALL OCR RESULTS AGAINST XLSX
    # ============================================================

    candidate_matches = []


    if len(combined_ocr_df) > 0:

        for _, row in combined_ocr_df.iterrows():

            survey, score = find_best_survey_match(
                row["OCR_Text"]
            )


            if survey is not None:

                candidate_matches.append({

                    "Survey Number": survey,

                    "OCR_Text": row["OCR_Text"],

                    "OCR_Confidence": row["Confidence"],

                    "Match_Score": score,

                    "Map_X": int(
                        row["Map_X"]
                    ),

                    "Map_Y": int(
                        row["Map_Y"]
                    ),

                    "Source": row["Source"]

                })


    candidate_df = pd.DataFrame(
        candidate_matches
    )


    # ============================================================
    # 16. KEEP BEST MATCH FOR EACH SURVEY
    # ============================================================

    if len(candidate_df) > 0:

        candidate_df["Combined_Score"] = (
            candidate_df["OCR_Confidence"]
            *
            candidate_df["Match_Score"]
        )


        survey_map_df = (
            candidate_df
            .sort_values(
                "Combined_Score",
                ascending=False
            )
            .drop_duplicates(
                subset=["Survey Number"],
                keep="first"
            )
            .reset_index(drop=True)
        )

    else:

        survey_map_df = pd.DataFrame(
            columns=[
                "Survey Number",
                "OCR_Text",
                "OCR_Confidence",
                "Match_Score",
                "Map_X",
                "Map_Y",
                "Source"
            ]
        )


    # ============================================================
    # 17. FINAL MATCH TABLE
    # ============================================================

    print("\n" + "=" * 80)
    print("FINAL SURVEY NUMBER MATCHES")
    print("=" * 80)


    if len(survey_map_df) > 0:

        display(
            survey_map_df[
                [
                    "Survey Number",
                    "OCR_Text",
                    "OCR_Confidence",
                    "Match_Score",
                    "Map_X",
                    "Map_Y",
                    "Source"
                ]
            ]
            .sort_values(
                "Survey Number"
            )
        )

    else:

        print(
            "No survey numbers matched."
        )


    # ============================================================
    # 18. CHECK UNMATCHED SURVEYS
    # ============================================================

    matched_surveys = set()


    if len(survey_map_df) > 0:

        matched_surveys = set(
            survey_map_df[
                "Survey Number"
            ]
        )


    unmatched_surveys = [

        survey

        for survey in excel_survey_numbers

        if survey not in matched_surveys

    ]


    print("\n" + "=" * 80)
    print("MATCH SUMMARY")
    print("=" * 80)

    print(
        "Survey numbers in XLSX :",
        len(excel_survey_numbers)
    )

    print(
        "Survey numbers matched  :",
        len(matched_surveys)
    )

    print(
        "Survey numbers unmatched:",
        len(unmatched_surveys)
    )


    if unmatched_surveys:

        print("\nUnmatched surveys:")

        for survey in unmatched_surveys:

            print(
                "  ✗",
                survey
            )

    else:

        print(
            "\n✓ ALL XLSX SURVEY NUMBERS MATCHED."
        )


    # ============================================================
    # 19. VISUALIZE ALL MATCHED SURVEYS
    # ============================================================

    plt.figure(
        figsize=(18, 10)
    )

    plt.imshow(
        map_rgb
    )


    for _, row in survey_map_df.iterrows():

        x = int(
            row["Map_X"]
        )

        y = int(
            row["Map_Y"]
        )

        survey = row[
            "Survey Number"
        ]


        # Marker
        plt.scatter(
            x,
            y,
            s=120,
            facecolors="none",
            edgecolors="yellow",
            linewidths=2
        )


        # Label
        plt.text(
            x + 8,
            y - 8,
            str(survey),
            fontsize=12,
            fontweight="bold",
            color="yellow",
            bbox=dict(
                facecolor="black",
                alpha=0.75,
                pad=2
            )
        )


    plt.title(
        "Survey Numbers Matched from XLSX to Map"
    )

    plt.axis("off")

    plt.close('all')


    # ============================================================
    # 20. CREATE SURVEY SEED MASK
    # ============================================================

    survey_seed_mask = np.zeros(
        (H, W),
        dtype=np.uint8
    )


    for _, row in survey_map_df.iterrows():

        x = int(
            row["Map_X"]
        )

        y = int(
            row["Map_Y"]
        )


        if (
            0 <= x < W
            and
            0 <= y < H
        ):

            cv2.circle(
                survey_seed_mask,
                (x, y),
                10,
                255,
                -1
            )


    # ============================================================
    # 21. CREATE OUTPUT DIRECTORY
    # ============================================================

    PART3_DIR = os.path.join(OUTPUT_DIR, "ocr_matching")

    os.makedirs(
        PART3_DIR,
        exist_ok=True
    )


    # ============================================================
    # 22. SAVE OCR DATA
    # ============================================================

    combined_ocr_df.to_csv(
        os.path.join(
            PART3_DIR,
            "combined_ocr_results.csv"
        ),
        index=False
    )


    yellow_ocr_df.to_csv(
        os.path.join(
            PART3_DIR,
            "yellow_region_ocr.csv"
        ),
        index=False
    )


    candidate_df.to_csv(
        os.path.join(
            PART3_DIR,
            "survey_match_candidates.csv"
        ),
        index=False
    )


    survey_map_df.to_csv(
        os.path.join(
            PART3_DIR,
            "survey_map_matches.csv"
        ),
        index=False
    )


    cv2.imwrite(
        os.path.join(
            PART3_DIR,
            "yellow_label_mask.png"
        ),
        yellow_mask
    )


    cv2.imwrite(
        os.path.join(
            PART3_DIR,
            "survey_seed_mask.png"
        ),
        survey_seed_mask
    )


    # ============================================================
    # 23. MERGE MAP INFORMATION WITH FARMER DATA
    # ============================================================

    columns_to_remove = [

        "Map_Matched",
        "Map_X",
        "Map_Y",
        "Map_Area_Pixels",
        "Map_Area_Acres",
        "Usable_Area_Acres",
        "OCR_Confidence"

    ]


    master_for_merge = master_df.drop(
        columns=[
            c
            for c in columns_to_remove
            if c in master_df.columns
        ],
        errors="ignore"
    )


    if len(survey_map_df) > 0:

        map_info = survey_map_df[
            [
                "Survey Number",
                "Map_X",
                "Map_Y",
                "OCR_Confidence"
            ]
        ].copy()


        map_info["Map_Matched"] = True


    else:

        map_info = pd.DataFrame(
            columns=[
                "Survey Number",
                "Map_X",
                "Map_Y",
                "OCR_Confidence",
                "Map_Matched"
            ]
        )


    farmer_map_df = master_for_merge.merge(
        map_info,
        on="Survey Number",
        how="left"
    )


    farmer_map_df[
        "Map_Matched"
    ] = (
        farmer_map_df[
            "Map_Matched"
        ]
        .fillna(False)
        .astype(bool)
    )


    # ============================================================
    # 24. SAVE FINAL FARMER-MAP DATA
    # ============================================================

    farmer_map_df.to_csv(
        os.path.join(
            PART3_DIR,
            "farmer_map_data_part3.csv"
        ),
        index=False
    )


    farmer_map_df.to_excel(
        os.path.join(
            PART3_DIR,
            "farmer_map_data_part3.xlsx"
        ),
        index=False
    )


    # ============================================================
    # 25. DISPLAY FINAL TABLE
    # ============================================================

    print("\n" + "=" * 80)
    print("FINAL FARMER + MAP DATA")
    print("=" * 80)


    display(
        farmer_map_df[
            [
                "Survey Number",
                "Farmer Name",
                "Total land",
                "Mobile number",
                "Field",
                "Map_Matched",
                "Map_X",
                "Map_Y",
                "OCR_Confidence"
            ]
        ]
    )


    # ============================================================
    # 26. FINAL MESSAGE
    # ============================================================

    print("\n" + "=" * 80)
    print("PART-3 COMPLETED")
    print("=" * 80)

    print(
        "\n✓ Survey numbers were obtained from XLSX."
    )

    print(
        "✓ No survey number was hard-coded."
    )

    print(
        "✓ No Excel order was used as map/drone order."
    )

    print(
        "✓ Multiple OCR methods were used."
    )

    print(
        "✓ Yellow survey labels were detected automatically."
    )

    print(
        "✓ OCR results were fuzzy-matched against XLSX surveys."
    )

    print(
        "\nOutput folder:"
    )

    print(
        PART3_DIR
    )

    print(
        "\nNext step:"
    )

    print(
        "PART-4 = automatic field-boundary / polygon extraction."
    )

    # ============================================================
    # PART-4 V6 FIXED
    # AUTOMATIC SEED-CONSTRAINED FIELD POLYGON EXTRACTION
    # ============================================================
    #
    # IMPORTANT
    # ------------------------------------------------------------
    # 1. Survey numbers come dynamically from Part-3.
    # 2. No survey number is hard-coded.
    # 3. No survey order is assumed.
    # 4. XLSX acreage is NOT used.
    # 5. Map is used for field geometry.
    # 6. Orange = road
    # 7. Blue   = pond
    # 8. Red    = not usable
    # 9. NO cv2.circle() is used for seed locking.
    #
    # OUTPUT:
    #   - field masks
    #   - field polygons
    #   - polygon coordinates
    #   - field geometry
    #   - drone routing input
    #
    # ============================================================

    import cv2
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt

    import os
    import re
    import math


    print("=" * 100)
    print("PART-4 V6 FIXED : AUTOMATIC FIELD POLYGON EXTRACTION")
    print("=" * 100)



    print(
        f"\nMap width  : {W}"
    )

    print(
        f"Map height : {H}"
    )


    # ============================================================
    # 2. READ SURVEY NUMBERS AND SEEDS FROM PART-3
    # ============================================================
    #
    # NOTHING IS HARD-CODED.
    # ============================================================

    field_seeds = survey_map_df[
        [
            "Survey Number",
            "Map_X",
            "Map_Y"
        ]
    ].copy()


    # Clean survey numbers
    field_seeds[
        "Survey Number"
    ] = (
        field_seeds[
            "Survey Number"
        ]
        .astype(str)
        .str.strip()
    )


    # Convert coordinates
    field_seeds[
        "Map_X"
    ] = pd.to_numeric(
        field_seeds[
            "Map_X"
        ],
        errors="coerce"
    )


    field_seeds[
        "Map_Y"
    ] = pd.to_numeric(
        field_seeds[
            "Map_Y"
        ],
        errors="coerce"
    )


    # Remove invalid seeds
    field_seeds = field_seeds.dropna(
        subset=[
            "Survey Number",
            "Map_X",
            "Map_Y"
        ]
    ).copy()


    # Remove duplicate surveys
    field_seeds = field_seeds.drop_duplicates(
        subset=[
            "Survey Number"
        ],
        keep="first"
    ).reset_index(
        drop=True
    )


    # Convert to integer
    field_seeds[
        "Map_X"
    ] = (
        field_seeds[
            "Map_X"
        ]
        .round()
        .astype(int)
    )


    field_seeds[
        "Map_Y"
    ] = (
        field_seeds[
            "Map_Y"
        ]
        .round()
        .astype(int)
    )


    # ============================================================
    # 3. CLIP SEEDS TO MAP
    # ============================================================

    field_seeds[
        "Map_X"
    ] = field_seeds[
        "Map_X"
    ].clip(
        0,
        W - 1
    )


    field_seeds[
        "Map_Y"
    ] = field_seeds[
        "Map_Y"
    ].clip(
        0,
        H - 1
    )


    survey_list = field_seeds[
        "Survey Number"
    ].tolist()


    print(
        "\nSurvey seeds obtained from Part-3:"
    )


    display(
        field_seeds
    )


    print(
        f"\nNumber of fields: "
        f"{len(survey_list)}"
    )


    # ============================================================
    # 4. PREPARE MAP
    # ============================================================

    rgb = np.ascontiguousarray(
        map_rgb.copy()
    )


    bgr = np.ascontiguousarray(
        map_bgr.copy()
    )


    gray = cv2.cvtColor(
        bgr,
        cv2.COLOR_BGR2GRAY
    )


    gray = np.ascontiguousarray(
        gray
    )


    excluded_mask = np.ascontiguousarray(
        excluded_mask.astype(
            np.uint8
        )
    )


    # ============================================================
    # 5. AGRICULTURAL ANALYSIS MASK
    # ============================================================

    agri_mask = np.ones(
        (
            H,
            W
        ),
        dtype=np.uint8
    )


    agri_mask[
        excluded_mask > 0
    ] = 0


    # ============================================================
    # 6. SUPPRESS EXCLUDED AREAS
    # ============================================================

    analysis_gray = gray.copy()


    analysis_gray[
        excluded_mask > 0
    ] = 255


    analysis_gray = np.ascontiguousarray(
        analysis_gray
    )


    # ============================================================
    # 7. ADAPTIVE THRESHOLD
    # ============================================================

    adaptive = cv2.adaptiveThreshold(
        analysis_gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        21,
        7
    )


    adaptive = np.ascontiguousarray(
        adaptive
    )


    adaptive[
        excluded_mask > 0
    ] = 0


    # ============================================================
    # 8. CANNY EDGES
    # ============================================================

    edges = cv2.Canny(
        analysis_gray,
        25,
        100
    )


    edges = np.ascontiguousarray(
        edges
    )


    edges[
        excluded_mask > 0
    ] = 0


    # ============================================================
    # 9. COMBINE EDGE INFORMATION
    # ============================================================

    boundary_candidates = cv2.bitwise_or(
        adaptive,
        edges
    )


    boundary_candidates = np.ascontiguousarray(
        boundary_candidates
    )


    # ============================================================
    # 10. CONNECT SMALL BOUNDARY GAPS
    # ============================================================

    close_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (
            3,
            3
        )
    )


    boundary_candidates = cv2.morphologyEx(
        boundary_candidates,
        cv2.MORPH_CLOSE,
        close_kernel
    )


    boundary_candidates = np.ascontiguousarray(
        boundary_candidates
    )


    # ============================================================
    # 11. LONG HORIZONTAL STRUCTURES
    # ============================================================

    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (
            max(
                15,
                W // 45
            ),
            2
        )
    )


    horizontal = cv2.morphologyEx(
        boundary_candidates,
        cv2.MORPH_OPEN,
        horizontal_kernel
    )


    horizontal = np.ascontiguousarray(
        horizontal
    )


    # ============================================================
    # 12. LONG VERTICAL STRUCTURES
    # ============================================================

    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (
            2,
            max(
                15,
                H // 25
            )
        )
    )


    vertical = cv2.morphologyEx(
        boundary_candidates,
        cv2.MORPH_OPEN,
        vertical_kernel
    )


    vertical = np.ascontiguousarray(
        vertical
    )


    structural = cv2.bitwise_or(
        horizontal,
        vertical
    )


    structural = np.ascontiguousarray(
        structural
    )


    # ============================================================
    # 13. HOUGH LINE DETECTION
    # ============================================================

    hough_lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=25,
        minLineLength=max(
            50,
            int(W * 0.035)
        ),
        maxLineGap=20
    )


    hough_mask = np.zeros(
        (
            H,
            W
        ),
        dtype=np.uint8
    )


    if hough_lines is not None:

        for line in hough_lines:

            x1, y1, x2, y2 = np.asarray(line).reshape(-1)[:4]


            length = math.hypot(
                x2 - x1,
                y2 - y1
            )


            angle = math.degrees(
                math.atan2(
                    y2 - y1,
                    x2 - x1
                )
            )


            # Normalize angle
            while angle < -90:

                angle += 180


            while angle > 90:

                angle -= 180


            near_horizontal = (
                abs(angle) <= 12
            )


            near_vertical = (
                abs(
                    abs(angle) - 90
                ) <= 12
            )


            # Keep reasonably long cadastral-like lines
            if (
                length >= 80
                and
                (
                    near_horizontal
                    or
                    near_vertical
                    or
                    length >= 150
                )
            ):

                cv2.line(
                    hough_mask,
                    (
                        int(x1),
                        int(y1)
                    ),
                    (
                        int(x2),
                        int(y2)
                    ),
                    255,
                    2
                )


    hough_mask = np.ascontiguousarray(
        hough_mask
    )


    # ============================================================
    # 14. FINAL BOUNDARY EVIDENCE
    # ============================================================

    boundary_mask = cv2.bitwise_or(
        structural,
        hough_mask
    )


    boundary_mask = np.ascontiguousarray(
        boundary_mask
    )


    # Small boundary gap closing
    boundary_mask = cv2.morphologyEx(
        boundary_mask,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (
                3,
                3
            )
        )
    )


    boundary_mask = np.ascontiguousarray(
        boundary_mask
    )


    # ============================================================
    # 15. EXCLUSION AREAS AS BARRIERS
    # ============================================================

    boundary_mask[
        excluded_mask > 0
    ] = 255


    # ============================================================
    # 16. IMAGE BORDER AS BOUNDARY
    # ============================================================

    border = max(
        3,
        int(
            min(H, W) * 0.008
        )
    )


    boundary_mask[
        :border,
        :
    ] = 255


    boundary_mask[
        H - border:H,
        :
    ] = 255


    boundary_mask[
        :,
        :border
    ] = 255


    boundary_mask[
        :,
        W - border:W
    ] = 255


    # ============================================================
    # 17. DISPLAY DETECTED BOUNDARIES
    # ============================================================

    boundary_debug = rgb.copy()


    boundary_debug[
        boundary_mask > 0
    ] = np.array(
        [
            255,
            0,
            255
        ],
        dtype=np.uint8
    )


    plt.figure(
        figsize=(20, 11)
    )

    plt.imshow(
        boundary_debug
    )

    plt.title(
        "PART-4 V6 - Detected Cadastral Boundary Evidence"
    )

    plt.axis(
        "off"
    )

    plt.close('all')


    # ============================================================
    # 18. SEED-BASED VORONOI PARTITION
    # ============================================================
    #
    # This is intentionally NOT based on XLSX area.
    #
    # Each pixel is initially assigned to its closest
    # survey seed.
    #
    # Strong map boundaries are subsequently respected.
    # ============================================================

    Y, X = np.indices(
        (
            H,
            W
        ),
        dtype=np.float32
    )


    number_of_fields = len(
        field_seeds
    )


    seed_distance_stack = np.empty(
        (
            number_of_fields,
            H,
            W
        ),
        dtype=np.float32
    )


    for i, row in field_seeds.iterrows():

        sx = float(
            row["Map_X"]
        )

        sy = float(
            row["Map_Y"]
        )


        seed_distance_stack[
            i
        ] = np.sqrt(
            (
                X - sx
            ) ** 2
            +
            (
                Y - sy
            ) ** 2
        )


    # ============================================================
    # 19. INITIAL SEED LABELS
    # ============================================================

    nearest_seed = np.argmin(
        seed_distance_stack,
        axis=0
    )


    labels_current = (
        nearest_seed + 1
    ).astype(
        np.int32
    )


    labels_current[
        agri_mask == 0
    ] = 0


    labels_current = np.ascontiguousarray(
        labels_current,
        dtype=np.int32
    )


    # ============================================================
    # 20. ITERATIVE BOUNDARY-AWARE PARTITION
    # ============================================================
    #
    # The important correction:
    #
    # We do NOT call cv2.circle() here.
    #
    # Seed locking is performed directly with NumPy.
    # ============================================================

    normalized_boundary = (
        boundary_mask.astype(
            np.float32
        )
        /
        255.0
    )


    # Boundary influence
    BOUNDARY_WEIGHT = 2.5


    # Small number of iterations
    NUM_ITERATIONS = 8


    for iteration in range(
        NUM_ITERATIONS
    ):

        print(
            f"  Segmentation iteration "
            f"{iteration + 1}/{NUM_ITERATIONS}"
        )


        # --------------------------------------------------------
        # Base distance
        # --------------------------------------------------------

        cost_stack = (
            seed_distance_stack /
            math.hypot(
                W,
                H
            )
        )


        # --------------------------------------------------------
        # Boundary cost
        #
        # NOTE:
        # This is not used as a global acreage constraint.
        # --------------------------------------------------------

        cost_stack = (
            cost_stack
            +
            (
                BOUNDARY_WEIGHT *
                normalized_boundary
            )[None, :, :]
        )


        # --------------------------------------------------------
        # Invalid/excluded pixels
        # --------------------------------------------------------

        cost_stack[
            :,
            agri_mask == 0
        ] = np.inf


        # --------------------------------------------------------
        # Assign closest seed
        # --------------------------------------------------------

        new_labels = (
            np.argmin(
                cost_stack,
                axis=0
            )
            + 1
        ).astype(
            np.int32
        )


        new_labels[
            agri_mask == 0
        ] = 0


        # ========================================================
        # FIXED SEED LOCKING
        # ========================================================
        #
        # NO cv2.circle()
        #
        # Direct NumPy assignment avoids the OpenCV memory
        # layout error completely.
        # ========================================================

        new_labels = np.ascontiguousarray(
            new_labels,
            dtype=np.int32
        )


        for seed_index, (_, row) in enumerate(
            field_seeds.iterrows(),
            start=1
        ):

            sx = int(
                row["Map_X"]
            )

            sy = int(
                row["Map_Y"]
            )


            sx = int(
                np.clip(
                    sx,
                    0,
                    W - 1
                )
            )


            sy = int(
                np.clip(
                    sy,
                    0,
                    H - 1
                )
            )


            # ----------------------------------------------------
            # LOCK ONLY THE EXACT SEED PIXEL.
            #
            # No cv2.circle().
            # ----------------------------------------------------

            new_labels[
                sy,
                sx
            ] = seed_index


        labels_current = np.ascontiguousarray(
            new_labels,
            dtype=np.int32
        )


    # ============================================================
    # 21. CREATE INDIVIDUAL FIELD MASKS
    # ============================================================

    field_masks = {}


    for index, survey in enumerate(
        survey_list,
        start=1
    ):

        mask = (
            labels_current == index
        ).astype(
            np.uint8
        )


        # Remove excluded regions
        mask[
            excluded_mask > 0
        ] = 0


        field_masks[
            survey
        ] = np.ascontiguousarray(
            mask,
            dtype=np.uint8
        )


    # ============================================================
    # 22. KEEP ONLY SEED-CONNECTED COMPONENT
    # ============================================================

    def keep_seed_component(
        mask,
        sx,
        sy
    ):

        mask = np.ascontiguousarray(
            mask,
            dtype=np.uint8
        )


        number, labels, stats, centroids = (
            cv2.connectedComponentsWithStats(
                mask,
                connectivity=8
            )
        )


        if number <= 1:

            return mask


        sx = int(
            np.clip(
                sx,
                0,
                W - 1
            )
        )


        sy = int(
            np.clip(
                sy,
                0,
                H - 1
            )
        )


        seed_label = int(
            labels[
                sy,
                sx
            ]
        )


        # --------------------------------------------------------
        # If seed pixel is not inside a component, find nearest
        # component centroid.
        # --------------------------------------------------------

        if seed_label == 0:

            best_label = 0

            best_distance = np.inf


            for label_id in range(
                1,
                number
            ):

                cx, cy = centroids[
                    label_id
                ]


                distance = (
                    (cx - sx) ** 2
                    +
                    (cy - sy) ** 2
                )


                if distance < best_distance:

                    best_distance = distance

                    best_label = label_id


            seed_label = best_label


        if seed_label == 0:

            return np.zeros_like(
                mask
            )


        result = (
            labels == seed_label
        ).astype(
            np.uint8
        )


        result = np.ascontiguousarray(
            result
        )


        return result


    # ============================================================
    # 23. APPLY SEED CONNECTIVITY
    # ============================================================

    for index, survey in enumerate(
        survey_list
    ):

        sx = int(
            field_seeds.iloc[
                index
            ]["Map_X"]
        )


        sy = int(
            field_seeds.iloc[
                index
            ]["Map_Y"]
        )


        field_masks[
            survey
        ] = keep_seed_component(
            field_masks[
                survey
            ],
            sx,
            sy
        )


    # ============================================================
    # 24. MORPHOLOGICAL CLEANING
    # ============================================================

    for survey in survey_list:

        mask = field_masks[
            survey
        ]


        mask = cv2.morphologyEx(
            mask,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (
                    5,
                    5
                )
            )
        )


        mask = np.ascontiguousarray(
            mask,
            dtype=np.uint8
        )


        # --------------------------------------------------------
        # Connected components
        # --------------------------------------------------------

        number, labels, stats, centroids = (
            cv2.connectedComponentsWithStats(
                mask,
                connectivity=8
            )
        )


        if number > 1:

            cleaned = np.zeros_like(
                mask,
                dtype=np.uint8
            )


            # Find component containing seed
            seed_row = field_seeds[
                field_seeds[
                    "Survey Number"
                ] == survey
            ].iloc[0]


            sx = int(
                seed_row["Map_X"]
            )

            sy = int(
                seed_row["Map_Y"]
            )


            sx = np.clip(
                sx,
                0,
                W - 1
            )


            sy = np.clip(
                sy,
                0,
                H - 1
            )


            seed_label = int(
                labels[
                    sy,
                    sx
                ]
            )


            if seed_label > 0:

                cleaned[
                    labels == seed_label
                ] = 1

            else:

                # Keep components larger than threshold
                for component_id in range(
                    1,
                    number
                ):

                    area = stats[
                        component_id,
                        cv2.CC_STAT_AREA
                    ]


                    if area >= 100:

                        cleaned[
                            labels == component_id
                        ] = 1


            mask = cleaned


        field_masks[
            survey
        ] = np.ascontiguousarray(
            mask,
            dtype=np.uint8
        )


    # ============================================================
    # 25. FINAL EXCLUSION
    # ============================================================

    for survey in survey_list:

        field_masks[
            survey
        ][
            excluded_mask > 0
        ] = 0


    # ============================================================
    # 26. CALCULATE FIELD AREAS
    # ============================================================

    field_pixel_areas = {}


    field_centroids = {}


    for survey in survey_list:

        mask = field_masks[
            survey
        ]


        area = int(
            np.count_nonzero(
                mask
            )
        )


        field_pixel_areas[
            survey
        ] = area


        moments = cv2.moments(
            mask
        )


        if moments[
            "m00"
        ] > 0:

            cx = (
                moments[
                    "m10"
                ]
                /
                moments[
                    "m00"
                ]
            )


            cy = (
                moments[
                    "m01"
                ]
                /
                moments[
                    "m00"
                ]
            )

        else:

            cx = np.nan
            cy = np.nan


        field_centroids[
            survey
        ] = (
            cx,
            cy
        )


    # ============================================================
    # 27. COMBINED USABLE AREA
    # ============================================================

    combined_usable_mask = np.zeros(
        (
            H,
            W
        ),
        dtype=np.uint8
    )


    for survey in survey_list:

        combined_usable_mask[
            field_masks[
                survey
            ] > 0
        ] = 1


    combined_usable_mask[
        excluded_mask > 0
    ] = 0


    combined_usable_mask = np.ascontiguousarray(
        combined_usable_mask
    )


    total_usable_pixels = int(
        np.count_nonzero(
            combined_usable_mask
        )
    )


    # ============================================================
    # 28. FIELD CONTOURS
    # ============================================================

    field_contours = {}


    field_polygons = {}


    for survey in survey_list:

        mask = (
            field_masks[
                survey
            ] * 255
        )


        mask = np.ascontiguousarray(
            mask,
            dtype=np.uint8
        )


        contours, _ = cv2.findContours(
            mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE
        )


        if len(contours) == 0:

            field_contours[
                survey
            ] = None

            field_polygons[
                survey
            ] = None

            continue


        contour = max(
            contours,
            key=cv2.contourArea
        )


        field_contours[
            survey
        ] = contour


        perimeter = cv2.arcLength(
            contour,
            True
        )


        epsilon = (
            0.003 *
            perimeter
        )


        polygon = cv2.approxPolyDP(
            contour,
            epsilon,
            True
        )


        field_polygons[
            survey
        ] = polygon


    # ============================================================
    # 29. GEOMETRY TABLE
    # ============================================================

    geometry_records = []


    for index, row in field_seeds.iterrows():

        survey = row[
            "Survey Number"
        ]


        mask = field_masks[
            survey
        ]


        ys, xs = np.where(
            mask > 0
        )


        if len(xs) > 0:

            min_x = int(
                xs.min()
            )

            max_x = int(
                xs.max()
            )

            min_y = int(
                ys.min()
            )

            max_y = int(
                ys.max()
            )

        else:

            min_x = -1
            max_x = -1

            min_y = -1
            max_y = -1


        contour = field_contours[
            survey
        ]


        if contour is not None:

            contour_area = float(
                cv2.contourArea(
                    contour
                )
            )


            perimeter = float(
                cv2.arcLength(
                    contour,
                    True
                )
            )

        else:

            contour_area = 0.0

            perimeter = 0.0


        cx, cy = field_centroids[
            survey
        ]


        geometry_records.append({

            "Survey_Number":
                survey,

            "Seed_X":
                int(row["Map_X"]),

            "Seed_Y":
                int(row["Map_Y"]),

            "Min_X":
                min_x,

            "Max_X":
                max_x,

            "Min_Y":
                min_y,

            "Max_Y":
                max_y,

            "Width_Pixels":
                (
                    max_x -
                    min_x +
                    1
                )
                if max_x >= 0
                else 0,

            "Height_Pixels":
                (
                    max_y -
                    min_y +
                    1
                )
                if max_y >= 0
                else 0,

            "Pixel_Area":
                field_pixel_areas[
                    survey
                ],

            "Contour_Area":
                contour_area,

            "Perimeter_Pixels":
                perimeter,

            "Centroid_X":
                cx,

            "Centroid_Y":
                cy

        })


    field_geometry_df = pd.DataFrame(
        geometry_records
    )


    # ============================================================
    # 30. AREA SHARE
    # ============================================================

    if total_usable_pixels > 0:

        field_geometry_df[
            "Percentage_of_Usable_Area"
        ] = (
            field_geometry_df[
                "Pixel_Area"
            ]
            /
            total_usable_pixels
        ) * 100

    else:

        field_geometry_df[
            "Percentage_of_Usable_Area"
        ] = 0


    # ============================================================
    # 31. SEED-CENTROID DISTANCE
    # ============================================================

    seed_centroid_distances = []


    for _, row in field_geometry_df.iterrows():

        distance = math.hypot(
            row["Seed_X"] -
            row["Centroid_X"],
            row["Seed_Y"] -
            row["Centroid_Y"]
        )


        seed_centroid_distances.append(
            distance
        )


    field_geometry_df[
        "Seed_to_Centroid_Distance"
    ] = seed_centroid_distances


    # ============================================================
    # 32. GEOMETRIC QUALITY CONTROL
    # ============================================================
    #
    # NO XLSX AREA COMPARISON.
    #
    # This only identifies suspicious geometry.
    # ============================================================

    median_area = np.median(
        field_geometry_df[
            "Pixel_Area"
        ]
    )


    median_area = max(
        float(median_area),
        1.0
    )


    field_geometry_df[
        "Area_Ratio_to_Median"
    ] = (
        field_geometry_df[
            "Pixel_Area"
        ]
        /
        median_area
    )


    field_geometry_df[
        "Geometry_QC"
    ] = "OK"


    for i, row in field_geometry_df.iterrows():

        review = False


        # Extremely large compared with other map fields
        if (
            row[
                "Area_Ratio_to_Median"
            ]
            >
            2.5
        ):

            review = True


        # Centroid far from seed
        if (
            row[
                "Seed_to_Centroid_Distance"
            ]
            >
            250
        ):

            review = True


        # Occupies almost entire map
        if (
            row["Width_Pixels"]
            >
            0.75 * W
            and
            row["Height_Pixels"]
            >
            0.75 * H
        ):

            review = True


        if review:

            field_geometry_df.loc[
                i,
                "Geometry_QC"
            ] = "REVIEW"


    # ============================================================
    # 33. CHECK FIELD OVERLAP
    # ============================================================

    mask_stack = np.stack(
        [
            field_masks[
                survey
            ]
            for survey in survey_list
        ],
        axis=0
    ).astype(
        np.uint8
    )


    overlap_count = np.sum(
        mask_stack,
        axis=0
    )


    overlap_pixels = int(
        np.count_nonzero(
            overlap_count > 1
        )
    )


    # ============================================================
    # 34. PRINT RESULTS
    # ============================================================

    print(
        "\n" + "=" * 100
    )

    print(
        "PART-4 V6 FIELD AREA RESULTS"
    )

    print(
        "=" * 100
    )


    for survey in survey_list:

        print(
            f"  {survey}: "
            f"{field_pixel_areas[survey]:,} pixels"
        )


    print(
        f"\nTotal map-derived usable pixels: "
        f"{total_usable_pixels:,}"
    )


    print(
        f"Field overlap pixels: "
        f"{overlap_pixels:,}"
    )


    if overlap_pixels == 0:

        print(
            "✓ No overlap between field masks."
        )

    else:

        print(
            "⚠ WARNING: field masks overlap."
        )


    # ============================================================
    # 35. DISPLAY GEOMETRY TABLE
    # ============================================================

    print(
        "\n" + "=" * 100
    )

    print(
        "FIELD GEOMETRY QUALITY CHECK"
    )

    print(
        "=" * 100
    )


    display(
        field_geometry_df
    )


    # ============================================================
    # 36. SEED CONTAINMENT CHECK
    # ============================================================

    print(
        "\nSeed containment:"
    )


    seed_status = []


    for _, row in field_seeds.iterrows():

        survey = row[
            "Survey Number"
        ]


        x = int(
            row["Map_X"]
        )

        y = int(
            row["Map_Y"]
        )


        mask = field_masks[
            survey
        ]


        inside = (
            mask[
                y,
                x
            ]
            >
            0
        )


        if inside:

            status = "OK"

            print(
                f"  ✓ {survey} "
                f"({x},{y})"
            )

        else:

            status = "NOT INSIDE"

            print(
                f"  ⚠ {survey} "
                f"({x},{y}) "
                f"not inside final mask"
            )


        seed_status.append(
            status
        )


    field_geometry_df[
        "Seed_Status"
    ] = seed_status


    # ============================================================
    # 37. CREATE FINAL COLORED MAP
    # ============================================================

    visual = rgb.copy()


    rng = np.random.default_rng(
        20260907
    )


    for survey in survey_list:

        mask = (
            field_masks[
                survey
            ] > 0
        )


        if np.count_nonzero(
            mask
        ) == 0:

            continue


        # Generate reproducible random visualization color
        color = rng.integers(
            60,
            230,
            size=3
        ).astype(
            np.float32
        )


        visual[
            mask
        ] = (
            0.65 *
            visual[
                mask
            ].astype(
                np.float32
            )
            +
            0.35 *
            color
        ).astype(
            np.uint8
        )


    # ============================================================
    # 38. DRAW CONTOURS
    # ============================================================

    visual_bgr = cv2.cvtColor(
        visual,
        cv2.COLOR_RGB2BGR
    )


    visual_bgr = np.ascontiguousarray(
        visual_bgr
    )


    for _, row in field_seeds.iterrows():

        survey = row[
            "Survey Number"
        ]


        x = int(
            row["Map_X"]
        )

        y = int(
            row["Map_Y"]
        )


        contour = field_contours[
            survey
        ]


        if contour is not None:

            contour = np.ascontiguousarray(
                contour,
                dtype=np.int32
            )


            cv2.polylines(
                visual_bgr,
                [contour],
                True,
                (0, 255, 255),
                3,
                cv2.LINE_AA
            )


        # --------------------------------------------------------
        # Seed marker
        #
        # Direct OpenCV circle is safe here because visual_bgr
        # was explicitly made contiguous.
        # --------------------------------------------------------

        cv2.circle(
            visual_bgr,
            (
                x,
                y
            ),
            6,
            (0, 255, 255),
            -1
        )


        # Survey label
        cv2.putText(
            visual_bgr,
            str(survey),
            (
                x + 10,
                y - 10
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 0, 0),
            4,
            cv2.LINE_AA
        )


        cv2.putText(
            visual_bgr,
            str(survey),
            (
                x + 10,
                y - 10
            ),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (255, 255, 255),
            2,
            cv2.LINE_AA
        )


    # ============================================================
    # 39. FINAL VISUAL
    # ============================================================

    final_visual = cv2.cvtColor(
        visual_bgr,
        cv2.COLOR_BGR2RGB
    )


    plt.figure(
        figsize=(20, 11)
    )

    plt.imshow(
        final_visual
    )

    plt.title(
        "PART-4 V6 FIXED - Seed-Constrained Field Polygons"
    )

    plt.axis(
        "off"
    )

    plt.close('all')


    # ============================================================
    # 40. INDIVIDUAL FIELD MASKS
    # ============================================================

    n = len(
        survey_list
    )


    cols = 3


    rows = max(
        1,
        math.ceil(
            n / cols
        )
    )


    fig, axes = plt.subplots(
        rows,
        cols,
        figsize=(
            18,
            rows * 5
        )
    )


    axes = np.array(
        axes
    ).reshape(
        -1
    )


    for i, survey in enumerate(
        survey_list
    ):

        axes[i].imshow(
            field_masks[
                survey
            ],
            cmap="gray"
        )


        axes[i].set_title(
            f"Survey {survey}"
        )


        axes[i].axis(
            "off"
        )


    # Hide unused axes
    for i in range(
        len(survey_list),
        len(axes)
    ):

        axes[i].axis(
            "off"
        )


    plt.tight_layout()

    plt.close('all')


    # ============================================================
    # 41. COMBINED USABLE AREA
    # ============================================================

    plt.figure(
        figsize=(20, 11)
    )

    plt.imshow(
        combined_usable_mask,
        cmap="gray"
    )

    plt.title(
        "PART-4 V6 - Combined Usable Agricultural Area"
    )

    plt.axis(
        "off"
    )

    plt.close('all')


    # ============================================================
    # 42. SAVE OUTPUT DIRECTORY
    # ============================================================

    PART4_DIR = OUTPUT_DIR


    os.makedirs(
        PART4_DIR,
        exist_ok=True
    )


    # ============================================================
    # 43. SAVE GEOMETRY TABLE
    # ============================================================

    field_geometry_df.to_csv(
        os.path.join(
            PART4_DIR,
            "field_geometry_v6.csv"
        ),
        index=False
    )


    field_geometry_df.to_excel(
        os.path.join(
            PART4_DIR,
            "field_geometry_v6.xlsx"
        ),
        index=False
    )


    # ============================================================
    # 44. SAVE BOUNDARY EVIDENCE
    # ============================================================

    cv2.imwrite(
        os.path.join(
            PART4_DIR,
            "boundary_evidence_v6.png"
        ),
        boundary_mask
    )


    # ============================================================
    # 45. SAVE FINAL FIELD MAP
    # ============================================================

    cv2.imwrite(
        os.path.join(
            PART4_DIR,
            "field_polygon_map_v6.png"
        ),
        cv2.cvtColor(
            final_visual,
            cv2.COLOR_RGB2BGR
        )
    )


    # ============================================================
    # 46. SAVE COMBINED USABLE MASK
    # ============================================================

    cv2.imwrite(
        os.path.join(
            PART4_DIR,
            "combined_usable_area_v6.png"
        ),
        (
            combined_usable_mask *
            255
        )
    )


    # ============================================================
    # 47. SAVE INDIVIDUAL FIELD MASKS
    # ============================================================

    for survey in survey_list:

        safe_name = re.sub(
            r"[^A-Za-z0-9_-]",
            "_",
            str(survey)
        )


        cv2.imwrite(
            os.path.join(
                PART4_DIR,
                f"{safe_name}_field_mask_v6.png"
            ),
            (
                field_masks[
                    survey
                ]
                *
                255
            )
        )


    # ============================================================
    # 48. SAVE POLYGON COORDINATES
    # ============================================================

    polygon_records = []


    for survey in survey_list:

        polygon = field_polygons[
            survey
        ]


        if polygon is None:

            continue


        points = (
            polygon.reshape(
                -1,
                2
            )
            .tolist()
        )


        polygon_records.append({

            "Survey_Number":
                survey,

            "Polygon_Pixel_Coordinates":
                str(points)

        })


    polygon_df = pd.DataFrame(
        polygon_records
    )


    polygon_df.to_csv(
        os.path.join(
            PART4_DIR,
            "field_polygon_coordinates_v6.csv"
        ),
        index=False
    )


    # ============================================================
    # 49. SAVE DRONE ROUTING INPUT
    # ============================================================

    routing_records = []


    for survey in survey_list:

        polygon = field_polygons[
            survey
        ]


        if polygon is None:

            continue


        cx, cy = field_centroids[
            survey
        ]


        routing_records.append({

            "Survey_Number":
                survey,

            "Centroid_X":
                cx,

            "Centroid_Y":
                cy,

            "Pixel_Area":
                field_pixel_areas[
                    survey
                ],

            "Polygon_Pixel_Coordinates":
                str(
                    polygon.reshape(
                        -1,
                        2
                    ).tolist()
                )

        })


    routing_df = pd.DataFrame(
        routing_records
    )


    routing_df.to_csv(
        os.path.join(
            PART4_DIR,
            "drone_routing_input_v6.csv"
        ),
        index=False
    )


    # ============================================================
    # 50. SAVE SEED INFORMATION
    # ============================================================

    field_seeds.to_csv(
        os.path.join(
            PART4_DIR,
            "part3_survey_seeds_used.csv"
        ),
        index=False
    )


    # ============================================================
    # 51. FINAL SUMMARY
    # ============================================================

    print(
        "\n" + "=" * 100
    )

    print(
        "PART-4 V6 FIXED COMPLETED"
    )

    print(
        "=" * 100
    )


    print(
        "\n✓ Survey numbers obtained dynamically from Part-3."
    )

    print(
        "✓ No survey numbers hard-coded."
    )

    print(
        "✓ No survey order used."
    )

    print(
        "✓ XLSX acreage NOT used."
    )

    print(
        "✓ Temporary XLSX measurements NOT used."
    )

    print(
        "✓ Map-derived pixel geometry used."
    )

    print(
        "✓ Road / pond / red exclusion mask applied."
    )

    print(
        "✓ Seed locking performed using NumPy."
    )

    print(
        "✓ cv2.circle() removed from seed-locking algorithm."
    )

    print(
        f"✓ Number of fields: "
        f"{len(survey_list)}"
    )

    print(
        f"✓ Total usable pixels: "
        f"{total_usable_pixels:,}"
    )

    print(
        f"✓ Overlap pixels: "
        f"{overlap_pixels:,}"
    )


    print(
        "\nOutput directory:"
    )

    print(
        PART4_DIR
    )


    print(
        "\nGenerated files:"
    )


    for filename in sorted(
        os.listdir(
            PART4_DIR
        )
    ):

        print(
            "  ✓",
            filename
        )


    # ============================================================
    # 52. QUALITY SUMMARY
    # ============================================================

    print(
        "\n" + "=" * 100
    )

    print(
        "GEOMETRY QUALITY SUMMARY"
    )

    print(
        "=" * 100
    )


    for _, row in field_geometry_df.iterrows():

        print(
            f"{row['Survey_Number']:>6} | "
            f"Area = {int(row['Pixel_Area']):>8,} px | "
            f"Seed = "
            f"({int(row['Seed_X'])},"
            f"{int(row['Seed_Y'])}) | "
            f"Seed status = "
            f"{row['Seed_Status']} | "
            f"QC = "
            f"{row['Geometry_QC']}"
        )


    review_count = int(
        (
            field_geometry_df[
                "Geometry_QC"
            ]
            ==
            "REVIEW"
        ).sum()
    )


    print(
        f"\nFields requiring visual review: "
        f"{review_count}"
    )


    # ============================================================
    # 53. IMPORTANT AREA NOTE
    # ============================================================

    print(
        "\n" + "=" * 100
    )

    print(
        "AREA NOTE"
    )

    print(
        "=" * 100
    )

    print(
        """
    The XLSX acreage is intentionally NOT used.

    The following values are map-derived:

        Pixel_Area
        Contour_Area
        Perimeter_Pixels
        Centroid_X
        Centroid_Y

    No acre/pixel calibration is performed.

    For real acreage, use a georeferenced map,
    GIS polygon, GPS/RTK survey or reliable spatial scale.
    """
    )





# ------------------------------------------------------------
    # Merge map-derived geometry with farmer information.
    # ------------------------------------------------------------

    geometry = field_geometry_df.copy()

    merged = master_df.merge(
        geometry,
        left_on="Survey Number",
        right_on="Survey_Number",
        how="left"
    )

    merged["Map_Matched"] = (
        merged["Map_X"].notna()
        & merged["Map_Y"].notna()
    )

    merged["Map_Area_Pixels"] = merged["Pixel_Area"]
    merged["Map_Area_Acres"] = np.nan
    merged["Usable_Area_Acres"] = np.nan

    # ------------------------------------------------------------
    # Create structured visual map.
    # ------------------------------------------------------------

    overlay = final_visual.copy()

    if overlay.dtype != np.uint8:
        overlay = np.clip(
            overlay,
            0,
            255
        ).astype(np.uint8)

    overlay_bgr = cv2.cvtColor(
        overlay,
        cv2.COLOR_RGB2BGR
    )

    title_height = max(
        55,
        int(H * 0.07)
    )

    cv2.rectangle(
        overlay_bgr,
        (0, 0),
        (W, title_height),
        (245, 250, 245),
        -1
    )

    cv2.putText(
        overlay_bgr,
        "AgriVision - Structured Field Map",
        (20, max(38, int(title_height * 0.68))),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (30, 90, 60),
        2,
        cv2.LINE_AA
    )

    color_rng = np.random.default_rng(
        20260909
    )

    for _, row in merged.iterrows():

        survey = str(
            row["Survey Number"]
        )

        if (
            pd.isna(row.get("Centroid_X"))
            or
            pd.isna(row.get("Centroid_Y"))
        ):
            continue

        cx = int(
            round(
                float(row["Centroid_X"])
            )
        )

        cy = int(
            round(
                float(row["Centroid_Y"])
            )
        )

        contour = field_contours.get(
            survey
        )

        if contour is not None:

            contour = np.ascontiguousarray(
                contour,
                dtype=np.int32
            )

            color = color_rng.integers(
                40,
                220,
                size=3
            ).astype(int)

            contour_color = (
                int(color[2]),
                int(color[1]),
                int(color[0])
            )

            cv2.polylines(
                overlay_bgr,
                [contour],
                True,
                contour_color,
                4,
                cv2.LINE_AA
            )

        farmer_name = str(
            row["Farmer Name"]
        )

        acres = str(
            row["Total land"]
        )

        crop = str(
            row["Field"]
        )

        lines = [
            f"Survey: {survey}",
            f"Farmer: {farmer_name}",
            f"Land: {acres}",
            f"Crop: {crop}"
        ]

        font = cv2.FONT_HERSHEY_SIMPLEX

        font_scale = max(
            0.42,
            min(
                0.62,
                W / 2100.0
            )
        )

        line_height = max(
            19,
            int(
                28 *
                font_scale /
                0.55
            )
        )

        line_sizes = [
            cv2.getTextSize(
                line,
                font,
                font_scale,
                1
            )[0]
            for line in lines
        ]

        box_width = min(
            max(
                width
                for width, _ in line_sizes
            ) + 22,
            max(
                180,
                int(W * 0.28)
            )
        )

        box_height = (
            line_height *
            len(lines)
            + 18
        )

        x1 = int(
            np.clip(
                cx - box_width // 2,
                5,
                max(
                    5,
                    W - box_width - 5
                )
            )
        )

        y1 = int(
            np.clip(
                cy - box_height // 2,
                title_height + 5,
                max(
                    title_height + 5,
                    H - box_height - 5
                )
            )
        )

        x2 = x1 + box_width
        y2 = y1 + box_height

        panel = overlay_bgr.copy()

        cv2.rectangle(
            panel,
            (x1, y1),
            (x2, y2),
            (255, 255, 255),
            -1
        )

        overlay_bgr = cv2.addWeighted(
            panel,
            0.78,
            overlay_bgr,
            0.22,
            0
        )

        cv2.rectangle(
            overlay_bgr,
            (x1, y1),
            (x2, y2),
            (60, 120, 80),
            2
        )

        cv2.circle(
            overlay_bgr,
            (cx, cy),
            6,
            (0, 180, 80),
            -1
        )

        for i, line in enumerate(lines):

            text_y = (
                y1
                + 22
                + i * line_height
            )

            cv2.putText(
                overlay_bgr,
                line,
                (x1 + 10, text_y),
                font,
                font_scale,
                (20, 70, 45),
                2 if i == 1 else 1,
                cv2.LINE_AA
            )

    cv2.putText(
        overlay_bgr,
        "Colored polygons = farmer-linked fields",
        (18, H - 32),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        (30, 70, 50),
        1,
        cv2.LINE_AA
    )

    result_image = os.path.join(
        OUTPUT_DIR,
        "structured_field_map.png"
    )

    cv2.imwrite(
        result_image,
        overlay_bgr
    )

    # ------------------------------------------------------------
    # Create farmer-field records.
    # ------------------------------------------------------------

    geometry_lookup = {
        str(row["Survey_Number"]): row
        for _, row in field_geometry_df.iterrows()
    }

    ocr_lookup = {
        str(row["Survey Number"]): row
        for _, row in survey_map_df.iterrows()
    }

    farmer_records = []

    for _, farmer in master_df.iterrows():

        survey = str(
            farmer["Survey Number"]
        )

        geom = geometry_lookup.get(
            survey,
            {}
        )

        ocr = ocr_lookup.get(
            survey,
            {}
        )

        polygon = field_polygons.get(
            survey
        )

        farmer_records.append({
            "survey_number": survey,
            "farmer_name": str(
                farmer["Farmer Name"]
            ),
            "land": str(
                farmer["Total land"]
            ),
            "land_acres": _safe_json_value(
                farmer["Original_Area_Acres"]
            ),
            "mobile_number": str(
                farmer["Mobile number"]
            ),
            "crop": str(
                farmer["Field"]
            ),
            "map_matched": bool(
                survey in ocr_lookup
            ),
            "map_x": _safe_json_value(
                ocr.get(
                    "Map_X",
                    np.nan
                )
            ),
            "map_y": _safe_json_value(
                ocr.get(
                    "Map_Y",
                    np.nan
                )
            ),
            "ocr_text": (
                str(
                    ocr.get(
                        "OCR_Text",
                        ""
                    )
                )
                if len(ocr)
                else ""
            ),
            "ocr_confidence": _safe_json_value(
                ocr.get(
                    "OCR_Confidence",
                    np.nan
                )
            ),
            "match_score": _safe_json_value(
                ocr.get(
                    "Match_Score",
                    np.nan
                )
            ),
            "pixel_area": _safe_json_value(
                geom.get(
                    "Pixel_Area",
                    np.nan
                )
            ),
            "centroid_x": _safe_json_value(
                geom.get(
                    "Centroid_X",
                    np.nan
                )
            ),
            "centroid_y": _safe_json_value(
                geom.get(
                    "Centroid_Y",
                    np.nan
                )
            ),
            "width_pixels": _safe_json_value(
                geom.get(
                    "Width_Pixels",
                    np.nan
                )
            ),
            "height_pixels": _safe_json_value(
                geom.get(
                    "Height_Pixels",
                    np.nan
                )
            ),
            "perimeter_pixels": _safe_json_value(
                geom.get(
                    "Perimeter_Pixels",
                    np.nan
                )
            ),
            "geometry_qc": str(
                geom.get(
                    "Geometry_QC",
                    "NOT_AVAILABLE"
                )
            ),
            "seed_status": str(
                geom.get(
                    "Seed_Status",
                    "NOT_AVAILABLE"
                )
            ),
            "polygon_coordinates": (
                polygon.reshape(
                    -1,
                    2
                ).tolist()
                if polygon is not None
                else []
            )
        })

    farmer_field_df = pd.DataFrame(
        farmer_records
    )

    farmer_field_df.to_csv(
        os.path.join(
            OUTPUT_DIR,
            "farmer_field_mapping.csv"
        ),
        index=False
    )

    farmer_field_df.to_excel(
        os.path.join(
            OUTPUT_DIR,
            "farmer_field_mapping.xlsx"
        ),
        index=False
    )

    matched_count = int(
        sum(
            bool(
                record["map_matched"]
            )
            for record in farmer_records
        )
    )

    review_count = int(
        (
            field_geometry_df[
                "Geometry_QC"
            ]
            == "REVIEW"
        ).sum()
    )

    output = {
        "success": True,
        "module": "Field Mapping",
        "structured_image": "structured_field_map.png",
        "farmer_table": "farmer_field_mapping.csv",
        "geometry_table": "field_geometry_v6.csv",
        "polygon_coordinates": "field_polygon_coordinates_v6.csv",
        "summary": {
            "input_map_width": int(W),
            "input_map_height": int(H),
            "total_farmer_fields": int(
                len(master_df)
            ),
            "survey_numbers_matched": matched_count,
            "survey_numbers_unmatched": int(
                len(master_df) - matched_count
            ),
            "total_usable_pixels": int(
                total_usable_pixels
            ),
            "overlap_pixels": int(
                overlap_pixels
            ),
            "fields_requiring_review": review_count
        },
        "fields": farmer_records
    }

    with open(
        os.path.join(
            OUTPUT_DIR,
            "mapping_result.json"
        ),
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            indent=2,
            ensure_ascii=False,
            default=_safe_json_value
        )

    return output

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="AgriVision standalone field mapping pipeline"
    )
    parser.add_argument(
        "--image",
        required=True,
        help="Path to the field/cadastral image"
    )
    parser.add_argument(
        "--farmers",
        required=True,
        help="Path to farmer CSV/XLSX/XLS file"
    )
    parser.add_argument(
        "--output",
        default="output/field_mapping",
        help="Directory for generated mapping outputs"
    )

    args = parser.parse_args()

    print("\n" + "=" * 100)
    print("AGRIVISION FIELD MAPPING - STANDALONE RUN")
    print("=" * 100)
    print(f"Image   : {args.image}")
    print(f"Farmers : {args.farmers}")
    print(f"Output  : {args.output}")

    try:
        result = run_mapping(
            args.image,
            args.farmers,
            args.output
        )

        print("\n" + "=" * 100)
        print("FIELD MAPPING COMPLETED SUCCESSFULLY")
        print("=" * 100)
        print(json.dumps(result.get("summary", {}), indent=2, default=_safe_json_value))
        print(f"\nOutputs saved to: {os.path.abspath(args.output)}")

    except Exception as exc:
        print("\n" + "=" * 100)
        print("FIELD MAPPING FAILED")
        print("=" * 100)
        print(f"{type(exc).__name__}: {exc}")
        raise

