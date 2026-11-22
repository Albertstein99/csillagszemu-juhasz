"""Independent integration smoke test using Google's public example portrait."""
import pathlib
import sys
import time
import cv2
import numpy as np

ROOT=pathlib.Path(sys.argv[2]) if len(sys.argv)>2 else pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from csillagszem.vision import Vision

def check(path):
    bgr=cv2.imread(str(path))
    if bgr is None:
        raise ValueError('Cannot load test portrait')
    detector=Vision(ROOT/'models')
    try:
        result,status=detector.read(bgr,time.monotonic())
        if result is None:
            raise AssertionError('Expected visible eyes on the fixture: '+status)
        features,quality=result
        assert len(features)==12 and np.isfinite(features).all() and 0<quality<=1
        print('Real portrait passed face, iris, head pose and binocular gaze inference.')
    finally:
        detector.close()

if __name__=='__main__':
    check(sys.argv[1])
