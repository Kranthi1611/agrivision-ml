const Footer = () => {

  return (

    <footer className="footer">

      <div className="footer-main">


        {/* BRAND */}

        <div className="footer-brand">

          <div className="footer-logo">
            🌿
          </div>

          <div>

            <h2>
              Agri<span>Vision</span>
            </h2>

            <p>
              Smart Vision. Smarter Cultivation.
            </p>

          </div>

        </div>


        {/* LINKS */}

        <div className="footer-links">

          <a href="#">Home</a>
          <span>|</span>

          <a href="#about">About</a>
          <span>|</span>

          <a href="#features">Features</a>
          <span>|</span>

          <a href="#how-it-works">How It Works</a>
          <span>|</span>

          <a href="#impact">Impact</a>
          <span>|</span>

          <a href="#contact">Contact</a>

        </div>


        {/* SOCIAL */}

        <div className="social-icons">

          <a href="#" aria-label="LinkedIn">
            in
          </a>

          <a href="#" aria-label="X">
            𝕏
          </a>

          <a href="#" aria-label="YouTube">
            ▶
          </a>

          <a href="#" aria-label="Instagram">
            ◎
          </a>

        </div>


        {/* MESSAGE */}

        <div className="footer-message">

          <span>🌱</span>

          <div>

            <strong>Growing Together</strong>

            <p>
              for a Better Tomorrow
            </p>

          </div>

        </div>

      </div>


      <div className="footer-bottom">

        <p>
          © 2026 AgriVision. All rights reserved.
        </p>

        <p>
          Made with <span>♥</span> for Indian Agriculture
        </p>

      </div>

    </footer>

  );

};

export default Footer;