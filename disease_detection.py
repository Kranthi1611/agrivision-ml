from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
import tensorflow as tf
from tensorflow.keras.models import load_model


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

MODEL_PATH = BASE_DIR / "models" / "paddy_disease_model.keras"
CLASS_FILE = BASE_DIR / "models" / "paddy_disease_classes.txt"


# ============================================================
# MODEL SETTINGS
# ============================================================

IMG_SIZE = 224


# ============================================================
# DISEASE CLASSES
# ============================================================
# These match the classes used during training.

DEFAULT_CLASSES = [
    "Bacterial Leaf Blight",
    "Brown Spot",
    "Healthy Rice Leaf",
    "Leaf Blast",
    "Leaf Scald",
    "Narrow Brown Leaf Spot",
    "Rice Hispa",
    "Sheath Blight",
]


# ============================================================
# FERTILIZER / TREATMENT RECOMMENDATIONS
# ============================================================
# These are prototype recommendations for the application.
# They can be replaced later with agronomist-verified advice.

DISEASE_RECOMMENDATIONS = {
    "Bacterial Leaf Blight": {
        "fertilizer": (
            "Avoid excessive nitrogen. Maintain balanced NPK nutrition "
            "and follow local agricultural recommendations."
        ),
        "pesticide": (
            "Use a locally approved bactericide only according to the "
            "label and agricultural officer recommendation."
        ),
    },

    "Brown Spot": {
        "fertilizer": (
            "Maintain balanced nutrition, particularly adequate potassium "
            "and other soil-required nutrients."
        ),
        "pesticide": (
            "Use an approved fungicide according to the crop label and "
            "local agricultural recommendation."
        ),
    },

    "Healthy Rice Leaf": {
        "fertilizer": (
            "No disease-specific fertilizer treatment is required. "
            "Continue normal balanced crop nutrition."
        ),
        "pesticide": (
            "No disease-specific pesticide is recommended based on this "
            "prediction."
        ),
    },

    "Leaf Blast": {
        "fertilizer": (
            "Avoid excessive nitrogen and maintain balanced crop nutrition."
        ),
        "pesticide": (
            "Use an approved rice blast fungicide according to the label "
            "and local agricultural recommendation."
        ),
    },

    "Leaf Scald": {
        "fertilizer": (
            "Maintain balanced NPK nutrition and avoid unnecessary "
            "excess nitrogen."
        ),
        "pesticide": (
            "Use an approved fungicide if recommended by a local "
            "agricultural professional."
        ),
    },

    "Narrow Brown Leaf Spot": {
        "fertilizer": (
            "Maintain balanced crop nutrition and correct any identified "
            "soil nutrient deficiencies."
        ),
        "pesticide": (
            "Use an approved fungicide according to the product label "
            "and local recommendation."
        ),
    },

    "Rice Hispa": {
        "fertilizer": (
            "Maintain normal balanced crop nutrition. Fertilizer should "
            "not be increased solely because of this pest."
        ),
        "pesticide": (
            "Use an approved insecticide only when treatment is justified "
            "and according to the label/local recommendation."
        ),
    },

    "Sheath Blight": {
        "fertilizer": (
            "Avoid excessive nitrogen and maintain balanced crop nutrition."
        ),
        "pesticide": (
            "Use an approved fungicide according to the label and "
            "local agricultural recommendation."
        ),
    },
}


# ============================================================
# LOAD CLASS NAMES
# ============================================================

def load_class_names() -> list[str]:
    """
    Load class names from the class file created during training.

    Expected file:
        models/paddy_disease_classes.txt

    If the file cannot be read, use the same class order that was
    used during training.
    """

    if CLASS_FILE.exists():
        try:
            classes = []

            with open(CLASS_FILE, "r", encoding="utf-8") as file:
                for line in file:
                    line = line.strip()

                    if not line:
                        continue

                    # Handle files such as:
                    # 0: Bacterial Leaf Blight
                    # 1: Brown Spot
                    # etc.
                    if ":" in line:
                        prefix, name = line.split(":", 1)

                        if prefix.strip().isdigit():
                            line = name.strip()

                    classes.append(line)

            if len(classes) == len(DEFAULT_CLASSES):
                return classes

        except Exception as error:
            print(
                f"Warning: Could not read class file: {error}"
            )

    return DEFAULT_CLASSES.copy()


