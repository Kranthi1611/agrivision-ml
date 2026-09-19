from fastapi import FastAPI, UploadFile, File, Form
from pydantic import BaseModel
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from pathlib import Path
import shutil
import json
import uuid
import pandas as pd

from disease_detection import predict_disease

from optimized_drone_path import (
    main,
    OUTPUT_IMAGE,
    OUTPUT_CSV,
    OUTPUT_STATS,
    INPUT_IMAGE
)

from field_mapping import run_mapping
from resource_estimation import run_estimation
from farmer_notifications import (
    build_farmer_message,
    normalize_mobile,
    send_sms,
)


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

FIELD_MAPPING_INPUT_DIR = (
    BASE_DIR / "input" / "field_mapping"
)

FIELD_MAPPING_OUTPUT_DIR = (
    BASE_DIR / "output" / "field_mapping"
)

RESOURCE_ESTIMATION_INPUT_DIR = (
    BASE_DIR / "input" / "resource_estimation"
)

RESOURCE_ESTIMATION_OUTPUT_DIR = (
    BASE_DIR / "output" / "resource_estimation"
)

FARMER_NOTIFICATIONS_INPUT_DIR = (
    BASE_DIR / "input" / "farmer_notifications"
)

FARMER_NOTIFICATIONS_OUTPUT_DIR = (
    BASE_DIR / "output" / "farmer_notifications"
)


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="AgriVision ML API",
    description="AgriVision Machine Learning API"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():
    return {
        "message": "AgriVision ML API is running",
        "modules": [
            "Field Mapping",
            "Optimized Drone Path",
            "Disease Detection",
            "Resource Estimation",
            "Farmer Notifications"
        ]
    }


# ============================================================
# DISEASE DETECTION
# ============================================================

@app.post("/disease-detection")
async def disease_detection(
    crop_image: UploadFile = File(...)
):

    if not crop_image.filename:
        return {
            "success": False,
            "message": "No crop image received."
        }

    try:

        # ----------------------------------------------------
        # Read uploaded image
        # ----------------------------------------------------

        image_bytes = await crop_image.read()

        if not image_bytes:
            return {
                "success": False,
                "message": "Uploaded image is empty."
            }

        # ----------------------------------------------------
        # Run Disease Detection
        # ----------------------------------------------------

        result = predict_disease(image_bytes)

        # ----------------------------------------------------
        # Return Result
        # ----------------------------------------------------

        return result

    except Exception as e:

        return {
            "success": False,
            "message": str(e)
        }


# ============================================================
# FIELD MAPPING
# ============================================================

@app.post("/field-mapping")
async def field_mapping(
    field_image: UploadFile = File(...),
    farmer_file: UploadFile = File(...)
):

    if not field_image.filename:
        return {
            "success": False,
            "message": "No field image received."
        }

    if not farmer_file.filename:
        return {
            "success": False,
            "message": "No farmer data file received."
        }

    # --------------------------------------------------------
    # Create unique request ID
    # --------------------------------------------------------

    request_id = uuid.uuid4().hex

    input_dir = (
        FIELD_MAPPING_INPUT_DIR / request_id
    )

    output_dir = (
        FIELD_MAPPING_OUTPUT_DIR / request_id
    )

    input_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # File paths
    # --------------------------------------------------------

    image_path = (
        input_dir / field_image.filename
    )

    farmer_path = (
        input_dir / farmer_file.filename
    )

    # --------------------------------------------------------
    # Save uploaded field image
    # --------------------------------------------------------

    with open(
        image_path,
        "wb"
    ) as buffer:

        shutil.copyfileobj(
            field_image.file,
            buffer
        )

    # --------------------------------------------------------
    # Save farmer Excel/CSV
    # --------------------------------------------------------

    with open(
        farmer_path,
        "wb"
    ) as buffer:

        shutil.copyfileobj(
            farmer_file.file,
            buffer
        )

    # --------------------------------------------------------
    # Run ML
    # --------------------------------------------------------

    try:

        result = run_mapping(
            str(image_path),
            str(farmer_path),
            str(output_dir)
        )

        # ----------------------------------------------------
        # Output files
        # ----------------------------------------------------

        structured_map = (
            output_dir /
            "structured_field_map.png"
        )

        mapping_csv = (
            output_dir /
            "farmer_field_mapping.csv"
        )

        mapping_excel = (
            output_dir /
            "farmer_field_mapping.xlsx"
        )

        geometry_csv = (
            output_dir /
            "field_geometry_v6.csv"
        )

        polygon_csv = (
            output_dir /
            "field_polygon_coordinates_v6.csv"
        )

        result_json = (
            output_dir /
            "mapping_result.json"
        )

        # ----------------------------------------------------
        # Make sure mapping_result.json exists
        # ----------------------------------------------------

        if not result_json.exists():

            with open(
                result_json,
                "w",
                encoding="utf-8"
            ) as file:

                json.dump(
                    result,
                    file,
                    indent=2,
                    default=str
                )

        # ----------------------------------------------------
        # Response
        # ----------------------------------------------------

        return {
            "success": True,

            "message":
                "Field mapping generated successfully.",

            "request_id":
                request_id,

            "summary":
                result.get(
                    "summary",
                    {}
                ) if isinstance(result, dict)
                else {},

            "structured_map":
                f"/field-mapping/image/{request_id}"
                if structured_map.exists()
                else None,

            "mapping_csv":
                f"/field-mapping/csv/{request_id}"
                if mapping_csv.exists()
                else None,

            "mapping_excel":
                f"/field-mapping/excel/{request_id}"
                if mapping_excel.exists()
                else None,

            "geometry_csv":
                f"/field-mapping/geometry/{request_id}"
                if geometry_csv.exists()
                else None,

            "polygon_csv":
                f"/field-mapping/polygon/{request_id}"
                if polygon_csv.exists()
                else None,

            "result_json":
                f"/field-mapping/result/{request_id}"
                if result_json.exists()
                else None
        }

    except Exception as e:

        return {
            "success": False,
            "message": str(e),
            "request_id": request_id
        }


