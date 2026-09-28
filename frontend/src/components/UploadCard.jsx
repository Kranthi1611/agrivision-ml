import { useRef, useState } from "react";

const UploadCard = ({
  type,
  title,
  description,
  acceptedTypes,
  icon,
  onFileSelect
}) => {
  const inputRef = useRef(null);

  const [selectedFile, setSelectedFile] = useState(null);
  const [dragging, setDragging] = useState(false);

  const handleFile = (file) => {
    if (!file) return;

    setSelectedFile(file);

    if (onFileSelect) {
      onFileSelect(file);
    }
  };

  const handleInputChange = (event) => {
    const file = event.target.files[0];
    handleFile(file);
  };

  const handleDrop = (event) => {
    event.preventDefault();
    setDragging(false);

    const file = event.dataTransfer.files[0];
    handleFile(file);
  };

  const handleRemoveFile = (event) => {
    event.stopPropagation();

    setSelectedFile(null);

    if (inputRef.current) {
      inputRef.current.value = "";
    }

    if (onFileSelect) {
      onFileSelect(null);
    }
  };

  const formatSize = (bytes) => {
    if (bytes < 1024) {
      return `${bytes} Bytes`;
    }

    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }

    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="glass-upload-card">

      <div className="upload-card-heading">

        <div className={`upload-heading-icon ${type}`}>
          {icon}
        </div>

        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>

      </div>


      <div
        className={`drop-zone ${dragging ? "dragging" : ""}`}

        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}

        onDragLeave={() => setDragging(false)}

        onDrop={handleDrop}

        onClick={() => inputRef.current.click()}
      >

        <div className="drop-icon">
          {type === "image" ? "☁" : "▤"}
        </div>


        <h3>
          {type === "image"
            ? "Drag & drop field image here"
            : "Drag & drop farmer data file here"}
        </h3>


        <span className="or-text">
          or
        </span>


        <button
          className="browse-button"

          onClick={(event) => {
            event.stopPropagation();
            inputRef.current.click();
          }}
        >
          📁 Browse Files
        </button>


        <input
          ref={inputRef}
          type="file"
          hidden
          accept={acceptedTypes}
          onChange={handleInputChange}
        />


        <p className="file-support">

          Supports:{" "}

          {type === "image"
            ? "JPG, PNG, TIFF"
            : "Excel (.xlsx, .xls) or CSV"}

          <br />

          Maximum size: 50 MB

        </p>

      </div>


      {type === "data" && (
        <div className="data-information">

          <span>ⓘ</span>

          <p>
            The file should contain farmer details,
            survey numbers, land area, crop information,
            planting date and reported diseases.
          </p>

        </div>
      )}


      <div
        className={`selected-file ${
          selectedFile ? "has-file" : ""
        }`}
      >

        <div className="selected-file-icon">

          {selectedFile
            ? type === "image"
              ? "🖼️"
              : "📊"
            : type === "image"
              ? "🖼️"
              : "📄"}

        </div>


        <div className="selected-file-info">

          {selectedFile ? (
            <>
              <strong>
                {selectedFile.name}
              </strong>

              <small>
                {formatSize(selectedFile.size)}
              </small>
            </>
          ) : (
            <>
              <strong>
                {type === "image"
                  ? "No image selected"
                  : "No farmer data selected"}
              </strong>

              <small>
                {type === "image"
                  ? "Field imagery will appear here"
                  : "Farmer information file will appear here"}
              </small>
            </>
          )}

        </div>


        {selectedFile && (
          <span
            className="remove-file"
            onClick={handleRemoveFile}
            title="Remove file"
          >
            ×
          </span>
        )}

      </div>

    </div>
  );
};

export default UploadCard;