CLASS_NAMES = load_class_names()


# ============================================================
# LOAD MODEL
# ============================================================

_model: tf.keras.Model | None = None


def get_model() -> tf.keras.Model:
    """
    Load the trained EfficientNet-B0 disease model.

    The model is loaded only once and then reused for subsequent
    predictions.
    """

    global _model

    if _model is not None:
        return _model

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Disease model not found at:\n{MODEL_PATH}\n\n"
            "Make sure train_disease.py has completed successfully "
            "and paddy_disease_model.keras exists in the models folder."
        )

    if MODEL_PATH.stat().st_size == 0:
        raise RuntimeError(
            f"Disease model file is empty:\n{MODEL_PATH}"
        )

    print("=" * 70)
    print("Loading AgriVision Paddy Disease Model")
    print("=" * 70)
    print(f"Model: {MODEL_PATH}")
    print(f"Classes: {CLASS_NAMES}")

    _model = load_model(
        MODEL_PATH,
        compile=False,
    )

    print("Disease model loaded successfully.")
    print("=" * 70)

    return _model


# ============================================================
# IMAGE PREPROCESSING
# ============================================================

def preprocess_image(image_bytes: bytes) -> np.ndarray:
    """
    Convert uploaded image bytes into the format expected by
    the trained EfficientNet-B0 model.

    Training image size:
        224 x 224

    Training preprocessing:
        RGB
        pixel values scaled to [0, 1]
    """

    if not image_bytes:
        raise ValueError("Uploaded image is empty.")

    try:
        image = Image.open(io.BytesIO(image_bytes))

        # Convert to RGB because uploaded images may be
        # grayscale, RGBA, etc.
        image = image.convert("RGB")

        # Resize exactly to the training image size.
        image = image.resize(
            (IMG_SIZE, IMG_SIZE),
            Image.Resampling.BILINEAR,
        )

        # Convert to NumPy.
        image_array = np.asarray(
            image,
            dtype=np.float32,
        )

        # Scale pixels from [0, 255] to [0, 1].
        image_array = image_array / 255.0

        # Add batch dimension.
        image_array = np.expand_dims(
            image_array,
            axis=0,
        )

        return image_array

    except Exception as error:
        raise ValueError(
            f"Could not process the uploaded image: {error}"
        ) from error


# ============================================================
# SEVERITY ESTIMATION
# ============================================================

def estimate_severity(confidence: float, disease: str) -> str:
    """
    Estimate prediction severity from model confidence.

    IMPORTANT:
    This is confidence-based application logic, not a direct
    measurement of physical disease severity in the field.
    """

    if disease == "Healthy Rice Leaf":
        return "Healthy"

    if confidence >= 0.85:
        return "High"

    if confidence >= 0.65:
        return "Moderate"

    return "Low"


# ============================================================
# RECOMMENDATIONS
# ============================================================

def get_recommendations(disease: str) -> dict[str, str]:
    """
    Return application recommendations for the predicted disease.
    """

    return DISEASE_RECOMMENDATIONS.get(
        disease,
        {
            "fertilizer": (
                "Follow balanced crop nutrition based on soil "
                "testing and local agricultural guidance."
            ),
            "pesticide": (
                "Consult an agricultural professional before applying "
                "any pesticide."
            ),
        },
    )


# ============================================================
# DISEASE PREDICTION
# ============================================================

