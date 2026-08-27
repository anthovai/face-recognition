#!/bin/sh
# Download the OpenCV Zoo weights. See LICENSES.md before adding anything here.
set -e
cd "$(dirname "$0")"

# opencv_zoo stores weights in Git LFS, so raw.githubusercontent serves a
# pointer stub instead of the model. media.githubusercontent.com/media/ is the
# endpoint that resolves LFS objects.
BASE=https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models

fetch() {
    if [ -f "$2" ]; then
        echo "have $2"
        return
    fi
    echo "fetching $2"
    curl -fL "$1" -o "$2"
    # A pointer stub is a few hundred bytes; a real model is hundreds of KB.
    if [ "$(wc -c < "$2")" -lt 10000 ]; then
        echo "ERROR: $2 came back as an LFS pointer, not the model" >&2
        rm -f "$2"
        exit 1
    fi
}

fetch "$BASE/face_detection_yunet/face_detection_yunet_2023mar.onnx" \
      face_detection_yunet_2023mar.onnx
fetch "$BASE/face_recognition_sface/face_recognition_sface_2021dec.onnx" \
      face_recognition_sface_2021dec.onnx

echo
echo "models present:"
ls -la ./*.onnx
