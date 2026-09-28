import { useState } from "react";
import { useNavigate } from "react-router-dom";

import Navbar from "../components/Navbar";
import UploadCard from "../components/UploadCard";
import FeatureCard from "../components/FeatureCard";
import Footer from "../components/Footer";

import "../App.css";

const Home = () => {
  const navigate = useNavigate();

  // Uploaded files
  const [fieldFile, setFieldFile] = useState(null);
  const [farmerFile, setFarmerFile] = useState(null);

  // General error
  const [error, setError] = useState("");

  // Selected module
  const [selectedModule, setSelectedModule] = useState(null);

  // ML states
  const [processing, setProcessing] = useState(false);
  const [mlResult, setMlResult] = useState(null);
  const [mlError, setMlError] = useState("");

  const features = [
    {
      icon: "🗺️",
      title: "Field Mapping",
      description: "Convert imagery to accurate field boundaries"
    },
    {
      icon: "🌱",
      title: "Disease Detection",
      description: "Identify crop diseases using AI"
    },
    {
      icon: "🧪",
      title: "Resource Estimation",
      description: "Calculate fertilizers, pesticides and drone costs"
    },
    {
      icon: "🚁",
      title: "Optimized Drone Path",
      description: "Minimize travel distance and fuel consumption"
    },
    {
      icon: "🔔",
      title: "Farmer Notifications",
      description: "Get personalized cost and treatment details"
    }
  ];

  // ==========================================================
  // GENERAL PROCESS BUTTON
  // ==========================================================

  const handleProcess = () => {

    if (!fieldFile && !farmerFile) {
      setError(
        "Please upload both the field image and farmer data file."
      );
      return;
    }

    if (!fieldFile) {
      setError("Please upload the field image.");
      return;
    }

    if (!farmerFile) {
      setError("Please upload the farmer data file.");
      return;
    }

    setError("");

    alert(
      "Files received successfully. ML processing will be connected here."
    );
  };


  // ==========================================================
  // OPTIMIZED DRONE PATH
  // ==========================================================

  const handleOptimizedDronePath = () => {
    setError("");

    // Only field image is required for this module
    if (!fieldFile) {
      setError(
        "Please upload the field image to generate the optimized drone path."
      );
      return;
    }

    // Open the dedicated Optimized Drone Path page
    navigate("/optimized-drone-path", {
      state: {
        fieldFile: fieldFile,
      },
    });
  };


  // ==========================================================
  // DISEASE DETECTION
  // ==========================================================

  const handleDiseaseDetection = () => {
    setError("");

    // Disease Detection uses a separate crop/leaf image.
    // No field image or farmer data is required here.
    navigate("/disease-detection");
  };


  // ==========================================================
  // FIELD MAPPING
  // ==========================================================

  const handleFieldMapping = () => {
    setError("");

    // Both field image and farmer data are required
    if (!fieldFile && !farmerFile) {
      setError(
        "Please upload both the field image and farmer data file."
      );
      return;
    }

    if (!fieldFile) {
      setError("Please upload the field image.");
      return;
    }

    if (!farmerFile) {
      setError("Please upload the farmer data file.");
      return;
    }

    // Open the dedicated Field Mapping page
    navigate("/field-mapping", {
      state: {
        fieldFile: fieldFile,
        farmerFile: farmerFile,
      },
    });
  };


  // ==========================================================
  // RESOURCE ESTIMATION
  // ==========================================================

  const handleResourceEstimation = () => {
    setError("");

    // Resource Estimation requires only farmer data
    if (!farmerFile) {
      setError("Please upload the farmer data file.");
      return;
    }

    navigate("/resource-estimation", {
      state: {
        farmerFile: farmerFile,
      },
    });
  };


  // ==========================================================
  // FARMER NOTIFICATIONS
  // ==========================================================

  const handleFarmerNotifications = () => {
    setError("");

    // Farmer data is required for notifications
    if (!farmerFile) {
      setError("Please upload the farmer data file.");
      return;
    }

    navigate("/farmer-notifications", {
      state: {
        farmerFile: farmerFile,
      },
    });
  };


  // ==========================================================
  // RUN ML API
  // ==========================================================

  const runOptimizedDronePath = async () => {

    if (!fieldFile) {

      setMlError(
        "Field image is required."
      );

      return;
    }

    setProcessing(true);
    setMlError("");
    setMlResult(null);

    try {

      const formData = new FormData();

      formData.append(
        "field_image",
        fieldFile
      );

      const response = await fetch(
        "http://127.0.0.1:8000/optimized-drone-path",
        {
          method: "POST",
          body: formData
        }
      );

      const data = await response.json();

      if (!response.ok || !data.success) {

        throw new Error(
          data.message ||
          "Optimized path generation failed."
        );
      }

      // Add cache-busting parameter so a new result
      // is displayed every time.
      const timestamp = Date.now();

      setMlResult({
        ...data,
        route_image_url:
          `http://127.0.0.1:8000${data.route_image}?t=${timestamp}`,

        route_csv_url:
          `http://127.0.0.1:8000${data.route_csv}`
      });

    } catch (error) {

      console.error(
        "ML API Error:",
        error
      );

      setMlError(
        error.message ||
        "Unable to connect to the AgriVision ML service."
      );

    } finally {

      setProcessing(false);

    }
  };


  // ==========================================================
  // BACK TO MODULES
  // ==========================================================

  const closeModule = () => {

    setSelectedModule(null);
    setMlResult(null);
    setMlError("");

  };


  return (

    <div className="app">

      <Navbar />


      {/* =====================================================
          HERO
      ===================================================== */}

      <main className="hero">

        <div className="hero-overlay"></div>

        <div className="hero-content">


          {/* LABEL */}

          <div className="hero-label">

            AI <span>×</span>
            DRONES <span>×</span>
            DATA <span>×</span>
            FARMERS <span>×</span>
            SUSTAINABLE INDIA

          </div>


          {/* TITLE */}

          <h1>

            Empowering Farmers

            <br />

            with <span>Smart Agriculture</span>

          </h1>


          {/* DESCRIPTION */}

          <p className="hero-description">

            Upload field imagery and farmer data. Let AI do the rest —

            <br />

            from field mapping to disease detection, resource estimation,
            and optimized drone operations.

          </p>


          {/* =================================================
              UPLOADS
          ================================================= */}

          <section className="upload-section">

            <UploadCard

              type="image"

              title="Upload Field Image"

              description="Upload a satellite or drone image of the complete field region"

              acceptedTypes=".jpg,.jpeg,.png,.tif,.tiff"

              icon="🖼️"

              onFileSelect={setFieldFile}

            />


            <UploadCard

              type="data"

              title="Upload Farmer Data"

              description="Upload the file containing complete farmer and field details"

              acceptedTypes=".csv,.xlsx,.xls"

              icon="📄"

              onFileSelect={setFarmerFile}

            />

          </section>


          {/* ERROR */}

          {error && (

            <p className="upload-error">

              ⚠️ {error}

            </p>

          )}


          {/* =================================================
              PROCESS BUTTON
          ================================================= */}

          <div className="process-section">

            <button

              className="process-button"

              onClick={handleProcess}

            >

              <span>✦</span>

              Submit & Process

              <span>→</span>

            </button>


            <p>

              Your data will be securely processed by the
              AgriVision system.

            </p>

          </div>


          {/* =================================================
              FEATURES
          ================================================= */}

          <section
            className="feature-grid"
            id="features"
          >

            {features.map(
              (feature, index) => (

                <FeatureCard

                  key={index}

                  icon={feature.icon}

                  title={feature.title}

                  description={feature.description}

                  onClick={
                    feature.title === "Field Mapping"
                      ? handleFieldMapping
                      : feature.title === "Disease Detection"
                      ? handleDiseaseDetection
                      : feature.title === "Optimized Drone Path"
                      ? handleOptimizedDronePath
                      : feature.title === "Resource Estimation"
                      ? handleResourceEstimation
                      : feature.title === "Farmer Notifications"
                      ? handleFarmerNotifications
                      : undefined
                  }

                />

              )
            )}

          </section>


          {/* =================================================
              OPTIMIZED DRONE PATH RESULT
          ================================================= */}

          {selectedModule === "optimized-drone-path" && (

            <section
              className="module-result"
              id="module-result"
            >


              {/* HEADER */}

              <div className="module-result-header">

                <div>

                  <div className="module-result-title">

                    <span>🚁</span>

                    <h2>
                      Optimized Drone Path
                    </h2>

                  </div>

                  <p>

                    Generate an efficient drone coverage
                    route directly from the uploaded field imagery.

                  </p>

                </div>


                <button
                  className="module-close-button"
                  onClick={closeModule}
                >
                  ✕
                </button>

              </div>


              {/* =================================================
                  INPUT INFORMATION
              ================================================= */}

              <div className="module-info-grid">

                <div className="module-info-card">

                  <span>🖼️</span>

                  <div>

                    <small>
                      FIELD IMAGE
                    </small>

                    <strong>
                      {fieldFile?.name}
                    </strong>

                  </div>

                </div>


                <div className="module-info-card">

                  <span>✓</span>

                  <div>

                    <small>
                      FARMER DATA
                    </small>

                    <strong>
                      Not Required
                    </strong>

                  </div>

                </div>

              </div>


              {/* =================================================
                  EXPLANATION
              ================================================= */}

              <div className="module-explanation">

                <h3>
                  What does this module do?
                </h3>

                <p>

                  AgriVision analyzes the uploaded field image
                  to identify the usable agricultural region.
                  It excludes non-operational areas such as
                  roads and water bodies, generates parallel
                  drone coverage lines, and organizes them into
                  an efficient route to reduce unnecessary
                  movement.

                </p>

              </div>


              {/* =================================================
                  GENERATE BUTTON
              ================================================= */}

              {!mlResult && (

                <div className="generate-section">

                  <button

                    className="generate-path-button"

                    onClick={runOptimizedDronePath}

                    disabled={processing}

                  >

                    {processing ? (

                      <>
                        <span className="loading-spinner"></span>
                        Processing Field Image...
                      </>

                    ) : (

                      <>
                        🚁 Generate Optimized Path
                        <span>→</span>
                      </>

                    )}

                  </button>


                  {processing && (

                    <p className="processing-message">

                      AI is analyzing the field and calculating
                      the optimized drone coverage route.

                    </p>

                  )}

                </div>

              )}


              {/* =================================================
                  ERROR
              ================================================= */}

              {mlError && (

                <div className="ml-error">

                  ⚠️ {mlError}

                </div>

              )}


              {/* =================================================
                  RESULTS
              ================================================= */}

              {mlResult && (

                <div className="drone-results">


                  {/* IMAGE COMPARISON */}

                  <div className="image-comparison">


                    {/* ORIGINAL */}

                    <div className="result-image-card">

                      <div className="result-image-header">

                        <span>
                          Original Field Image
                        </span>

                        <small>
                          INPUT
                        </small>

                      </div>

                      <img
                        src={URL.createObjectURL(fieldFile)}
                        alt="Original field"
                      />

                    </div>


                    {/* ARROW */}

                    <div className="comparison-arrow">

                      →

                    </div>


                    {/* OPTIMIZED */}

                    <div className="result-image-card">

                      <div className="result-image-header">

                        <span>
                          Optimized Drone Path
                        </span>

                        <small>
                          ML OUTPUT
                        </small>

                      </div>

                      <img
                        src={mlResult.route_image_url}
                        alt="Optimized drone route"
                      />

                    </div>

                  </div>


                  {/* =================================================
                      STATISTICS
                  ================================================= */}

                  <div className="route-statistics">

                    <div className="stat-card">

                      <span>📏</span>

                      <small>
                        COVERAGE DISTANCE
                      </small>

                      <strong>
                        Generated by ML
                      </strong>

                    </div>


                    <div className="stat-card">

                      <span>↔️</span>

                      <small>
                        TRANSIT DISTANCE
                      </small>

                      <strong>
                        Generated by ML
                      </strong>

                    </div>


                    <div className="stat-card">

                      <span>🛣️</span>

                      <small>
                        TOTAL ROUTE
                      </small>

                      <strong>
                        Generated by ML
                      </strong>

                    </div>


                    <div className="stat-card">

                      <span>〰️</span>

                      <small>
                        COVERAGE LINES
                      </small>

                      <strong>
                        Generated by ML
                      </strong>

                    </div>

                  </div>


                  {/* =================================================
                      DETAILS
                  ================================================= */}

                  <div className="route-details">

                    <h3>
                      How the route was generated
                    </h3>

                    <div className="route-steps">

                      <div>

                        <span>1</span>

                        <p>
                          <strong>Field Detection</strong>
                          <br />
                          The usable agricultural boundary
                          was identified from the image.
                        </p>

                      </div>


                      <div>

                        <span>2</span>

                        <p>
                          <strong>Coverage Planning</strong>
                          <br />
                          Parallel coverage lines were created
                          across the usable field.
                        </p>

                      </div>


                      <div>

                        <span>3</span>

                        <p>
                          <strong>Route Optimization</strong>
                          <br />
                          The coverage segments were arranged
                          to minimize unnecessary transit.
                        </p>

                      </div>


                      <div>

                        <span>4</span>

                        <p>
                          <strong>Final Route</strong>
                          <br />
                          Start, coverage path and end point
                          were combined into the final route.
                        </p>

                      </div>

                    </div>

                  </div>


                  {/* =================================================
                      ACTIONS
                  ================================================= */}

                  <div className="result-actions">

                    <a
                      href={mlResult.route_csv_url}
                      download="optimized_drone_route.csv"
                      className="download-route-button"
                    >
                      📥 Download Route CSV
                    </a>


                    <button
                      className="back-module-button"
                      onClick={closeModule}
                    >
                      ← Back to Modules
                    </button>

                  </div>

                </div>

              )}

            </section>

          )}

        </div>

      </main>


      <Footer />

    </div>
  );
};

export default Home;