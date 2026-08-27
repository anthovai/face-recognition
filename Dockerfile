FROM python:3.12-slim

# opencv-python-headless still needs libGL's stubs for some codecs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests
# Calibration runs in this image on purpose: the thresholds have to be measured
# against the same models and the same OpenCV build that will make the
# decisions in production.
COPY calibrate.py calibrate_detection.py bench_load.py ./

# Model weights are bind-mounted read-only from the host (see
# docker-compose.yml) rather than copied in, so the licence-audited files stay
# visible and auditable outside the image.
ENV FACE_MODELS_DIR=/app/models

EXPOSE 9000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