def predict_disease(image_bytes: bytes) -> dict[str, Any]:
    """
    Predict rice disease from an uploaded crop/leaf image.

    Parameters
    ----------
    image_bytes:
        Raw bytes of the uploaded image.

    Returns
    -------
    dict
        Prediction result suitable for the FastAPI endpoint.
    """

    try:
        # --------------------------------------------------------
        # Load model
        # --------------------------------------------------------

        model = get_model()

        # --------------------------------------------------------
        # Preprocess image
        # --------------------------------------------------------

        image = preprocess_image(image_bytes)

        # --------------------------------------------------------
        # Run prediction
        # --------------------------------------------------------

        predictions = model.predict(
            image,
            verbose=0,
        )

        predictions = np.asarray(predictions)

        if predictions.ndim != 2 or predictions.shape[0] != 1:
            raise RuntimeError(
                f"Unexpected model output shape: {predictions.shape}"
            )

        probabilities = predictions[0]

        # --------------------------------------------------------
        # Safety check
        # --------------------------------------------------------

        if len(probabilities) != len(CLASS_NAMES):
            raise RuntimeError(
                "Model output classes do not match the saved class list. "
                f"Model returned {len(probabilities)} outputs, "
                f"but {len(CLASS_NAMES)} class names were loaded."
            )

        # --------------------------------------------------------
        # Find highest probability
        # --------------------------------------------------------

        predicted_index = int(
            np.argmax(probabilities)
        )

        predicted_disease = CLASS_NAMES[predicted_index]

        confidence = float(
            probabilities[predicted_index]
        )

        confidence_percent = confidence * 100.0

        # --------------------------------------------------------
        # Severity
        # --------------------------------------------------------

        severity = estimate_severity(
            confidence,
            predicted_disease,
        )

        # --------------------------------------------------------
        # Recommendations
        # --------------------------------------------------------

        recommendations = get_recommendations(
            predicted_disease
        )

        # --------------------------------------------------------
        # All class probabilities
        # --------------------------------------------------------

        class_probabilities = {}

        for index, class_name in enumerate(CLASS_NAMES):
            class_probabilities[class_name] = round(
                float(probabilities[index]) * 100.0,
                2,
            )

        # Sort probabilities from highest to lowest.
        sorted_probabilities = dict(
            sorted(
                class_probabilities.items(),
                key=lambda item: item[1],
                reverse=True,
            )
        )

        # --------------------------------------------------------
        # Final result
        # --------------------------------------------------------

        result = {
            "success": True,

            "disease": predicted_disease,

            "confidence": round(
                confidence_percent,
                2,
            ),

            "confidence_score": round(
                confidence,
                4,
            ),

            "severity": severity,

            "fertilizer_recommendation": (
                recommendations["fertilizer"]
            ),

            "pesticide_recommendation": (
                recommendations["pesticide"]
            ),

            "class_probabilities": sorted_probabilities,

            "model": "EfficientNet-B0",

            "image_size": IMG_SIZE,

            "classes": CLASS_NAMES,
        }

        return result

    except Exception as error:

        print("=" * 70)
        print("DISEASE PREDICTION ERROR")
        print("=" * 70)
        print(str(error))
        print("=" * 70)

        return {
            "success": False,
            "message": str(error),
        }


# ============================================================
# SIMPLE LOCAL TEST
# ============================================================

if __name__ == "__main__":

    print("=" * 70)
    print("AgriVision Disease Detection")
    print("=" * 70)

    print(f"Model path  : {MODEL_PATH}")
    print(f"Class file  : {CLASS_FILE}")
    print(f"Image size  : {IMG_SIZE}")
    print(f"Classes     : {len(CLASS_NAMES)}")

    for index, class_name in enumerate(CLASS_NAMES):
        print(f"{index}: {class_name}")

    print("=" * 70)

    try:
        get_model()
        print("Model verification: SUCCESS")
        print("The trained disease model is ready for API predictions.")

    except Exception as error:
        print("Model verification: FAILED")
        print(error)