# ============================================================
# FIELD MAPPING IMAGE
# ============================================================

@app.get("/field-mapping/image/{request_id}")
def get_field_mapping_image(
    request_id: str
):

    file_path = (
        FIELD_MAPPING_OUTPUT_DIR /
        request_id /
        "structured_field_map.png"
    )

    if not file_path.exists():

        return {
            "success": False,
            "message":
                "Field mapping image not found."
        }

    return FileResponse(
        path=file_path,
        media_type="image/png",
        filename="structured_field_map.png"
    )


# ============================================================
# FIELD MAPPING CSV
# ============================================================

@app.get("/field-mapping/csv/{request_id}")
def get_field_mapping_csv(
    request_id: str
):

    file_path = (
        FIELD_MAPPING_OUTPUT_DIR /
        request_id /
        "farmer_field_mapping.csv"
    )

    if not file_path.exists():

        return {
            "success": False,
            "message":
                "Field mapping CSV not found."
        }

    return FileResponse(
        path=file_path,
        media_type="text/csv",
        filename="farmer_field_mapping.csv"
    )


# ============================================================
# FIELD MAPPING EXCEL
# ============================================================

@app.get("/field-mapping/excel/{request_id}")
def get_field_mapping_excel(
    request_id: str
):

    file_path = (
        FIELD_MAPPING_OUTPUT_DIR /
        request_id /
        "farmer_field_mapping.xlsx"
    )

    if not file_path.exists():

        return {
            "success": False,
            "message":
                "Field mapping Excel file not found."
        }

    return FileResponse(
        path=file_path,
        media_type=(
            "application/vnd.openxmlformats-"
            "officedocument.spreadsheetml.sheet"
        ),
        filename="farmer_field_mapping.xlsx"
    )


# ============================================================
# FIELD GEOMETRY CSV
# ============================================================

@app.get("/field-mapping/geometry/{request_id}")
def get_field_geometry(
    request_id: str
):

    file_path = (
        FIELD_MAPPING_OUTPUT_DIR /
        request_id /
        "field_geometry_v6.csv"
    )

    if not file_path.exists():

        return {
            "success": False,
            "message":
                "Field geometry CSV not found."
        }

    return FileResponse(
        path=file_path,
        media_type="text/csv",
        filename="field_geometry_v6.csv"
    )


# ============================================================
# FIELD POLYGON CSV
# ============================================================

@app.get("/field-mapping/polygon/{request_id}")
def get_field_polygon(
    request_id: str
):

    file_path = (
        FIELD_MAPPING_OUTPUT_DIR /
        request_id /
        "field_polygon_coordinates_v6.csv"
    )

    if not file_path.exists():

        return {
            "success": False,
            "message":
                "Field polygon CSV not found."
        }

    return FileResponse(
        path=file_path,
        media_type="text/csv",
        filename="field_polygon_coordinates_v6.csv"
    )


# ============================================================
# FIELD MAPPING RESULT JSON
# ============================================================

