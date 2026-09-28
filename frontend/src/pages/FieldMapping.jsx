import { useLocation, useNavigate } from "react-router-dom";
import { useState } from "react";
import bgImage from "../assets/bg.png";
import "../App.css";

const API_BASE_URL = "http://127.0.0.1:8000";

const FieldMapping = () => {
  const location = useLocation();
  const navigate = useNavigate();

  const fieldFile = location.state?.fieldFile;
  const farmerFile = location.state?.farmerFile;

  const [message, setMessage] = useState("");
  const [processing, setProcessing] = useState(false);
  const [result, setResult] = useState(null);
  const [resultUrls, setResultUrls] = useState(null);
  const [error, setError] = useState("");

  // ============================================================
  // GENERATE FIELD MAP
  // ============================================================

  const handleGenerateMap = async () => {
    setError("");
    setMessage("");
    setResult(null);
    setResultUrls(null);

    if (!fieldFile || !farmerFile) {
      setError(
        "Please upload both the field image and farmer data file."
      );
      return;
    }

    setProcessing(true);
    setMessage("Processing field image and farmer data...");

    try {
      const formData = new FormData();

      formData.append("field_image", fieldFile);
      formData.append("farmer_file", farmerFile);

      const response = await fetch(
        `${API_BASE_URL}/field-mapping`,
        {
          method: "POST",
          body: formData,
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.message ||
            "Field mapping request failed."
        );
      }

      if (!data.success) {
        throw new Error(
          data.message ||
            "Field mapping failed."
        );
      }

      setResultUrls(data);

      // --------------------------------------------------------
      // Get complete mapping result
      // --------------------------------------------------------

      if (data.result_json) {
        const resultResponse = await fetch(
          `${API_BASE_URL}${data.result_json}`
        );

        if (resultResponse.ok) {
          const resultData =
            await resultResponse.json();

          setResult(resultData);
        }
      }

      setMessage(
        "Field mapping generated successfully."
      );
    } catch (err) {
      console.error(
        "Field mapping error:",
        err
      );

      setError(
        err.message ||
          "Unable to generate field mapping."
      );

      setMessage("");
    } finally {
      setProcessing(false);
    }
  };

  // ============================================================
  // NEW NAVIGATION - DRONE ROUTE
  // ============================================================

  const handleDroneRoute = () => {
    if (!resultUrls) {
      setError(
        "Please generate the field mapping first."
      );
      return;
    }

    navigate("/optimized-drone-path", {
      state: {
        fieldFile: fieldFile,
        farmerFile: farmerFile,
        fieldMappingResult: result,
        fieldMappingUrls: resultUrls,
      },
    });
  };

  // ============================================================
  // NEW NAVIGATION - DISEASE DETECTION
  // ============================================================

  const handleDiseaseDetection = () => {
    if (!resultUrls) {
      setError(
        "Please generate the field mapping first."
      );
      return;
    }

    navigate("/disease-detection", {
      state: {
        fieldFile: fieldFile,
        farmerFile: farmerFile,
        fieldMappingResult: result,
        fieldMappingUrls: resultUrls,
      },
    });
  };

  // ============================================================
  // DOWNLOAD HELPERS
  // ============================================================

  const downloadFile = (url, filename) => {
    if (!url) return;

    const link = document.createElement("a");

    link.href = `${API_BASE_URL}${url}`;
    link.download = filename;

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // ============================================================
  // EXTRACT MAPPING ROWS
  // ============================================================

  const getMappingRows = () => {
    if (!result || typeof result !== "object") {
      return [];
    }

    const possibleKeys = [
      "farmer_field_mapping",
      "farmer_mapping",
      "field_mapping",
      "mappings",
      "fields",
      "data",
      "results",
    ];

    for (const key of possibleKeys) {
      if (Array.isArray(result[key])) {
        return result[key];
      }
    }

    return [];
  };

  const mappingRows = getMappingRows();

  // ============================================================
  // SUMMARY
  // ============================================================

  const summary =
    result?.summary ||
    resultUrls?.summary ||
    {};

  return (
    <div
      className="field-mapping-page"
      style={{
        minHeight: "100vh",
        backgroundImage: `url(${bgImage})`,
        backgroundSize: "cover",
        backgroundPosition: "center",
        backgroundAttachment: "fixed",
        backgroundRepeat: "no-repeat",
        padding: "40px 6%",
        color: "#123c2b",
        textShadow: "0 1px 2px rgba(255,255,255,0.45)",
      }}
    >
      {/* ====================================================== */}
      {/* HEADER */}
      {/* ====================================================== */}

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "30px",
        }}
      >
        <div>
          <h1 style={{ marginBottom: "8px" }}>
            Field Mapping
          </h1>

          <p>
            Map each field area to the corresponding farmer.
          </p>
        </div>

        <button
          onClick={() => navigate("/home")}
          style={{
            padding: "10px 18px",
            border: "none",
            borderRadius: "8px",
            background: "#2f6f4e",
            color: "white",
            cursor: "pointer",
          }}
        >
          ← Back to Home
        </button>
      </div>

      {/* ====================================================== */}
      {/* UPLOADED FILES */}
      {/* ====================================================== */}

      <div
        style={{
          background: "rgba(238, 247, 240, 0.82)",
          border: "1px solid rgba(255, 255, 255, 0.75)",
          backdropFilter: "blur(10px)",
          WebkitBackdropFilter: "blur(10px)",
          borderRadius: "14px",
          padding: "25px",
          marginBottom: "25px",
          boxShadow:
            "0 4px 15px rgba(0,0,0,0.08)",
        }}
      >
        <h2
          style={{
            marginBottom: "20px",
          }}
        >
          Uploaded Data
        </h2>

        <div
          style={{
            marginBottom: "12px",
          }}
        >
          <strong>Field Image:</strong>{" "}
          {fieldFile
            ? fieldFile.name
            : "Not uploaded"}
        </div>

        <div>
          <strong>Farmer Data:</strong>{" "}
          {farmerFile
            ? farmerFile.name
            : "Not uploaded"}
        </div>
      </div>

      {/* ====================================================== */}
      {/* GENERATE SECTION */}
      {/* ====================================================== */}

      <div
        style={{
          background: "rgba(238, 247, 240, 0.82)",
          border: "1px solid rgba(255, 255, 255, 0.75)",
          backdropFilter: "blur(10px)",
          WebkitBackdropFilter: "blur(10px)",
          borderRadius: "14px",
          padding: "30px",
          textAlign: "center",
          boxShadow:
            "0 4px 15px rgba(0,0,0,0.08)",
          marginBottom: "25px",
        }}
      >
        <h2
          style={{
            marginBottom: "10px",
          }}
        >
          Generate Structured Field Map
        </h2>

        <p
          style={{
            marginBottom: "20px",
          }}
        >
          The system will identify field areas and
          associate them with the corresponding farmer.
        </p>

        <button
          onClick={handleGenerateMap}
          disabled={
            !fieldFile ||
            !farmerFile ||
            processing
          }
          style={{
            padding: "12px 25px",
            border: "none",
            borderRadius: "8px",
            background:
              !fieldFile ||
              !farmerFile ||
              processing
                ? "#999"
                : "#2f6f4e",
            color: "white",
            fontSize: "16px",
            cursor:
              !fieldFile ||
              !farmerFile ||
              processing
                ? "not-allowed"
                : "pointer",
          }}
        >
          {processing
            ? "Processing..."
            : "Generate Field Map"}
        </button>

        {/* Processing message */}

        {message && (
          <p
            style={{
              marginTop: "20px",
              fontWeight: "600",
            }}
          >
            {message}
          </p>
        )}

        {/* Error */}

        {error && (
          <div
            style={{
              marginTop: "20px",
              padding: "12px",
              borderRadius: "8px",
              background: "#ffe8e8",
              color: "#b42318",
              fontWeight: "600",
            }}
          >
            {error}
          </div>
        )}
      </div>

      {/* ====================================================== */}
      {/* RESULTS */}
      {/* ====================================================== */}

      {resultUrls && (
        <>
          {/* ================================================== */}
          {/* SUMMARY */}
          {/* ================================================== */}

          <div
            style={{
              background: "rgba(238, 247, 240, 0.82)",
              border: "1px solid rgba(255, 255, 255, 0.75)",
              backdropFilter: "blur(10px)",
              WebkitBackdropFilter: "blur(10px)",
              borderRadius: "14px",
              padding: "30px",
              marginBottom: "25px",
              boxShadow:
                "0 4px 15px rgba(0,0,0,0.08)",
            }}
          >
            <h2
              style={{
                marginBottom: "25px",
              }}
            >
              Mapping Summary
            </h2>

            <div
              style={{
                display: "grid",
                gridTemplateColumns:
                  "repeat(auto-fit, minmax(180px, 1fr))",
                gap: "15px",
              }}
            >
              <div
                style={{
                  padding: "20px",
                  borderRadius: "10px",
                  background: "rgba(219, 238, 224, 0.72)",
                  border: "1px solid rgba(255, 255, 255, 0.7)",
                  backdropFilter: "blur(6px)",
                  WebkitBackdropFilter: "blur(6px)",
                  textAlign: "center",
                }}
              >
                <div
                  style={{
                    fontSize: "28px",
                    fontWeight: "700",
                  }}
                >
                  {summary.total_farmer_fields ??
                    "—"}
                </div>

                <div>
                  Farmer Fields
                </div>
              </div>

              <div
                style={{
                  padding: "20px",
                  borderRadius: "10px",
                  background: "rgba(219, 238, 224, 0.72)",
                  border: "1px solid rgba(255, 255, 255, 0.7)",
                  backdropFilter: "blur(6px)",
                  WebkitBackdropFilter: "blur(6px)",
                  textAlign: "center",
                }}
              >
                <div
                  style={{
                    fontSize: "28px",
                    fontWeight: "700",
                  }}
                >
                  {summary.survey_numbers_matched ??
                    "—"}
                </div>

                <div>
                  Surveys Matched
                </div>
              </div>

              <div
                style={{
                  padding: "20px",
                  borderRadius: "10px",
                  background: "rgba(219, 238, 224, 0.72)",
                  border: "1px solid rgba(255, 255, 255, 0.7)",
                  backdropFilter: "blur(6px)",
                  WebkitBackdropFilter: "blur(6px)",
                  textAlign: "center",
                }}
              >
                <div
                  style={{
                    fontSize: "28px",
                    fontWeight: "700",
                  }}
                >
                  {summary.survey_numbers_unmatched ??
                    "—"}
                </div>

                <div>
                  Surveys Unmatched
                </div>
              </div>

              <div
                style={{
                  padding: "20px",
                  borderRadius: "10px",
                  background: "rgba(219, 238, 224, 0.72)",
                  border: "1px solid rgba(255, 255, 255, 0.7)",
                  backdropFilter: "blur(6px)",
                  WebkitBackdropFilter: "blur(6px)",
                  textAlign: "center",
                }}
              >
                <div
                  style={{
                    fontSize: "28px",
                    fontWeight: "700",
                  }}
                >
                  {summary.fields_requiring_review ??
                    "—"}
                </div>

                <div>
                  Fields Requiring Review
                </div>
              </div>
            </div>
          </div>

          {/* ================================================== */}
          {/* FIELD MAP IMAGE */}
          {/* ================================================== */}

          {resultUrls.structured_map && (
            <div
              style={{
                background: "white",
                borderRadius: "14px",
                padding: "30px",
                marginBottom: "25px",
                boxShadow:
                  "0 4px 15px rgba(0,0,0,0.08)",
              }}
            >
              <h2
                style={{
                  marginBottom: "20px",
                }}
              >
                Structured Field Map
              </h2>

              <div
                style={{
                  width: "100%",
                  display: "flex",
                  justifyContent: "center",
                  background: "rgba(232, 243, 235, 0.72)",
                  border: "1px solid rgba(255, 255, 255, 0.7)",
                  borderRadius: "12px",
                  padding: "10px",
                }}
              >
                <img
                  src={`${API_BASE_URL}${resultUrls.structured_map}`}
                  alt="Structured Field Map"
                  style={{
                    width: "100%",
                    maxHeight: "650px",
                    objectFit: "contain",
                    borderRadius: "8px",
                  }}
                />
              </div>
            </div>
          )}

          {/* ================================================== */}
          {/* FARMER MAPPING TABLE */}
          {/* ================================================== */}

          {mappingRows.length > 0 && (
            <div
              style={{
                background: "white",
                borderRadius: "14px",
                padding: "30px",
                marginBottom: "25px",
                boxShadow:
                  "0 4px 15px rgba(0,0,0,0.08)",
                overflowX: "auto",
              }}
            >
              <h2
                style={{
                  marginBottom: "20px",
                }}
              >
                Farmer Field Mapping
              </h2>

              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                }}
              >
                <thead>
                  <tr>
                    {Object.keys(
                      mappingRows[0]
                    ).map((key) => (
                      <th
                        key={key}
                        style={{
                          padding: "12px",
                          textAlign: "left",
                          borderBottom:
                            "2px solid #dbe7dd",
                          background:
                            "#edf5ed",
                        }}
                      >
                        {key}
                      </th>
                    ))}
                  </tr>
                </thead>

                <tbody>
                  {mappingRows.map(
                    (row, index) => (
                      <tr key={index}>
                        {Object.keys(
                          mappingRows[0]
                        ).map((key) => (
                          <td
                            key={key}
                            style={{
                              padding: "12px",
                              borderBottom:
                                "1px solid #e5ebe6",
                            }}
                          >
                            {row[key] === null ||
                            row[key] === undefined
                              ? "—"
                              : String(row[key])}
                          </td>
                        ))}
                      </tr>
                    )
                  )}
                </tbody>
              </table>
            </div>
          )}

          {/* ================================================== */}
          {/* DOWNLOADS */}
          {/* ================================================== */}

          <div
            style={{
              background: "rgba(238, 247, 240, 0.82)",
              border: "1px solid rgba(255, 255, 255, 0.75)",
              backdropFilter: "blur(10px)",
              WebkitBackdropFilter: "blur(10px)",
              borderRadius: "14px",
              padding: "30px",
              marginBottom: "25px",
              boxShadow:
                "0 4px 15px rgba(0,0,0,0.08)",
            }}
          >
            <h2
              style={{
                marginBottom: "20px",
              }}
            >
              Download Results
            </h2>

            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: "12px",
              }}
            >
              {resultUrls.mapping_csv && (
                <button
                  onClick={() =>
                    downloadFile(
                      resultUrls.mapping_csv,
                      "farmer_field_mapping.csv"
                    )
                  }
                  style={{
                    padding: "11px 18px",
                    border: "none",
                    borderRadius: "8px",
                    background: "#2f6f4e",
                    color: "white",
                    cursor: "pointer",
                  }}
                >
                  Download CSV
                </button>
              )}

              {resultUrls.mapping_excel && (
                <button
                  onClick={() =>
                    downloadFile(
                      resultUrls.mapping_excel,
                      "farmer_field_mapping.xlsx"
                    )
                  }
                  style={{
                    padding: "11px 18px",
                    border: "none",
                    borderRadius: "8px",
                    background: "#2f6f4e",
                    color: "white",
                    cursor: "pointer",
                  }}
                >
                  Download Excel
                </button>
              )}

              {resultUrls.geometry_csv && (
                <button
                  onClick={() =>
                    downloadFile(
                      resultUrls.geometry_csv,
                      "field_geometry.csv"
                    )
                  }
                  style={{
                    padding: "11px 18px",
                    border: "none",
                    borderRadius: "8px",
                    background: "#4d8064",
                    color: "white",
                    cursor: "pointer",
                  }}
                >
                  Download Geometry
                </button>
              )}

              {resultUrls.polygon_csv && (
                <button
                  onClick={() =>
                    downloadFile(
                      resultUrls.polygon_csv,
                      "field_polygon_coordinates.csv"
                    )
                  }
                  style={{
                    padding: "11px 18px",
                    border: "none",
                    borderRadius: "8px",
                    background: "#4d8064",
                    color: "white",
                    cursor: "pointer",
                  }}
                >
                  Download Polygon Coordinates
                </button>
              )}
            </div>
          </div>

          {/* ================================================== */}
          {/* NEW MODULE NAVIGATION */}
          {/* ================================================== */}

          <div
            style={{
              background: "rgba(238, 247, 240, 0.92)",
              border: "1px solid rgba(255, 255, 255, 0.75)",
              backdropFilter: "blur(10px)",
              WebkitBackdropFilter: "blur(10px)",
              borderRadius: "14px",
              padding: "30px",
              marginBottom: "25px",
              boxShadow:
                "0 4px 15px rgba(0,0,0,0.08)",
              textAlign: "center",
            }}
          >
            <h2
              style={{
                marginBottom: "10px",
              }}
            >
              Continue to Next Module
            </h2>

            <p
              style={{
                marginBottom: "22px",
              }}
            >
              Field mapping is complete. Choose the next
              operation to continue the AgriVision workflow.
            </p>

            <div
              style={{
                display: "flex",
                justifyContent: "center",
                flexWrap: "wrap",
                gap: "15px",
              }}
            >
              {/* Drone Route */}

              <button
                type="button"
                onClick={handleDroneRoute}
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
                🚁 Optimized Drone Route
              </button>

              {/* Disease Detection */}

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
            </div>
          </div>
        </>
      )}

      {/* ====================================================== */}
      {/* INITIAL RESULT AREA */}
      {/* ====================================================== */}

      {!resultUrls && (
        <div
          style={{
            background: "white",
            borderRadius: "14px",
            padding: "30px",
            minHeight: "180px",
            boxShadow:
              "0 4px 15px rgba(0,0,0,0.08)",
          }}
        >
          <h2
            style={{
              marginBottom: "15px",
            }}
          >
            Mapping Results
          </h2>

          <p>
            The structured field map and farmer-wise
            details will appear here after processing.
          </p>
        </div>
      )}
    </div>
  );
};

export default FieldMapping;