FROM python:3.12-slim

# No apt-get step, deliberately.
#
# There was one: `apt-get install libglib2.0-0`, carried over from the days
# when opencv-python (the full build, with GUI support) needed it. The headless
# wheel does not — verified by building without it and running the whole
# pipeline, detection through liveness through matching, on real photographs.
#
# Removing it is not tidiness. It was the only thing here that reached a
# Debian mirror, and on a server whose network could not get to deb.debian.org
# the install failed at that line with a timeout and a 404 — a face service
# that would not build because of a package it never used.
#
# If you pin opencv-python-headless below 4.10, check this again: older wheels
# did link against libglib, and the failure is an ImportError on `import cv2`
# rather than anything about the missing package.

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