@app.get("/field-mapping/result/{request_id}")
def get_field_mapping_result(
    request_id: str
):

    file_path = (
        FIELD_MAPPING_OUTPUT_DIR /
        request_id /
        "mapping_result.json"
    )

    if not file_path.exists():

        return {
            "success": False,
            "message":
                "Field mapping result not found."
        }

    with open(
        file_path,
        "r",
        encoding="utf-8"
    ) as file:

        result = json.load(file)

    return result


# ============================================================
# RESOURCE ESTIMATION
# ============================================================

@app.post("/resource-estimation")
async def resource_estimation(
    farmer_file: UploadFile = File(...)
):

    if not farmer_file.filename:
        return {
            "success": False,
            "message": "No farmer data file received."
        }

    request_id = uuid.uuid4().hex

    input_dir = (
        RESOURCE_ESTIMATION_INPUT_DIR / request_id
    )

    output_dir = (
        RESOURCE_ESTIMATION_OUTPUT_DIR / request_id
    )

    input_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    farmer_path = (
        input_dir / farmer_file.filename
    )

    # --------------------------------------------------------
    # Save farmer Excel/CSV
    # --------------------------------------------------------

    with open(
        farmer_path,
        "wb"
    ) as buffer:

        shutil.copyfileobj(
            farmer_file.file,
            buffer
        )

    try:

        # ----------------------------------------------------
        # Run Resource Estimation
        # ----------------------------------------------------

        result = run_estimation(
            str(farmer_path),
            str(output_dir)
        )

        # ----------------------------------------------------
        # Output files
        # ----------------------------------------------------

        estimation_csv = (
            output_dir /
            "resource_estimation.csv"
        )

        estimation_excel = (
            output_dir /
            "resource_estimation.xlsx"
        )

        result_json = (
            output_dir /
            "resource_estimation_result.json"
        )

        return {
            "success": True,

            "message":
                "Resource estimation generated successfully.",

            "request_id":
                request_id,

            "summary":
                result.get(
                    "summary",
                    {}
                ),

            "fields":
                result.get(
                    "fields",
                    []
                ),

            "estimation_csv":
                f"/resource-estimation/csv/{request_id}"
                if estimation_csv.exists()
                else None,

            "estimation_excel":
                f"/resource-estimation/excel/{request_id}"
                if estimation_excel.exists()
                else None,

            "result_json":
                f"/resource-estimation/result/{request_id}"
                if result_json.exists()
                else None
        }

    except Exception as e:

        return {
            "success": False,
            "message": str(e),
            "request_id": request_id
        }


# ============================================================
# RESOURCE ESTIMATION CSV
# ============================================================

@app.get("/resource-estimation/csv/{request_id}")
def get_resource_estimation_csv(
    request_id: str
):

    file_path = (
        RESOURCE_ESTIMATION_OUTPUT_DIR /
        request_id /
        "resource_estimation.csv"
    )

    if not file_path.exists():

        return {
            "success": False,
            "message":
                "Resource estimation CSV not found."
        }

    return FileResponse(
        path=file_path,
        media_type="text/csv",
        filename="resource_estimation.csv"
    )


# ============================================================
# RESOURCE ESTIMATION EXCEL
# ============================================================

@app.get("/resource-estimation/excel/{request_id}")
def get_resource_estimation_excel(
    request_id: str
):

    file_path = (
        RESOURCE_ESTIMATION_OUTPUT_DIR /
        request_id /
        "resource_estimation.xlsx"
    )

    if not file_path.exists():

        return {
            "success": False,
            "message":
                "Resource estimation Excel file not found."
        }

    return FileResponse(
        path=file_path,
        media_type=(
            "application/vnd.openxmlformats-"
            "officedocument.spreadsheetml.sheet"
        ),
        filename="resource_estimation.xlsx"
    )


# ============================================================
# RESOURCE ESTIMATION RESULT JSON
# ============================================================

@app.get("/resource-estimation/result/{request_id}")
def get_resource_estimation_result(
    request_id: str
):

    file_path = (
        RESOURCE_ESTIMATION_OUTPUT_DIR /
        request_id /
        "resource_estimation_result.json"
    )

    if not file_path.exists():

        return {
            "success": False,
            "message":
                "Resource estimation result not found."
        }

    with open(
        file_path,
        "r",
        encoding="utf-8"
    ) as file:

        result = json.load(file)

    return result


# ============================================================
# OPTIMIZED DRONE PATH
# ============================================================

