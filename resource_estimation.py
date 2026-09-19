"""
AgriVision - Resource Estimation Engine

Input:
    Excel/CSV farmer-data file using the existing fixed column names:
      Survey Number
      Farmer Name
      Land Area (Acres)
      Crop
      Disease
      Disease Severity
      Mobile Number
      Field Type
      Is Cultivated Field

This is a configurable estimation engine for the SIH prototype.
The agronomic rates below are DEMO/CONFIGURABLE values and are not
a prescription for real-world pesticide/fertilizer application.

Usage:
    python resource_estimation.py --farmers input/resource_estimation_input.xlsx
    python resource_estimation.py --farmers input/resource_estimation_input.xlsx \
        --output output/resource_estimation
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_COLUMNS = [
    "Survey Number",
    "Farmer Name",
    "Land Area (Acres)",
    "Crop",
    "Disease",
    "Disease Severity",
    "Mobile Number",
    "Field Type",
    "Is Cultivated Field",
]


# ---------------------------------------------------------------------
# CONFIGURABLE DEMO PARAMETERS
# ---------------------------------------------------------------------
# Fertilizer: kg/acre
FERTILIZER_RATE_KG_PER_ACRE = {
    "paddy": 50.0,
    "rice": 50.0,
    "wheat": 45.0,
    "maize": 50.0,
    "cotton": 40.0,
    "groundnut": 35.0,
    "default": 40.0,
}

# Spray solution: litres/acre
SPRAY_SOLUTION_L_PER_ACRE = {
    "paddy": 20.0,
    "rice": 20.0,
    "wheat": 18.0,
    "maize": 18.0,
    "cotton": 20.0,
    "groundnut": 18.0,
    "default": 20.0,
}

# Pesticide product/application rate: litres/acre.
# Disease-specific demo rates.
PESTICIDE_RATE_L_PER_ACRE = {
    "blast": 0.40,
    "brown spot": 0.35,
    "bacterial leaf blight": 0.45,
    "leaf folder": 0.30,
    "sheath blight": 0.40,
    "default": 0.30,
}

SEVERITY_MULTIPLIER = {
    "mild": 0.80,
    "moderate": 1.00,
    "severe": 1.25,
    "high": 1.25,
    "low": 0.80,
    "medium": 1.00,
    "default": 1.00,
}

# Drone operating assumptions.
DRONE_TANK_CAPACITY_L = 10.0
DRONE_SPEED_KM_PER_HOUR = 18.0
DRONE_OPERATION_COST_PER_HOUR = 900.0
DRONE_SETUP_COST_PER_FIELD = 100.0

# Material prices: configurable demo values.
FERTILIZER_COST_PER_KG = 30.0
PESTICIDE_COST_PER_L = 650.0
WATER_COST_PER_L = 0.05


def clean_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalize_key(value: Any) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"\s+", " ", text)
    return text


def parse_acres(value: Any) -> float:
    """Accepts numbers and strings such as '2 acres'."""
    if pd.isna(value):
        return 0.0

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(float(value), 0.0)

    text = str(value).strip().lower().replace(",", "")
    match = re.search(r"[-+]?\d*\.?\d+", text)
    if not match:
        raise ValueError(f"Could not read land area from: {value!r}")

    return max(float(match.group()), 0.0)


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    text = normalize_key(value)
    if text in {"true", "yes", "y", "1", "cultivated"}:
        return True
    if text in {"false", "no", "n", "0", "non-cultivated", "road"}:
        return False

    # For the current data, non-empty Field Type is enough to infer
    # cultivated status only when the explicit flag is unavailable.
    return False


def load_farmer_data(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    elif suffix == ".csv":
        df = pd.read_csv(path)
    else:
        raise ValueError("Input must be .xlsx, .xls or .csv")

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            "Farmer data schema mismatch. Missing columns: "
            + ", ".join(missing)
        )

    # Keep the original column names exactly.
    return df[REQUIRED_COLUMNS].copy()


def is_cultivated(row: pd.Series) -> bool:
    explicit = row["Is Cultivated Field"]
    if not pd.isna(explicit) and clean_text(explicit):
        return parse_bool(explicit)

    field_type = normalize_key(row["Field Type"])
    crop = normalize_key(row["Crop"])

    if "road" in field_type or field_type in {
        "road / non-cultivated",
        "non-cultivated",
    }:
        return False

    if crop in {"", "road", "none", "nan"}:
        return False

    return True


def estimate_field(row: pd.Series) -> dict[str, Any]:
    survey = clean_text(row["Survey Number"])
    farmer = clean_text(row["Farmer Name"])
    crop_display = clean_text(row["Crop"])
    crop = normalize_key(row["Crop"])
    disease_display = clean_text(row["Disease"])
    disease = normalize_key(row["Disease"])
    severity_display = clean_text(row["Disease Severity"])
    severity = normalize_key(row["Disease Severity"])

    area = parse_acres(row["Land Area (Acres)"])
    cultivated = is_cultivated(row)

    if not cultivated:
        return {
            "Survey Number": survey,
            "Farmer Name": farmer,
            "Land Area (Acres)": round(area, 4),
            "Crop": crop_display,
            "Disease": disease_display,
            "Disease Severity": severity_display,
            "Cultivated": False,
            "Fertilizer Required (kg)": 0.0,
            "Pesticide Required (L)": 0.0,
            "Spray Solution Required (L)": 0.0,
            "Drone Refills": 0,
            "Estimated Drone Time (min)": 0.0,
            "Fertilizer Cost (INR)": 0.0,
            "Pesticide Cost (INR)": 0.0,
            "Water Cost (INR)": 0.0,
            "Drone Operation Cost (INR)": 0.0,
            "Setup Cost (INR)": 0.0,
            "Total Estimated Cost (INR)": 0.0,
        }

    fertilizer_rate = FERTILIZER_RATE_KG_PER_ACRE.get(
        crop, FERTILIZER_RATE_KG_PER_ACRE["default"]
    )

    spray_rate = SPRAY_SOLUTION_L_PER_ACRE.get(
        crop, SPRAY_SOLUTION_L_PER_ACRE["default"]
    )

    pesticide_rate = PESTICIDE_RATE_L_PER_ACRE.get(
        disease, PESTICIDE_RATE_L_PER_ACRE["default"]
    )

    severity_multiplier = SEVERITY_MULTIPLIER.get(
        severity, SEVERITY_MULTIPLIER["default"]
    )

    fertilizer_kg = area * fertilizer_rate
    pesticide_l = area * pesticide_rate * severity_multiplier
    spray_solution_l = area * spray_rate

    refills = math.ceil(spray_solution_l / DRONE_TANK_CAPACITY_L)

    # Simple area-based drone time estimate.
    # Actual route distance/time can later be taken directly from
    # the Optimized Drone Path module.
    estimated_drone_time_min = (
        area / 1.0 / DRONE_SPEED_KM_PER_HOUR * 60.0
    )

    fertilizer_cost = fertilizer_kg * FERTILIZER_COST_PER_KG
    pesticide_cost = pesticide_l * PESTICIDE_COST_PER_L
    water_cost = spray_solution_l * WATER_COST_PER_L
    drone_cost = (
        estimated_drone_time_min / 60.0 * DRONE_OPERATION_COST_PER_HOUR
    )
    setup_cost = DRONE_SETUP_COST_PER_FIELD

    total = (
        fertilizer_cost
        + pesticide_cost
        + water_cost
        + drone_cost
        + setup_cost
    )

    return {
        "Survey Number": survey,
        "Farmer Name": farmer,
        "Land Area (Acres)": round(area, 4),
        "Crop": crop_display,
        "Disease": disease_display,
        "Disease Severity": severity_display,
        "Cultivated": True,
        "Fertilizer Required (kg)": round(fertilizer_kg, 3),
        "Pesticide Required (L)": round(pesticide_l, 3),
        "Spray Solution Required (L)": round(spray_solution_l, 3),
        "Drone Refills": int(refills),
        "Estimated Drone Time (min)": round(estimated_drone_time_min, 2),
        "Fertilizer Cost (INR)": round(fertilizer_cost, 2),
        "Pesticide Cost (INR)": round(pesticide_cost, 2),
        "Water Cost (INR)": round(water_cost, 2),
        "Drone Operation Cost (INR)": round(drone_cost, 2),
        "Setup Cost (INR)": round(setup_cost, 2),
        "Total Estimated Cost (INR)": round(total, 2),
    }


def build_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    cultivated = [r for r in results if r["Cultivated"]]

    def total(key: str) -> float:
        return round(sum(float(r[key]) for r in cultivated), 3)

    material_cost = round(
        sum(
            r["Fertilizer Cost (INR)"]
            + r["Pesticide Cost (INR)"]
            + r["Water Cost (INR)"]
            for r in cultivated
        ),
        2,
    )

    drone_cost = round(
        sum(
            r["Drone Operation Cost (INR)"] + r["Setup Cost (INR)"]
            for r in cultivated
        ),
        2,
    )

    return {
        "total_records": len(results),
        "cultivated_fields": len(cultivated),
        "total_cultivated_area_acres": total("Land Area (Acres)"),
        "total_fertilizer_kg": total("Fertilizer Required (kg)"),
        "total_pesticide_l": total("Pesticide Required (L)"),
        "total_spray_solution_l": total("Spray Solution Required (L)"),
        "total_drone_refills": int(
            sum(int(r["Drone Refills"]) for r in cultivated)
        ),
        "estimated_drone_time_min": total("Estimated Drone Time (min)"),
        "material_cost_inr": material_cost,
        "drone_operation_cost_inr": drone_cost,
        "total_estimated_cost_inr": round(material_cost + drone_cost, 2),
    }


def run_estimation(
    farmer_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = load_farmer_data(farmer_path)
    results = [estimate_field(row) for _, row in df.iterrows()]
    summary = build_summary(results)

    result_df = pd.DataFrame(results)

    # Main field-wise result.
    csv_path = output_dir / "resource_estimation.csv"
    xlsx_path = output_dir / "resource_estimation.xlsx"
    json_path = output_dir / "resource_estimation_result.json"

    result_df.to_csv(csv_path, index=False)
    result_df.to_excel(xlsx_path, index=False)

    payload = {
        "summary": summary,
        "fields": results,
        "configuration": {
            "drone_tank_capacity_l": DRONE_TANK_CAPACITY_L,
            "drone_speed_kmph": DRONE_SPEED_KM_PER_HOUR,
            "drone_operation_cost_per_hour_inr": DRONE_OPERATION_COST_PER_HOUR,
            "drone_setup_cost_per_field_inr": DRONE_SETUP_COST_PER_FIELD,
            "fertilizer_cost_per_kg_inr": FERTILIZER_COST_PER_KG,
            "pesticide_cost_per_l_inr": PESTICIDE_COST_PER_L,
            "water_cost_per_l_inr": WATER_COST_PER_L,
            "note": (
                "Agronomic and cost values are configurable demo parameters "
                "for the prototype and should be replaced/validated with "
                "approved local recommendations before real-world use."
            ),
        },
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    return {
        "summary": summary,
        "fields": results,
        "csv": str(csv_path),
        "excel": str(xlsx_path),
        "json": str(json_path),
    }


def print_report(result: dict[str, Any]) -> None:
    summary = result["summary"]

    print("\n" + "=" * 70)
    print("AGRIVISION - RESOURCE ESTIMATION")
    print("=" * 70)

    print(f"Total records              : {summary['total_records']}")
    print(f"Cultivated fields          : {summary['cultivated_fields']}")
    print(
        f"Total cultivated area      : "
        f"{summary['total_cultivated_area_acres']:.2f} acres"
    )
    print(
        f"Total fertilizer           : "
        f"{summary['total_fertilizer_kg']:.2f} kg"
    )
    print(
        f"Total pesticide            : "
        f"{summary['total_pesticide_l']:.2f} L"
    )
    print(
        f"Total spray solution       : "
        f"{summary['total_spray_solution_l']:.2f} L"
    )
    print(f"Total drone refills        : {summary['total_drone_refills']}")
    print(
        f"Estimated drone time       : "
        f"{summary['estimated_drone_time_min']:.2f} min"
    )
    print(
        f"Material cost              : "
        f"INR {summary['material_cost_inr']:,.2f}"
    )
    print(
        f"Drone operation cost       : "
        f"INR {summary['drone_operation_cost_inr']:,.2f}"
    )
    print(
        f"TOTAL ESTIMATED COST       : "
        f"INR {summary['total_estimated_cost_inr']:,.2f}"
    )

    print("\nFIELD-WISE ESTIMATION")
    print("-" * 70)

    for field in result["fields"]:
        print(
            f"{field['Survey Number']} | "
            f"{field['Farmer Name']} | "
            f"{field['Land Area (Acres)']:.2f} acres | "
            f"{field['Crop']}"
        )

        if field["Cultivated"]:
            print(
                f"  Fertilizer : {field['Fertilizer Required (kg)']:.2f} kg"
            )
            print(
                f"  Pesticide  : {field['Pesticide Required (L)']:.2f} L"
            )
            print(
                f"  Spray      : {field['Spray Solution Required (L)']:.2f} L"
            )
            print(f"  Refills    : {field['Drone Refills']}")
            print(
                f"  Cost       : "
                f"INR {field['Total Estimated Cost (INR)']:,.2f}"
            )
        else:
            print("  Skipped: non-cultivated field")

    print("\nOutputs:")
    print(result["csv"])
    print(result["excel"])
    print(result["json"])
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AgriVision Resource Estimation Engine"
    )
    parser.add_argument(
        "--farmers",
        required=True,
        help="Path to farmer data (.xlsx/.xls/.csv)",
    )
    parser.add_argument(
        "--output",
        default="output/resource_estimation",
        help="Output directory",
    )

    args = parser.parse_args()

    result = run_estimation(args.farmers, args.output)
    print_report(result)


if __name__ == "__main__":
    main()
