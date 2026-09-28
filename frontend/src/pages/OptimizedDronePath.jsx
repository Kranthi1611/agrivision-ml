import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import bgImage from "../assets/bg.png";
import "../App.css";

const API_BASE_URL = "http://127.0.0.1:8000";

const OptimizedDronePath = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const fieldFile = location.state?.fieldFile;
  const farmerFile = location.state?.farmerFile;

  const [processing, setProcessing] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const [originalImage, setOriginalImage] = useState("");

  // ==========================================================
  // CREATE PREVIEW OF ORIGINAL FIELD IMAGE
  // ==========================================================

  useEffect(() => {
    if (!fieldFile) return;

    const imageUrl = URL.createObjectURL(fieldFile);

    setOriginalImage(imageUrl);

    return () => {
      URL.revokeObjectURL(imageUrl);
    };
  }, [fieldFile]);

  // ==========================================================
  // FORMAT HELPERS
  // ==========================================================

  const formatNumber = (value, decimals = 2) => {
    if (value === null || value === undefined || isNaN(value)) {
      return "—";
    }

    return Number(value).toLocaleString(undefined, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  };

  const formatInteger = (value) => {
    if (value === null || value === undefined || isNaN(value)) {
      return "—";
    }

    return Number(value).toLocaleString();
  };

  const formatDistance = (value) => {
    if (value === null || value === undefined || isNaN(value)) {
      return "—";
    }

    return `${formatNumber(value)} px`;
  };

  const formatTime = (minutes) => {
    if (
      minutes === null ||
      minutes === undefined ||
      isNaN(minutes)
    ) {
      return "Not configured";
    }

    if (minutes < 1) {
      return `${formatNumber(minutes * 60)} sec`;
    }

    const hours = Math.floor(minutes / 60);
    const mins = Math.round(minutes % 60);

    if (hours > 0) {
      return `${hours}h ${mins}m`;
    }

    return `${mins} min`;
  };

  // ==========================================================
  // RUN OPTIMIZED DRONE PATH ML
  // ==========================================================

  const generatePath = async () => {
    if (!fieldFile) {
      setError("No field image was received.");
      return;
    }

    setProcessing(true);
    setError("");
    setResult(null);

    try {
      const formData = new FormData();

      formData.append("field_image", fieldFile);

      const response = await fetch(
        `${API_BASE_URL}/optimized-drone-path`,
        {
          method: "POST",
          body: formData,
        }
      );

      if (!response.ok) {
        throw new Error(
          `ML server returned HTTP ${response.status}.`
        );
      }

      const data = await response.json();

      if (!data.success) {
        throw new Error(
          data.message ||
            "Failed to generate optimized drone path."
        );
      }

      const timestamp = Date.now();

      // ======================================================
      // STORE IMAGE + CSV + ACTUAL ML STATISTICS
      // ======================================================

      setResult({
        image:
          `${API_BASE_URL}${data.route_image}?t=${timestamp}`,

        csv:
          `${API_BASE_URL}${data.route_csv}?t=${timestamp}`,

        statistics: data.statistics || null,
      });
    } catch (err) {
      console.error("ML API Error:", err);

      setError(
        err.message ||
          "Failed to connect to the AgriVision ML server. Make sure the ML API is running."
      );
    } finally {
      setProcessing(false);
    }
  };

  // ==========================================================
  // NEW NAVIGATION - DISEASE DETECTION
  // ==========================================================

  const handleDiseaseDetection = () => {
    if (!result) {
      setError(
        "Please generate the optimized drone route first."
      );
      return;
    }

    navigate("/disease-detection", {
      state: {
        fieldFile: fieldFile,
        farmerFile: farmerFile,
        routeResult: result,
      },
    });
  };

  // ==========================================================
  // NEW NAVIGATION - RESOURCE ESTIMATION
  // ==========================================================

  const handleResourceEstimation = () => {
    if (!result) {
      setError(
        "Please generate the optimized drone route first."
      );
      return;
    }

    if (!farmerFile) {
      setError(
        "Farmer data is required for Resource Estimation."
      );
      return;
    }

    navigate("/resource-estimation", {
      state: {
        farmerFile: farmerFile,
        routeResult: result,
      },
    });
  };

  // ==========================================================
  // BACKGROUND STYLE
  // ==========================================================

  const moduleBackgroundStyle = {
    backgroundImage: `
      linear-gradient(
        rgba(237, 245, 237, 0.35),
        rgba(237, 245, 237, 0.45)
      ),
      url(${bgImage})
    `,
  };

  // ==========================================================
  // NO IMAGE
  // ==========================================================

  if (!fieldFile) {
    return (
      <div
        className="module-page"
        style={moduleBackgroundStyle}
      >
        <div className="module-empty">
          <h1>🚁 Optimized Drone Path</h1>

          <p>
            No field image was selected. Please return to the
            AgriVision home page and upload a field image first.
          </p>

          <button
            className="module-back-button"
            onClick={() => navigate("/home")}
          >
            ← Back to AgriVision
          </button>
        </div>
      </div>
    );
  }

  // ==========================================================
  // EXTRACT STATISTICS
  // ==========================================================

  const stats = result?.statistics;

  const fieldAnalysis = stats?.field_analysis;
  const optimization = stats?.route_optimization;
  const distances = stats?.distances;
  const roadRoute = stats?.road_route;
  const droneOperation = stats?.drone_operation;

  // ==========================================================
  // MAIN PAGE
  // ==========================================================

  return (
    <div
      className="module-page"
      style={moduleBackgroundStyle}
    >
      {/* ======================================================
          HEADER
      ====================================================== */}

      <header className="module-header">
        <button
          className="module-back-button"
          onClick={() => navigate("/home")}
        >
          ← Back to AgriVision
        </button>

        <div className="module-title">
          <span className="module-title-icon">
            🚁
          </span>

          <div>
            <h1>Optimized Drone Path</h1>

            <p>
              Generate an efficient drone coverage route
              directly from the uploaded field imagery.
            </p>
          </div>
        </div>
      </header>

      {/* ======================================================
          MAIN CONTENT
      ====================================================== */}

      <main className="module-container">

        {/* ====================================================
            INTRODUCTION
        ==================================================== */}

        <section className="module-intro">
          <div>
            <span className="module-tag">
              IMAGE-BASED AI ANALYSIS
            </span>

            <h2>
              Smart route planning for
              <span> efficient drone operations</span>
            </h2>

            <p>
              AgriVision analyzes the uploaded field image,
              identifies the usable agricultural region, avoids
              non-operational areas such as roads and water
              bodies, and generates an optimized coverage route.
            </p>
          </div>

          <div className="module-requirement">
            <div>🖼️</div>

            <strong>
              Field Image Only
            </strong>

            <small>
              Farmer data is not required for this module.
            </small>
          </div>
        </section>

        {/* ====================================================
            IMAGE COMPARISON
        ==================================================== */}

        <section className="image-comparison">

          {/* ORIGINAL IMAGE */}

          <div className="image-card">
            <div className="image-card-header">
              <div>
                <span className="image-number">
                  01
                </span>

                <div>
                  <h3>
                    Original Field Image
                  </h3>

                  <p>
                    Uploaded field imagery
                  </p>
                </div>
              </div>
            </div>

            <div className="image-wrapper">
              <img
                src={originalImage}
                alt="Original field"
              />
            </div>

            <div className="file-name">
              🖼️ {fieldFile.name}
            </div>
          </div>

          {/* ARROW */}

          <div className="route-arrow">
            →
          </div>

          {/* OPTIMIZED RESULT */}

          <div className="image-card result-card">
            <div className="image-card-header">
              <div>
                <span className="image-number">
                  02
                </span>

                <div>
                  <h3>
                    Optimized Drone Route
                  </h3>

                  <p>
                    AI-generated coverage path
                  </p>
                </div>
              </div>
            </div>

            <div className="image-wrapper result-wrapper">

              {result ? (
                <img
                  src={result.image}
                  alt="Optimized drone path"
                />
              ) : (
                <div className="result-placeholder">
                  <div>
                    🚁
                  </div>

                  <h3>
                    Route not generated yet
                  </h3>

                  <p>
                    Click the button below to generate
                    the optimized drone path.
                  </p>
                </div>
              )}

            </div>

            {result && (
              <div className="result-success">
                ✓ Optimized route generated successfully
              </div>
            )}
          </div>
        </section>

        {/* ====================================================
            GENERATE BUTTON
        ==================================================== */}

        <section className="generate-section">
          <button
            className="generate-path-button"
            onClick={generatePath}
            disabled={processing}
          >
            {processing ? (
              <>
                <span>⏳</span>
                Generating Optimized Route...
              </>
            ) : (
              <>
                <span>🚁</span>
                {result
                  ? "Regenerate Optimized Path"
                  : "Generate Optimized Path"}
                <span>→</span>
              </>
            )}
          </button>

          <p>
            AI will analyze the field image and calculate
            an efficient drone coverage route.
          </p>
        </section>

        {/* ====================================================
            ERROR
        ==================================================== */}

        {error && (
          <div className="module-error">
            ⚠️ {error}
          </div>
        )}

        {/* ====================================================
            RESULTS
        ==================================================== */}

        {result && (
          <section className="route-result-section">

            {/* ==================================================
                RESULT HEADER
            ================================================== */}

            <div className="result-heading">
              <span>
                ✦
              </span>

              <div>
                <h2>
                  Route Optimization Complete
                </h2>

                <p>
                  The drone route has been generated
                  successfully from the uploaded field imagery.
                </p>
              </div>
            </div>

            {/* ==================================================
                MAIN STATISTICS
            ================================================== */}

            <div className="route-statistics">

              {/* COVERAGE SEGMENTS */}

              <div className="stat-card">
                <span>
                  📍
                </span>

                <div>
                  <small>
                    Coverage Segments
                  </small>

                  <strong>
                    {formatInteger(
                      fieldAnalysis?.selected_coverage_segments
                    )}
                  </strong>
                </div>
              </div>

              {/* COVERAGE DISTANCE */}

              <div className="stat-card">
                <span>
                  🛣️
                </span>

                <div>
                  <small>
                    Coverage Distance
                  </small>

                  <strong>
                    {formatDistance(
                      distances?.coverage_distance_pixels
                    )}
                  </strong>
                </div>
              </div>

              {/* TOTAL ROUTE */}

              <div className="stat-card">
                <span>
                  🚁
                </span>

                <div>
                  <small>
                    Total Route Distance
                  </small>

                  <strong>
                    {formatDistance(
                      distances?.total_route_distance_pixels
                    )}
                  </strong>
                </div>
              </div>

              {/* ORIENTATION */}

              <div className="stat-card">
                <span>
                  🧭
                </span>

                <div>
                  <small>
                    Selected Orientation
                  </small>

                  <strong>
                    {optimization?.selected_orientation
                      ? optimization.selected_orientation
                          .charAt(0)
                          .toUpperCase() +
                        optimization.selected_orientation.slice(1)
                      : "—"}
                  </strong>
                </div>
              </div>

            </div>

            {/* ==================================================
                DETAILED METRICS
            ================================================== */}

            <div className="route-details">

              <h3>
                Route Performance
              </h3>

              <div className="route-statistics">

                {/* TRANSIT DISTANCE */}

                <div className="stat-card">
                  <span>
                    ↔️
                  </span>

                  <div>
                    <small>
                      Transit Distance
                    </small>

                    <strong>
                      {formatDistance(
                        distances?.transit_distance_pixels
                      )}
                    </strong>
                  </div>
                </div>

                {/* DISTANCE SAVED */}

                <div className="stat-card">
                  <span>
                    📉
                  </span>

                  <div>
                    <small>
                      Distance Saved
                    </small>

                    <strong>
                      {formatDistance(
                        optimization?.distance_saved_pixels
                      )}
                    </strong>
                  </div>
                </div>

                {/* IMPROVEMENT */}

                <div className="stat-card">
                  <span>
                    ⚡
                  </span>

                  <div>
                    <small>
                      Route Improvement
                    </small>

                    <strong>
                      {optimization?.improvement_percent != null
                        ? `${formatNumber(
                            optimization.improvement_percent
                          )}%`
                        : "—"}
                    </strong>
                  </div>
                </div>

                {/* TURNS */}

                <div className="stat-card">
                  <span>
                    🔄
                  </span>

                  <div>
                    <small>
                      Route Turns
                    </small>

                    <strong>
                      {formatInteger(
                        optimization?.number_of_turns
                      )}
                    </strong>
                  </div>
                </div>

              </div>

            </div>

            {/* ==================================================
                FIELD ANALYSIS
            ================================================== */}

            <div className="route-details">

              <h3>
                Field Analysis
              </h3>

              <div className="route-steps">

                <div>
                  <span>
                    1
                  </span>

                  <p>
                    <strong>
                      Field Area
                    </strong>

                    <br />

                    {formatInteger(
                      fieldAnalysis?.field_area_pixels
                    )}{" "}
                    px²
                  </p>
                </div>

                <div>
                  <span>
                    2
                  </span>

                  <p>
                    <strong>
                      Usable Field Area
                    </strong>

                    <br />

                    {formatInteger(
                      fieldAnalysis?.usable_field_area_pixels
                    )}{" "}
                    px²
                  </p>
                </div>

                <div>
                  <span>
                    3
                  </span>

                  <p>
                    <strong>
                      Excluded Area
                    </strong>

                    <br />

                    {formatInteger(
                      fieldAnalysis?.excluded_area_pixels
                    )}{" "}
                    px²
                  </p>
                </div>

                <div>
                  <span>
                    4
                  </span>

                  <p>
                    <strong>
                      Coverage Lines
                    </strong>

                    <br />

                    {formatInteger(
                      fieldAnalysis?.selected_coverage_segments
                    )}
                  </p>
                </div>

              </div>

            </div>

            {/* ==================================================
                OPTIMIZATION METHOD
            ================================================== */}

            <div className="route-details">

              <h3>
                Optimization Method
              </h3>

              <div className="route-steps">

                <div>
                  <span>
                    ✓
                  </span>

                  <p>
                    <strong>
                      Field Segmentation
                    </strong>

                    <br />

                    Agricultural field regions were
                    identified from the uploaded imagery.
                  </p>
                </div>

                <div>
                  <span>
                    ✓
                  </span>

                  <p>
                    <strong>
                      Coverage Planning
                    </strong>

                    <br />

                    Horizontal and vertical coverage
                    candidates were generated and compared.
                  </p>
                </div>

                <div>
                  <span>
                    ✓
                  </span>

                  <p>
                    <strong>
                      Nearest Neighbor
                    </strong>

                    <br />

                    Coverage segments were ordered using
                    nearest-neighbor route construction.
                  </p>
                </div>

                <div>
                  <span>
                    ✓
                  </span>

                  <p>
                    <strong>
                      2-Opt Optimization
                    </strong>

                    <br />

                    The initial route was further improved
                    to reduce unnecessary movement.
                  </p>
                </div>

              </div>

            </div>

            {/* ==================================================
                DRONE OPERATION
            ================================================== */}

            <div className="route-details">

              <h3>
                Drone Operation Estimates
              </h3>

              <div className="route-statistics">

                {/* FLIGHT TIME */}

                <div className="stat-card">
                  <span>
                    ⏱️
                  </span>

                  <div>
                    <small>
                      Estimated Flight Time
                    </small>

                    <strong>
                      {formatTime(
                        droneOperation?.total_flight_time_minutes
                      )}
                    </strong>
                  </div>
                </div>

                {/* SPRAY VOLUME */}

                <div className="stat-card">
                  <span>
                    💧
                  </span>

                  <div>
                    <small>
                      Spray Volume
                    </small>

                    <strong>
                      {droneOperation?.total_spray_volume_litres != null
                        ? `${formatNumber(
                            droneOperation.total_spray_volume_litres
                          )} L`
                        : "Not configured"}
                    </strong>
                  </div>
                </div>

                {/* TANK LOADS */}

                <div className="stat-card">
                  <span>
                    🛢️
                  </span>

                  <div>
                    <small>
                      Tank Loads
                    </small>

                    <strong>
                      {droneOperation?.tank_loads != null
                        ? formatInteger(
                            droneOperation.tank_loads
                          )
                        : "Not configured"}
                    </strong>
                  </div>
                </div>

                {/* SORTIES */}

                <div className="stat-card">
                  <span>
                    🔋
                  </span>

                  <div>
                    <small>
                      Drone Sorties
                    </small>

                    <strong>
                      {droneOperation?.number_of_sorties != null
                        ? formatInteger(
                            droneOperation.number_of_sorties
                          )
                        : "Not configured"}
                    </strong>
                  </div>
                </div>

              </div>

              <div
                style={{
                  marginTop: "18px",
                  padding: "14px 18px",
                  borderRadius: "12px",
                  background: "rgba(255,255,255,0.65)",
                  border: "1px solid rgba(18,60,43,0.10)",
                }}
              >
                <strong>
                  Battery Status:
                </strong>{" "}
                {droneOperation?.battery_status ||
                  "Not configured"}
              </div>

            </div>

            {/* ==================================================
                ROUTE DETAILS
            ================================================== */}

            <div className="route-details">

              <h3>
                How the route was generated
              </h3>

              <div className="route-steps">

                <div>
                  <span>
                    1
                  </span>

                  <p>
                    <strong>
                      Field Detection
                    </strong>

                    <br />

                    The usable agricultural boundary
                    was identified from the image.
                  </p>
                </div>

                <div>
                  <span>
                    2
                  </span>

                  <p>
                    <strong>
                      Coverage Planning
                    </strong>

                    <br />

                    Parallel coverage lines were created
                    across the usable field.
                  </p>
                </div>

                <div>
                  <span>
                    3
                  </span>

                  <p>
                    <strong>
                      Route Optimization
                    </strong>

                    <br />

                    Nearest Neighbor and 2-Opt were used
                    to optimize the coverage sequence.
                  </p>
                </div>

                <div>
                  <span>
                    4
                  </span>

                  <p>
                    <strong>
                      Final Route
                    </strong>

                    <br />

                    The optimized coverage segments were
                    combined into the final open route.
                  </p>
                </div>

              </div>

            </div>

            {/* ==================================================
                ROAD START / END
            ================================================== */}

            {roadRoute && (
              <div className="route-details">

                <h3>
                  Drone Route Endpoints
                </h3>

                <div className="route-statistics">

                  <div className="stat-card">
                    <span>
                      🟢
                    </span>

                    <div>
                      <small>
                        Road Start
                      </small>

                      <strong>
                        (
                        {roadRoute.start_x},{" "}
                        {roadRoute.start_y}
                        )
                      </strong>
                    </div>
                  </div>

                  <div className="stat-card">
                    <span>
                      🔴
                    </span>

                    <div>
                      <small>
                        Road End
                      </small>

                      <strong>
                        (
                        {roadRoute.end_x},{" "}
                        {roadRoute.end_y}
                        )
                      </strong>
                    </div>
                  </div>

                  <div className="stat-card">
                    <span>
                      🛫
                    </span>

                    <div>
                      <small>
                        Route Type
                      </small>

                      <strong>
                        {optimization?.open_route
                          ? "Open Route"
                          : "Closed Route"}
                      </strong>
                    </div>
                  </div>

                  <div className="stat-card">
                    <span>
                      ↩️
                    </span>

                    <div>
                      <small>
                        Return to Start
                      </small>

                      <strong>
                        {optimization?.return_to_start
                          ? "Yes"
                          : "No"}
                      </strong>
                    </div>
                  </div>

                </div>

              </div>
            )}

            {/* ==================================================
                ACTIONS
            ================================================== */}

            <div className="result-actions">

              <a
                href={result.csv}
                className="download-route-button"
                download="optimized_drone_route.csv"
              >
                📥 Download Route CSV
              </a>

              <button
                className="back-module-button"
                onClick={generatePath}
                disabled={processing}
              >
                🔄 Regenerate Route
              </button>

            </div>

            {/* ==================================================
                NEXT MODULE NAVIGATION
            ================================================== */}

            <div
              style={{
                marginTop: "30px",
                padding: "28px",
                borderRadius: "14px",
                background: "rgba(238, 247, 240, 0.92)",
                border:
                  "1px solid rgba(255, 255, 255, 0.75)",
                boxShadow:
                  "0 4px 15px rgba(0,0,0,0.08)",
                textAlign: "center",
              }}
            >
              <h3
                style={{
                  marginBottom: "10px",
                  color: "#164e3b",
                }}
              >
                Continue AgriVision Workflow
              </h3>

              <p
                style={{
                  marginBottom: "22px",
                  color: "#315c49",
                }}
              >
                Route optimization is complete. Continue
                with disease analysis or resource planning.
              </p>

              <div
                style={{
                  display: "flex",
                  justifyContent: "center",
                  flexWrap: "wrap",
                  gap: "14px",
                }}
              >
                {/* DISEASE DETECTION */}

                <button
                  type="button"
                  onClick={handleDiseaseDetection}
                  style={{
                    padding: "13px 24px",
                    border: "none",
                    borderRadius: "9px",
                    background: "#3f7d5f",
                    color: "white",
                    fontSize: "16px",
                    fontWeight: "600",
                    cursor: "pointer",
                    boxShadow:
                      "0 4px 10px rgba(0,0,0,0.12)",
                  }}
                >
                  🌿 Disease Detection
                </button>

                {/* RESOURCE ESTIMATION */}

                <button
                  type="button"
                  onClick={handleResourceEstimation}
                  style={{
                    padding: "13px 24px",
                    border: "none",
                    borderRadius: "9px",
                    background: "#2f6f4e",
                    color: "white",
                    fontSize: "16px",
                    fontWeight: "600",
                    cursor: "pointer",
                    boxShadow:
                      "0 4px 10px rgba(0,0,0,0.12)",
                  }}
                >
                  📊 Resource Estimation
                </button>

              </div>
            </div>

          </section>
        )}

      </main>
    </div>
  );
};

export default OptimizedDronePath;