@app.post("/optimized-drone-path")
async def optimized_drone_path(
    field_image: UploadFile = File(...)
):

    if not field_image.filename:
        return {
            "success": False,
            "message":
                "No field image received."
        }

    INPUT_IMAGE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # Save uploaded image
    # --------------------------------------------------------

    with open(
        INPUT_IMAGE,
        "wb"
    ) as buffer:

        shutil.copyfileobj(
            field_image.file,
            buffer
        )

    try:

        # ----------------------------------------------------
        # Run drone ML pipeline
        # ----------------------------------------------------

        result = main()

        # ----------------------------------------------------
        # Check output image
        # ----------------------------------------------------

        if not OUTPUT_IMAGE.exists():

            return {
                "success": False,
                "message":
                    "Processing completed but "
                    "route image was not created."
            }

        # ----------------------------------------------------
        # Load statistics
        # ----------------------------------------------------

        statistics = {}

        if OUTPUT_STATS.exists():

            with open(
                OUTPUT_STATS,
                "r",
                encoding="utf-8"
            ) as file:

                statistics = json.load(
                    file
                )

        return {
            "success": True,

            "message":
                "Optimized drone path generated successfully.",

            "route_image":
                "/optimized-drone-path/image",

            "route_csv":
                "/optimized-drone-path/csv",

            "statistics":
                statistics
        }

    except Exception as e:

        return {
            "success": False,
            "message": str(e)
        }


# ============================================================
# ROUTE IMAGE
# ============================================================

@app.get("/optimized-drone-path/image")
def get_route_image():

    if not OUTPUT_IMAGE.exists():

        return {
            "success": False,
            "message":
                "No optimized route image available."
        }

    return FileResponse(
        path=OUTPUT_IMAGE,
        media_type="image/png",
        filename="optimized_drone_path.png"
    )


# ============================================================
# ROUTE CSV
# ============================================================

@app.get("/optimized-drone-path/csv")
def get_route_csv():

    if not OUTPUT_CSV.exists():

        return {
            "success": False,
            "message":
                "No route CSV available."
        }

    return FileResponse(
        path=OUTPUT_CSV,
        media_type="text/csv",
        filename="optimized_drone_route.csv"
    )


# ============================================================
# STATISTICS JSON
# ============================================================

@app.get("/optimized-drone-path/stats")
def get_route_statistics():

    if not OUTPUT_STATS.exists():

        return {
            "success": False,
            "message":
                "No route statistics available."
        }

    with open(
        OUTPUT_STATS,
        "r",
        encoding="utf-8"
    ) as file:

        statistics = json.load(
            file
        )

    return {
        "success": True,
        "statistics": statistics
    }


# ============================================================
# FARMER NOTIFICATIONS
# ============================================================

