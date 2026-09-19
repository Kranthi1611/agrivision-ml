from __future__ import annotations

import os
from typing import Any

import requests


TEXTBEE_URL = "https://api.textbee.dev/api/v1/gateway/send-sms"


def format_currency(value: Any) -> str:
    try:
        return f"₹{float(value or 0):,.2f}"
    except Exception:
        return "₹0.00"


def build_farmer_message(field: dict[str, Any]) -> str:
    name = str(field.get("Farmer Name", "")).strip()
    survey = str(field.get("Survey Number", "")).strip()

    area = float(field.get("Land Area (Acres)", 0) or 0)
    crop = str(field.get("Crop", "")).strip() or "—"
    disease = str(field.get("Disease", "")).strip() or "—"
    severity = str(field.get("Disease Severity", "")).strip() or "—"

    fertilizer = float(
        field.get("Fertilizer Required (kg)", 0) or 0
    )
    pesticide = float(
        field.get("Pesticide Required (L)", 0) or 0
    )
    spray = float(
        field.get("Spray Solution Required (L)", 0) or 0
    )

    refills = int(field.get("Drone Refills", 0) or 0)

    fertilizer_cost = float(
        field.get("Fertilizer Cost (INR)", 0) or 0
    )
    pesticide_cost = float(
        field.get("Pesticide Cost (INR)", 0) or 0
    )
    water_cost = float(
        field.get("Water Cost (INR)", 0) or 0
    )
    drone_cost = float(
        field.get("Drone Operation Cost (INR)", 0) or 0
    )
    setup_cost = float(
        field.get("Setup Cost (INR)", 0) or 0
    )
    total_cost = float(
        field.get("Total Estimated Cost (INR)", 0) or 0
    )

    message = (
        f"AgriVision Farmer Notification\n\n"
        f"Dear {name},\n\n"
        f"Field: {survey}\n"
        f"Area: {area:.2f} acres\n"
        f"Crop: {crop}\n"
        f"Disease: {disease}\n"
        f"Severity: {severity}\n\n"
        f"Resource Requirement:\n"
        f"Fertilizer: {fertilizer:.2f} kg\n"
        f"Pesticide: {pesticide:.2f} L\n"
        f"Spray Solution: {spray:.2f} L\n"
        f"Drone Refills: {refills}\n\n"
        f"Cost Breakdown:\n"
        f"Fertilizer: {format_currency(fertilizer_cost)}\n"
        f"Pesticide: {format_currency(pesticide_cost)}\n"
        f"Water: {format_currency(water_cost)}\n"
        f"Drone Operation: {format_currency(drone_cost)}\n"
        f"Setup: {format_currency(setup_cost)}\n\n"
        f"Total Estimated Cost: {format_currency(total_cost)}\n\n"
        f"AgriVision"
    )

    return message


def normalize_mobile(number: Any) -> str:
    value = str(number or "").strip()

    digits = "".join(
        character for character in value
        if character.isdigit()
    )

    if digits.startswith("91") and len(digits) == 12:
        digits = digits[-10:]

    if len(digits) != 10:
        raise ValueError(
            f"Invalid Indian mobile number: {number}"
        )

    return f"+91{digits}"


def send_sms(
    mobile_number: str,
    message: str
) -> dict[str, Any]:

    api_key = os.getenv("TEXTBEE_API_KEY", "").strip()
    device_id = os.getenv("TEXTBEE_DEVICE_ID", "").strip()

    if not api_key:
        raise RuntimeError(
            "TEXTBEE_API_KEY is not configured."
        )

    if not device_id:
        raise RuntimeError(
            "TEXTBEE_DEVICE_ID is not configured."
        )

    mobile = normalize_mobile(mobile_number)

    if not message.strip():
        raise ValueError(
            "SMS message cannot be empty."
        )

    payload = {
        "deviceId": device_id,
        "recipients": [mobile],
        "message": message,
    }

    try:
        response = requests.post(
            TEXTBEE_URL,
            json=payload,
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
            },
            timeout=30,
        )

        response_data = response.json()

        if not response.ok:
            return {
                "success": False,
                "sent": False,
                "mode": "textbee",
                "mobile_number": mobile,
                "error": response_data,
            }

        data = response_data.get("data", {})

        return {
            "success": bool(data.get("success", True)),
            "sent": True,
            "mode": "textbee",
            "mobile_number": mobile,
            "provider_response": response_data,
            "sms_batch_id": data.get("smsBatchId"),
        }

    except requests.RequestException as error:
        return {
            "success": False,
            "sent": False,
            "mode": "textbee",
            "mobile_number": mobile,
            "error": str(error),
        }