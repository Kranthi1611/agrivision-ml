import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import bgImage from "../assets/bg.png";
import "../App.css";

const API_BASE_URL = "http://127.0.0.1:8000";

const DiseaseDetection = () => {
  const location = useLocation();
  const navigate = useNavigate();

  // ==========================================================
  // DATA RECEIVED FROM OTHER MODULES
  // ==========================================================

  const fieldFile = location.state?.fieldFile;
  const farmerFile = location.state?.farmerFile;

  // ==========================================================
  // STATES
  // ==========================================================

  const [cropImage, setCropImage] = useState(null);
  const [previewUrl, setPreviewUrl] = useState("");

  const [processing, setProcessing] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  // ==========================================================
  // BACKGROUND
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
  // IMAGE SELECTION
  // ==========================================================

  const handleImageChange = (event) => {
    const file = event.target.files?.[0];

    if (!file) {
      return;
    }

    setCropImage(file);
    setPreviewUrl(URL.createObjectURL(file));

    setResult(null);
    setError("");
  };

  // ==========================================================
  // DISEASE PREDICTION
  // ==========================================================

  const handlePredictDisease = async () => {
    if (!cropImage) {
      setError(
        "Please upload a crop or rice leaf image first."
      );
      return;
    }

    setProcessing(true);
    setError("");
    setResult(null);

    try {
      const formData = new FormData();

      formData.append(
        "crop_image",
        cropImage
      );

      const response = await fetch(
        `${API_BASE_URL}/disease-detection`,
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
            "Failed to detect the disease."
        );
      }

      setResult(data);

    } catch (err) {
      console.error(
        "Disease Detection API Error:",
        err
      );

      setError(
        err.message ||
          "Failed to connect to the AgriVision ML server. Make sure the ML API is running."
      );

    } finally {
      setProcessing(false);
    }
  };

  // ==========================================================
  // DRONE ROUTE
  // ==========================================================

  const handleDroneRoute = () => {
    setError("");

    if (!fieldFile) {
      setError(
        "A field image is required for Optimized Drone Route. Please open this module from Field Mapping or upload a field image from Home."
      );
      return;
    }

    navigate(
      "/optimized-drone-path",
      {
        state: {
          fieldFile: fieldFile,
          farmerFile: farmerFile,
          diseaseResult: result,
        },
      }
    );
  };

  // ==========================================================
  // RESOURCE ESTIMATION
  // ==========================================================

  const handleResourceEstimation = () => {
    setError("");

    if (!farmerFile) {
      setError(
        "Farmer data is required for Resource Estimation. Please open this module through Field Mapping or another workflow that contains farmer data."
      );
      return;
    }

    navigate(
      "/resource-estimation",
      {
        state: {
          farmerFile: farmerFile,
          diseaseResult: result,
        },
      }
    );
  };

  // ==========================================================
  // BACK TO HOME
  // ==========================================================

  const handleBackHome = () => {
    navigate("/home");
  };

  // ==========================================================
  // MAIN PAGE
  // ==========================================================

  return (
    <div
      className="module-page disease-page"
      style={moduleBackgroundStyle}
    >

      {/* ======================================================
          HEADER
      ====================================================== */}

      <header className="module-header">

        <button
          type="button"
          className="module-back-button"
          onClick={handleBackHome}
        >
          ← Back to AgriVision
        </button>

        <div className="module-title">

          <span className="module-title-icon">
            🌱
          </span>

          <div>

            <h1>
              Disease Detection
            </h1>

            <p>
              AI-powered rice crop disease identification
              using EfficientNet-B0.
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

        <section className="module-intro disease-intro">

          <div>

            <span className="module-tag">
              IMAGE-BASED AI ANALYSIS
            </span>

            <h2>
              Smart disease detection for
              <span> healthier rice crops</span>
            </h2>

            <p>
              Upload a clear image of a rice crop or leaf.
              AgriVision analyzes the image using a trained
              EfficientNet-B0 deep learning model and identifies
              the most probable disease class.
            </p>

          </div>


          <div className="module-requirement">

            <div>
              🌿
            </div>

            <strong>
              Crop / Leaf Image
            </strong>

            <small>
              Upload a clear rice leaf or crop image
              for AI analysis.
            </small>

          </div>

        </section>


        {/* ====================================================
            UPLOAD SECTION
        ==================================================== */}

        <section className="disease-upload-section">

          <div className="disease-upload-header">

            <div>

              <span className="disease-section-tag">
                STEP 01
              </span>

              <h2>
                Upload Crop / Leaf Image
              </h2>

              <p>
                Select a clear image of the rice plant or
                affected leaf.
              </p>

            </div>

          </div>


          {/* FILE INPUT */}

          <label
            className="disease-upload-box"
            htmlFor="disease-image-upload"
          >

            <div className="disease-upload-icon">
              🖼️
            </div>

            <strong>
              Choose Rice Leaf Image
            </strong>

            <span>
              JPG, JPEG, PNG and other image formats
            </span>

            <span className="disease-upload-action">
              Browse Image
            </span>

            <input
              id="disease-image-upload"
              type="file"
              accept="image/*"
              onChange={handleImageChange}
            />

          </label>


          {/* PREVIEW */}

          {previewUrl && (

            <div className="disease-preview-section">

              <div className="disease-preview-header">

                <div>

                  <span className="disease-section-tag">
                    SELECTED IMAGE
                  </span>

                  <h3>
                    Uploaded Crop Image
                  </h3>

                </div>

                <span className="disease-file-name">
                  {cropImage?.name}
                </span>

              </div>


              <div className="disease-preview-card">

                <img
                  src={previewUrl}
                  alt="Uploaded rice crop"
                />

              </div>

            </div>

          )}


          {/* PREDICT BUTTON */}

          <div className="disease-predict-area">

            <button
              type="button"
              className="disease-predict-button"
              onClick={handlePredictDisease}
              disabled={
                processing ||
                !cropImage
              }
            >

              {processing ? (
                <>
                  <span className="disease-spinner"></span>
                  Analyzing Image...
                </>
              ) : (
                <>
                  🔍 Detect Disease
                  <span>→</span>
                </>
              )}

            </button>

            {processing && (

              <p className="disease-processing-message">
                EfficientNet-B0 is analyzing the uploaded
                rice leaf image.
              </p>

            )}

          </div>

        </section>


        {/* ====================================================
            ERROR
        ==================================================== */}

        {error && (

          <div className="module-error disease-error">
            ⚠️ {error}
          </div>

        )}


        {/* ====================================================
            RESULT
        ==================================================== */}

        {result?.success && (

          <section className="disease-result-section">

            {/* RESULT HEADER */}

            <div className="result-heading">

              <span>
                ✓
              </span>

              <div>

                <h2>
                  Disease Detection Complete
                </h2>

                <p>
                  The AI model has analyzed the uploaded
                  rice crop image successfully.
                </p>

              </div>

            </div>


            {/* ==================================================
                MAIN RESULT CARDS
            ================================================== */}

            <div className="disease-main-results">


              {/* DISEASE */}

              <div className="disease-result-card primary">

                <span className="disease-result-icon">
                  🌱
                </span>

                <div>

                  <small>
                    DETECTED DISEASE
                  </small>

                  <strong>
                    {result.disease}
                  </strong>

                </div>

              </div>


              {/* CONFIDENCE */}

              <div className="disease-result-card">

                <span className="disease-result-icon">
                  🎯
                </span>

                <div>

                  <small>
                    AI CONFIDENCE
                  </small>

                  <strong>
                    {result.confidence}%
                  </strong>

                </div>

              </div>


              {/* SEVERITY */}

              <div className="disease-result-card severity">

                <span className="disease-result-icon">
                  📊
                </span>

                <div>

                  <small>
                    ESTIMATED SEVERITY
                  </small>

                  <strong>
                    {result.severity}
                  </strong>

                </div>

              </div>

            </div>


            {/* ==================================================
                RECOMMENDATIONS
            ================================================== */}

            <div className="disease-recommendations">

              {/* FERTILIZER */}

              <div className="disease-recommendation-card">

                <div className="recommendation-title">

                  <span>
                    🌱
                  </span>

                  <h3>
                    Fertilizer Recommendation
                  </h3>

                </div>

                <p>
                  {result.fertilizer_recommendation}
                </p>

              </div>


              {/* PESTICIDE */}

              <div className="disease-recommendation-card pesticide">

                <div className="recommendation-title">

                  <span>
                    🧪
                  </span>

                  <h3>
                    Pesticide Recommendation
                  </h3>

                </div>

                <p>
                  {result.pesticide_recommendation}
                </p>

              </div>

            </div>


            {/* ==================================================
                PROBABILITIES
            ================================================== */}

            {result.class_probabilities && (

              <div className="disease-probabilities">

                <div className="disease-subsection-heading">

                  <span>
                    MODEL ANALYSIS
                  </span>

                  <h3>
                    AI Prediction Probabilities
                  </h3>

                  <p>
                    Probability assigned by the trained
                    EfficientNet-B0 model to each disease class.
                  </p>

                </div>


                <div className="probability-list">

                  {Object.entries(
                    result.class_probabilities
                  ).map(
                    ([disease, probability]) => (

                      <div
                        className="probability-row"
                        key={disease}
                      >

                        <div className="probability-label">

                          <span>
                            {disease}
                          </span>

                          <strong>
                            {probability}%
                          </strong>

                        </div>

                        <div className="probability-track">

                          <div
                            className="probability-fill"
                            style={{
                              width: `${probability}%`,
                            }}
                          />

                        </div>

                      </div>

                    )
                  )}

                </div>

              </div>

            )}


            {/* ==================================================
                MODEL INFORMATION
            ================================================== */}

            <div className="disease-model-info">

              <div>

                <small>
                  MODEL
                </small>

                <strong>
                  {result.model || "EfficientNet-B0"}
                </strong>

              </div>

              <div>

                <small>
                  INPUT SIZE
                </small>

                <strong>
                  {result.image_size || 224} ×{" "}
                  {result.image_size || 224}
                </strong>

              </div>

              <div>

                <small>
                  DISEASE CLASSES
                </small>

                <strong>
                  {result.classes?.length || 8}
                </strong>

              </div>

            </div>


            {/* ==================================================
                DISCLAIMER
            ================================================== */}

            <div className="disease-disclaimer">

              <span>
                ℹ️
              </span>

              <p>
                This is an AI-based prediction from the uploaded
                image. The confidence score indicates the model's
                prediction confidence and should not be treated as
                a confirmed field diagnosis.
              </p>

            </div>

          </section>

        )}


        {/* ====================================================
            NEXT MODULES
        ==================================================== */}

        {result?.success && (

          <section className="disease-next-section">

            <div>

              <span className="module-tag">
                CONTINUE AGRIVISION WORKFLOW
              </span>

              <h2>
                Continue with the next operation
              </h2>

              <p>
                Use the disease result together with the
                corresponding field and farmer information
                for the next AgriVision modules.
              </p>

            </div>


            <div className="disease-next-buttons">

              <button
                type="button"
                className="disease-drone-button"
                onClick={handleDroneRoute}
              >
                🚁 Optimized Drone Route
                <span>→</span>
              </button>


              <button
                type="button"
                className="disease-resource-button"
                onClick={handleResourceEstimation}
              >
                📊 Resource Estimation
                <span>→</span>
              </button>

            </div>

          </section>

        )}

      </main>

    </div>
  );
};

export default DiseaseDetection;