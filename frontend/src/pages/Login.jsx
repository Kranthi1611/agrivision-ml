import { useState } from "react";
import { useNavigate } from "react-router-dom";
import "../App.css";

const Login = () => {
  const navigate = useNavigate();

  const [tab, setTab] = useState("login");

  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [showLoginPassword, setShowLoginPassword] = useState(false);
  const [loginError, setLoginError] = useState("");

  const [signupName, setSignupName] = useState("");
  const [signupEmail, setSignupEmail] = useState("");
  const [signupPassword, setSignupPassword] = useState("");
  const [signupConfirm, setSignupConfirm] = useState("");
  const [showSignupPassword, setShowSignupPassword] = useState(false);
  const [showSignupConfirm, setShowSignupConfirm] = useState(false);
  const [signupError, setSignupError] = useState("");

  const handleLogin = (e) => {
    e.preventDefault();
    setLoginError("");

    if (!loginEmail || !loginPassword) {
      setLoginError("Please fill in all fields.");
      return;
    }

    const users = JSON.parse(localStorage.getItem("agrivision_users") || "[]");
    const match = users.find(
      (u) => u.email === loginEmail && u.password === loginPassword
    );

    if (!match) {
      setLoginError("Invalid email or password. Please try again.");
      return;
    }

    localStorage.setItem(
      "agrivision_user",
      JSON.stringify({ name: match.name, email: match.email })
    );

    navigate("/home");
  };

  const handleSignup = (e) => {
    e.preventDefault();
    setSignupError("");

    if (!signupName || !signupEmail || !signupPassword || !signupConfirm) {
      setSignupError("Please fill in all fields.");
      return;
    }

    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailPattern.test(signupEmail)) {
      setSignupError("Please enter a valid email address.");
      return;
    }

    if (signupPassword.length < 6) {
      setSignupError("Password must be at least 6 characters.");
      return;
    }

    if (signupPassword !== signupConfirm) {
      setSignupError("Passwords do not match.");
      return;
    }

    const users = JSON.parse(localStorage.getItem("agrivision_users") || "[]");
    if (users.find((u) => u.email === signupEmail)) {
      setSignupError("An account with this email already exists.");
      return;
    }

    users.push({ name: signupName, email: signupEmail, password: signupPassword });
    localStorage.setItem("agrivision_users", JSON.stringify(users));

    localStorage.setItem(
      "agrivision_user",
      JSON.stringify({ name: signupName, email: signupEmail })
    );

    navigate("/home");
  };

  return (
    <div className="login-page">
      <div className="login-card">

        <div className="login-logo">🌿</div>
        <h1>Agri<span>Vision</span></h1>
        <p className="login-subtitle">Data Today. Healthier Fields Tomorrow.</p>

        <div className="login-divider"></div>

        <div className="login-tabs">
          <button
            className={`login-tab ${tab === "login" ? "active" : ""}`}
            onClick={() => { setTab("login"); setLoginError(""); }}
          >
            Login
          </button>
          <button
            className={`login-tab ${tab === "signup" ? "active" : ""}`}
            onClick={() => { setTab("signup"); setSignupError(""); }}
          >
            Sign Up
          </button>
        </div>

        {tab === "login" && (
          <>
            <h2>Welcome Back</h2>
            <p className="login-description">Sign in to your AgriVision account</p>

            <form onSubmit={handleLogin}>
              <div className="login-field">
                <label>Email Address</label>
                <input
                  type="email"
                  placeholder="you@example.com"
                  value={loginEmail}
                  onChange={(e) => setLoginEmail(e.target.value)}
                />
              </div>

              <div className="login-field">
                <label>Password</label>
                <div className="password-wrapper">
                  <input
                    type={showLoginPassword ? "text" : "password"}
                    placeholder="Enter your password"
                    value={loginPassword}
                    onChange={(e) => setLoginPassword(e.target.value)}
                  />
                  <button
                    type="button"
                    className="password-toggle"
                    onClick={() => setShowLoginPassword((p) => !p)}
                  >
                    {showLoginPassword ? "🙈" : "👁️"}
                  </button>
                </div>
              </div>

              {loginError && <p className="login-error">⚠️ {loginError}</p>}

              <button type="submit" className="login-submit">
                Sign In <span>→</span>
              </button>
            </form>

            <p className="login-note">
              Don't have an account?{" "}
              <span
                className="login-switch"
                onClick={() => { setTab("signup"); setLoginError(""); }}
              >
                Create one
              </span>
            </p>
          </>
        )}

        {tab === "signup" && (
          <>
            <h2>Create Account</h2>
            <p className="login-description">Join AgriVision and start your smart farming journey</p>

            <form onSubmit={handleSignup}>
              <div className="login-field">
                <label>Full Name</label>
                <input
                  type="text"
                  placeholder="Your full name"
                  value={signupName}
                  onChange={(e) => setSignupName(e.target.value)}
                />
              </div>

              <div className="login-field">
                <label>Email Address</label>
                <input
                  type="email"
                  placeholder="you@example.com"
                  value={signupEmail}
                  onChange={(e) => setSignupEmail(e.target.value)}
                />
              </div>

              <div className="login-field">
                <label>Password</label>
                <div className="password-wrapper">
                  <input
                    type={showSignupPassword ? "text" : "password"}
                    placeholder="Min. 6 characters"
                    value={signupPassword}
                    onChange={(e) => setSignupPassword(e.target.value)}
                  />
                  <button
                    type="button"
                    className="password-toggle"
                    onClick={() => setShowSignupPassword((p) => !p)}
                  >
                    {showSignupPassword ? "🙈" : "👁️"}
                  </button>
                </div>
              </div>

              <div className="login-field">
                <label>Confirm Password</label>
                <div className="password-wrapper">
                  <input
                    type={showSignupConfirm ? "text" : "password"}
                    placeholder="Re-enter your password"
                    value={signupConfirm}
                    onChange={(e) => setSignupConfirm(e.target.value)}
                  />
                  <button
                    type="button"
                    className="password-toggle"
                    onClick={() => setShowSignupConfirm((p) => !p)}
                  >
                    {showSignupConfirm ? "🙈" : "👁️"}
                  </button>
                </div>
              </div>

              {signupError && <p className="login-error">⚠️ {signupError}</p>}

              <button type="submit" className="login-submit">
                Create Account <span>→</span>
              </button>
            </form>

            <p className="login-note">
              Already have an account?{" "}
              <span
                className="login-switch"
                onClick={() => { setTab("login"); setSignupError(""); }}
              >
                Sign in
              </span>
            </p>
          </>
        )}

      </div>
    </div>
  );
};

export default Login;