@app.post("/farmer-notifications")
async def farmer_notifications(
    farmer_file: UploadFile = File(...),
    resource_result: str = Form(...)
):

    if not farmer_file.filename:
        return {
            "success": False,
            "message": "No farmer data file received."
        }

    request_id = uuid.uuid4().hex

    input_dir = (
        FARMER_NOTIFICATIONS_INPUT_DIR / request_id
    )

    output_dir = (
        FARMER_NOTIFICATIONS_OUTPUT_DIR / request_id
    )

    input_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    farmer_path = (
        input_dir / farmer_file.filename
    )

    # --------------------------------------------------------
    # Save farmer file
    # --------------------------------------------------------

    with open(
        farmer_path,
        "wb"
    ) as buffer:

        shutil.copyfileobj(
            farmer_file.file,
            buffer
        )

    try:

        # ----------------------------------------------------
        # Use the Resource Estimation result already generated
        # on the Resource Estimation page.
        #
        # IMPORTANT:
        # Do NOT run Resource Estimation again here.
        # ----------------------------------------------------

        try:

            estimation_result = json.loads(
                resource_result
            )

        except json.JSONDecodeError:

            return {
                "success": False,
                "message":
                    "Invalid Resource Estimation result received."
            }

        if not estimation_result.get("success"):

            return {
                "success": False,
                "message":
                    "The Resource Estimation result is not valid."
            }

        estimated_fields = (
            estimation_result.get(
                "fields",
                []
            )
        )

        # ----------------------------------------------------
        # Read original farmer data
        # This preserves Mobile Number
        # ----------------------------------------------------

        suffix = farmer_path.suffix.lower()

        if suffix == ".csv":

            farmer_df = pd.read_csv(
                farmer_path
            )

        elif suffix in [".xlsx", ".xls"]:

            farmer_df = pd.read_excel(
                farmer_path
            )

        else:

            return {
                "success": False,
                "message":
                    "Unsupported farmer file format. "
                    "Use CSV or Excel."
            }

        # ----------------------------------------------------
        # Validate required notification columns
        # ----------------------------------------------------

        required_columns = [
            "Survey Number",
            "Farmer Name",
            "Mobile Number",
        ]

        missing_columns = [
            column
            for column in required_columns
            if column not in farmer_df.columns
        ]

        if missing_columns:

            return {
                "success": False,
                "message":
                    "Missing required farmer columns: "
                    + ", ".join(missing_columns)
            }

        # ----------------------------------------------------
        # Create Survey Number -> Mobile Number mapping
        # ----------------------------------------------------

        mobile_by_survey = {}

        for _, row in farmer_df.iterrows():

            survey = str(
                row["Survey Number"]
            ).strip()

            mobile = row["Mobile Number"]

            mobile_by_survey[survey] = mobile

        # ----------------------------------------------------
        # Create Survey Number -> Original Farmer Data
        # ----------------------------------------------------

        farmer_data_by_survey = {}

        for _, row in farmer_df.iterrows():

            survey = str(
                row["Survey Number"]
            ).strip()

            farmer_data_by_survey[survey] = row.to_dict()

        # ----------------------------------------------------
        # Build individual farmer notifications
        # ----------------------------------------------------

        notifications = []

        for field in estimated_fields:

            # Roads / non-cultivated records are never notified.
            if field.get("Cultivated", False) is False:
                continue

            survey = str(
                field.get(
                    "Survey Number",
                    ""
                )
            ).strip()

            farmer_name = str(
                field.get(
                    "Farmer Name",
                    ""
                )
            ).strip()

            raw_mobile = mobile_by_survey.get(
                survey,
                ""
            )

            notification = {
                "survey_number": survey,
                "farmer_name": farmer_name,
                "mobile_number": None,
                "eligible": False,
                "message": None,
                "field": field,
            }

            # ------------------------------------------------
            # Validate mobile number
            # ------------------------------------------------

            try:

                mobile = normalize_mobile(
                    raw_mobile
                )

                notification[
                    "mobile_number"
                ] = mobile

                notification[
                    "eligible"
                ] = True

                # --------------------------------------------
                # Generate individualized SMS
                # --------------------------------------------

                notification[
                    "message"
                ] = build_farmer_message(
                    field
                )

            except Exception as mobile_error:

                notification[
                    "error"
                ] = str(
                    mobile_error
                )

            notifications.append(
                notification
            )

        # ----------------------------------------------------
        # Save notification preview JSON
        # ----------------------------------------------------

        result_json = (
            output_dir /
            "farmer_notifications.json"
        )

        result = {
            "success": True,
            "request_id": request_id,

            "summary": {
                "total_records":
                    len(notifications),

                "eligible_notifications":
                    sum(
                        1
                        for item in notifications
                        if item["eligible"]
                    ),

                "ineligible_notifications":
                    sum(
                        1
                        for item in notifications
                        if not item["eligible"]
                    ),
            },

            "notifications":
                notifications,
        }

        with open(
            result_json,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                result,
                file,
                indent=2,
                default=str,
                ensure_ascii=False
            )

        return result

    except Exception as e:

        return {
            "success": False,
            "message": str(e),
            "request_id": request_id
        }


# ============================================================
# SEND INDIVIDUAL FARMER SMS
# ============================================================

class FarmerSmsRequest(BaseModel):

    survey_number: str
    farmer_name: str
    mobile_number: str
    message: str


@app.post("/farmer-notifications/send-sms")
def send_farmer_sms(
    request: FarmerSmsRequest
):

    try:

        mobile = normalize_mobile(
            request.mobile_number
        )

        if not request.message.strip():

            return {
                "success": False,
                "sent": False,
                "message":
                    "SMS message cannot be empty."
            }

        result = send_sms(
            mobile,
            request.message
        )

        return {
            "success":
                bool(result.get("success")),

            "sent":
                bool(result.get("sent")),

            "mode":
                result.get("mode"),

            "mobile_number":
                result.get(
                    "mobile_number",
                    mobile
                ),

            "survey_number":
                request.survey_number,

            "farmer_name":
                request.farmer_name,

            "message":
                request.message,

            "provider_response":
                result.get(
                    "provider_response"
                ),

            "error":
                result.get("error"),
        }

    except Exception as error:

        return {
            "success": False,
            "sent": False,
            "message": str(error)
        }


# ============================================================
# FARMER NOTIFICATIONS RESULT
# ============================================================

@app.get("/farmer-notifications/result/{request_id}")
def get_farmer_notifications_result(
    request_id: str
):

    file_path = (
        FARMER_NOTIFICATIONS_OUTPUT_DIR /
        request_id /
        "farmer_notifications.json"
    )

    if not file_path.exists():

        return {
            "success": False,
            "message":
                "Farmer notifications result not found."
        }

    with open(
        file_path,
        "r",
        encoding="utf-8"
    ) as file:

        result = json.load(file)

    return result