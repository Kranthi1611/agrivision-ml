

import { useNavigate } from "react-router-dom";

const Navbar = () => {
  const navigate = useNavigate();
  const user = JSON.parse(localStorage.getItem("agrivision_user") || "null");

  const handleLogout = () => {
    localStorage.removeItem("agrivision_user");
    navigate("/");
  };

  return (
    <header className="navbar">
      <div className="logo-section">
        <div className="logo-mark">
          <span>🌿</span>
        </div>
        <div className="logo-content">
          <h2>Agri<span>Vision</span></h2>
          <p>Smart Vision. Smarter Cultivation.</p>
        </div>
      </div>

      <nav className="nav-links">
        <a href="#" className="active">Home</a>
        <a href="#about">About</a>
        <a href="#features">Features</a>
        <a href="#how-it-works">How It Works</a>
        <a href="#impact">Impact</a>
        <a href="#contact">Contact</a>
      </nav>

      <div className="nav-right">
        <div className="india-message">
          <span className="india-leaf">🌱</span>
          <div>
            <strong>For a</strong>
            <span>Greener India</span>
          </div>
        </div>

        {user ? (
          <div className="nav-user">
            <span className="nav-username">👤 {user.name}</span>
            <button className="logout-button" onClick={handleLogout}>
              Logout
            </button>
          </div>
        ) : (
          <button className="login-button" onClick={() => navigate("/")}>
            <span>♙</span>
            Login / Sign Up
          </button>
        )}
      </div>
    </header>
  );
};

export default Navbar;