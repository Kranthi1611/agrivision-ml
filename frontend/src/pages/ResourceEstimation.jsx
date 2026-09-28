import { useLocation, useNavigate } from "react-router-dom";
import { useState } from "react";
import bgImage from "../assets/bg.png";
import "../App.css";

const API_BASE_URL = "http://127.0.0.1:8000";

const ResourceEstimation = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const [farmerFile, setFarmerFile] = useState(
    location.state?.farmerFile || null
  );
  const [processing, setProcessing] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const handleRunEstimation = async () => {
    setError("");
    setResult(null);

    if (!farmerFile) {
      setError("Please upload the farmer data file.");
      return;
    }

    setProcessing(true);

    try {
      const formData = new FormData();
      formData.append("farmer_file", farmerFile);

      const response = await fetch(
        `${API_BASE_URL}/resource-estimation`,
        {
          method: "POST",
          body: formData,
        }
      );

      const data = await response.json();

      if (!response.ok || !data.success) {
        throw new Error(
          data.message || "Resource estimation failed."
        );
      }

      setResult(data);
    } catch (err) {
      setError(
        err.message ||
          "Unable to connect to the Resource Estimation API."
      );
    } finally {
      setProcessing(false);
    }
  };

  const formatNumber = (value, digits = 2) => {
    const number = Number(value || 0);
    return number.toLocaleString("en-IN", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  };

  const formatCurrency = (value) => {
    return `₹${Number(value || 0).toLocaleString("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  };

  const handleDownload = (path) => {
    if (!result?.request_id || !path) return;

    window.open(
      `${API_BASE_URL}${path}`,
      "_blank",
      "noopener,noreferrer"
    );
  };


  // ==========================================================
  // CONTINUE TO FARMER NOTIFICATIONS
  // ==========================================================

  const handleFarmerNotifications = () => {
    if (!result?.success) {
      setError(
        "Please generate the Resource Estimation result first."
      );
      return;
    }

    navigate("/farmer-notifications", {
      state: {
        farmerFile: farmerFile,
        resourceResult: result,
      },
    });
  };

  return (
    <div
      className="module-page resource-estimation-page"
      style={{
        backgroundImage: `url(${bgImage})`,
      }}
    >
      <div className="resource-estimation-container">

        {/* HEADER */}
        <div className="resource-estimation-header">
          <button
            className="resource-back-button"
            onClick={() => navigate("/home")}
          >
            ← Back to Home
          </button>

          <div className="resource-title-block">
            <div className="resource-title-icon">🧪</div>
            <div>
              <h1>Resource Estimation</h1>
              <p>
                Estimate fertilizer, pesticide, spray requirements,
                drone operations and total cost.
              </p>
            </div>
          </div>
        </div>

        {/* INPUT CARD */}
        <div className="resource-input-card">
          <div className="resource-section-heading">
            <h2>Farmer Data</h2>
            <p>
              Use the same farmer-data Excel/CSV structure used by
              the Field Mapping module.
            </p>
          </div>

          <div className="resource-file-row">
            <div className="resource-file-info">
              <span className="resource-file-icon">📄</span>

              <div>
                <strong>
                  {farmerFile
                    ? farmerFile.name
                    : "No farmer data file selected"}
                </strong>

                <span>
                  {farmerFile
                    ? "Ready for resource estimation"
                    : "Upload .xlsx, .xls or .csv"}
                </span>
              </div>
            </div>

            <label className="resource-upload-button">
              {farmerFile ? "Change File" : "Choose File"}

              <input
                type="file"
                accept=".xlsx,.xls,.csv"
                onChange={(event) => {
                  const file = event.target.files?.[0] || null;
                  setFarmerFile(file);
                  setResult(null);
                  setError("");
                }}
              />
            </label>
          </div>

          <button
            className="resource-run-button"
            onClick={handleRunEstimation}
            disabled={processing}
          >
            {processing
              ? "Calculating Resources..."
              : "Generate Resource Estimate"}
          </button>
        </div>

        {/* PROCESSING */}
        {processing && (
          <div className="resource-status-card">
            <div className="resource-spinner" />
            <div>
              <strong>Processing farmer data...</strong>
              <p>
                Calculating field-wise resources and village-level
                cost estimates.
              </p>
            </div>
          </div>
        )}

        {/* ERROR */}
        {error && (
          <div className="resource-error-card">
            <strong>Unable to generate estimate</strong>
            <p>{error}</p>
          </div>
        )}

        {/* RESULTS */}
        {result?.success && (
          <div className="resource-results">

            <div className="resource-results-header">
              <div>
                <span className="resource-success-label">
                  ✓ ESTIMATION COMPLETED
                </span>
                <h2>Resource Estimation Results</h2>
                <p>
                  Field-wise resource requirements and estimated
                  village-level cost.
                </p>
              </div>
            </div>

            {/* SUMMARY */}
            <div className="resource-summary-grid">
              <div className="resource-summary-card">
                <span>👨‍🌾</span>
                <small>Cultivated Fields</small>
                <strong>
                  {result.summary?.cultivated_fields ?? 0}
                </strong>
              </div>

              <div className="resource-summary-card">
                <span>🌾</span>
                <small>Cultivated Area</small>
                <strong>
                  {formatNumber(
                    result.summary?.total_cultivated_area_acres
                  )}{" "}
                  acres
                </strong>
              </div>

              <div className="resource-summary-card">
                <span>🧪</span>
                <small>Fertilizer Required</small>
                <strong>
                  {formatNumber(
                    result.summary?.total_fertilizer_kg
                  )}{" "}
                  kg
                </strong>
              </div>

              <div className="resource-summary-card">
                <span>💧</span>
                <small>Spray Solution</small>
                <strong>
                  {formatNumber(
                    result.summary?.total_spray_solution_l
                  )}{" "}
                  L
                </strong>
              </div>

              <div className="resource-summary-card">
                <span>🚁</span>
                <small>Drone Refills</small>
                <strong>
                  {result.summary?.total_drone_refills ?? 0}
                </strong>
              </div>

              <div className="resource-summary-card">
                <span>⏱️</span>
                <small>Drone Time</small>
                <strong>
                  {formatNumber(
                    result.summary?.estimated_drone_time_min
                  )}{" "}
                  min
                </strong>
              </div>

              <div className="resource-summary-card">
                <span>💰</span>
                <small>Material Cost</small>
                <strong>
                  {formatCurrency(
                    result.summary?.material_cost_inr
                  )}
                </strong>
              </div>

              <div className="resource-summary-card resource-total-card">
                <span>₹</span>
                <small>Total Estimated Cost</small>
                <strong>
                  {formatCurrency(
                    result.summary?.total_estimated_cost_inr
                  )}
                </strong>
              </div>
            </div>

            {/* FIELD-WISE TABLE */}
            <div className="resource-table-card">
              <div className="resource-section-heading">
                <h2>Field-wise Resource Plan</h2>
                <p>
                  Detailed estimation for each farmer and survey
                  number.
                </p>
              </div>

              <div className="resource-table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th>Survey</th>
                      <th>Farmer</th>
                      <th>Area</th>
                      <th>Crop</th>
                      <th>Disease</th>
                      <th>Severity</th>
                      <th>Fertilizer</th>
                      <th>Pesticide</th>
                      <th>Spray</th>
                      <th>Refills</th>
                      <th>Total Cost</th>
                    </tr>
                  </thead>

                  <tbody>
                    {(result.fields || []).map((field, index) => (
                      <tr key={`${field["Survey Number"]}-${index}`}>
                        <td>
                          {field["Survey Number"]}
                        </td>
                        <td>
                          {field["Farmer Name"]}
                        </td>
                        <td>
                          {formatNumber(
                            field["Land Area (Acres)"]
                          )}{" "}
                          ac
                        </td>
                        <td>{field["Crop"] || "—"}</td>
                        <td>{field["Disease"] || "—"}</td>
                        <td>
                          {field["Disease Severity"] || "—"}
                        </td>
                        <td>
                          {formatNumber(
                            field["Fertilizer Required (kg)"]
                          )}{" "}
                          kg
                        </td>
                        <td>
                          {formatNumber(
                            field["Pesticide Required (L)"]
                          )}{" "}
                          L
                        </td>
                        <td>
                          {formatNumber(
                            field["Spray Solution Required (L)"]
                          )}{" "}
                          L
                        </td>
                        <td>{field["Drone Refills"] ?? 0}</td>
                        <td>
                          {formatCurrency(
                            field["Total Estimated Cost (INR)"]
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* COST BREAKDOWN */}
            <div className="resource-cost-card">
              <div className="resource-section-heading">
                <h2>Cost Breakdown</h2>
              </div>

              <div className="resource-cost-grid">
                <div>
                  <span>Material Cost</span>
                  <strong>
                    {formatCurrency(
                      result.summary?.material_cost_inr
                    )}
                  </strong>
                </div>

                <div>
                  <span>Drone Operation Cost</span>
                  <strong>
                    {formatCurrency(
                      result.summary?.drone_operation_cost_inr
                    )}
                  </strong>
                </div>

                <div className="resource-cost-total">
                  <span>Total Estimated Cost</span>
                  <strong>
                    {formatCurrency(
                      result.summary?.total_estimated_cost_inr
                    )}
                  </strong>
                </div>
              </div>
            </div>

            {/* DOWNLOADS */}
            <div className="resource-download-card">
              <div>
                <h2>Download Results</h2>
                <p>
                  Export the generated resource estimation for
                  further use.
                </p>
              </div>

              <div className="resource-download-buttons">
                <button
                  onClick={() =>
                    handleDownload(result.estimation_csv)
                  }
                  disabled={!result.estimation_csv}
                >
                  Download CSV
                </button>

                <button
                  onClick={() =>
                    handleDownload(result.estimation_excel)
                  }
                  disabled={!result.estimation_excel}
                >
                  Download Excel
                </button>

                <button
                  onClick={() =>
                    handleDownload(result.result_json)
                  }
                  disabled={!result.result_json}
                >
                  View JSON
                </button>

                <button
                  onClick={handleFarmerNotifications}
                  disabled={!result?.success}
                >
                  🔔 Farmer Notifications
                </button>
              </div>
            </div>

            <div className="resource-demo-note">
              <strong>Prototype note:</strong> Agronomic application
              rates and cost values are configurable demo parameters
              in the current estimation engine and should be validated
              with approved local recommendations before real-world
              use.
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ResourceEstimation;
