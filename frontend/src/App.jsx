import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

import Login from "./pages/Login";
import Home from "./pages/Home";
import OptimizedDronePath from "./pages/OptimizedDronePath";
import FieldMapping from "./pages/FieldMapping";
import DiseaseDetection from "./pages/DiseaseDetection";
import ResourceEstimation from "./pages/ResourceEstimation";
import FarmerNotifications from "./pages/FarmerNotifications";

const ProtectedRoute = ({ children }) => {
  const user = localStorage.getItem("agrivision_user");

  return user ? children : <Navigate to="/" replace />;
};

const PublicRoute = ({ children }) => {
  const user = localStorage.getItem("agrivision_user");

  return user ? <Navigate to="/home" replace /> : children;
};

function App() {
  return (
    <BrowserRouter>
      <Routes>

        {/* Login Page */}
        <Route
          path="/"
          element={
            <PublicRoute>
              <Login />
            </PublicRoute>
          }
        />

        {/* Main AgriVision Home */}
        <Route
          path="/home"
          element={
            <ProtectedRoute>
              <Home />
            </ProtectedRoute>
          }
        />

        {/* Field Mapping Module */}
        <Route
          path="/field-mapping"
          element={
            <ProtectedRoute>
              <FieldMapping />
            </ProtectedRoute>
          }
        />

        {/* Disease Detection Module */}
        <Route
          path="/disease-detection"
          element={
            <ProtectedRoute>
              <DiseaseDetection />
            </ProtectedRoute>
          }
        />

        {/* Optimized Drone Path Module */}
        <Route
          path="/optimized-drone-path"
          element={
            <ProtectedRoute>
              <OptimizedDronePath />
            </ProtectedRoute>
          }
        />

        {/* Resource Estimation Module */}
        <Route
          path="/resource-estimation"
          element={
            <ProtectedRoute>
              <ResourceEstimation />
            </ProtectedRoute>
          }
        />

        {/* Farmer Notifications Module */}
        <Route
          path="/farmer-notifications"
          element={
            <ProtectedRoute>
              <FarmerNotifications />
            </ProtectedRoute>
          }
        />

        {/* Unknown URL */}
        <Route
          path="*"
          element={<Navigate to="/" replace />}
        />

      </Routes>
    </BrowserRouter>
  );
}

export default App;