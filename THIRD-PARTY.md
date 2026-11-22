# Third-party components

Csillagszemű Juhász's original application and installer code is MIT-licensed. Third-party components retain their upstream terms. Setup downloads these components separately. The application bundle includes the original code, notices and source links.

| Component | Source |
| --- | --- |
| CPython and its bundled Tcl/Tk and libraries, distributed by python-build-standalone | https://github.com/astral-sh/python-build-standalone |
| NumPy | https://numpy.org/ |
| OpenCV and opencv-contrib-python Windows wheels | https://github.com/opencv/opencv-python |
| cv2-enumerate-cameras | https://github.com/lukehugh/cv2_enumerate_cameras |
| MediaPipe and the Face Landmarker model | https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker |
| OpenVINO runtime | https://github.com/openvinotoolkit/openvino |
| Open Model Zoo gaze-estimation-adas-0002 | https://github.com/openvinotoolkit/open_model_zoo/tree/master/models/intel/gaze-estimation-adas-0002 |
| Open Model Zoo head-pose-estimation-adas-0001 | https://github.com/openvinotoolkit/open_model_zoo/tree/master/models/intel/head-pose-estimation-adas-0001 |

The Open Model Zoo FP16 files use the SHA-384 digests from the corresponding upstream model.yml manifests. The Face Landmarker task file uses model revision float16/1. Source URLs and expected digests are in setup/assets.py. The Python distribution and installed wheels retain their bundled license files. The public MediaPipe example portrait is downloaded for the CI smoke test and is excluded from the distribution.
