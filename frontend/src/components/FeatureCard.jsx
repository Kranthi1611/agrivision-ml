const FeatureCard = ({
  icon,
  title,
  description,
  onClick
}) => {

  return (
    <div
      className="feature-card"
      onClick={onClick}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={(event) => {
        if (
          onClick &&
          (event.key === "Enter" || event.key === " ")
        ) {
          event.preventDefault();
          onClick();
        }
      }}
    >

      <div className="feature-icon">
        {icon}
      </div>

      <div className="feature-content">

        <h3>{title}</h3>

        <p>{description}</p>

      </div>

    </div>
  );
};

export default FeatureCard;