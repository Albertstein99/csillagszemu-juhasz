"""Camera-side inference. Imported inside isolated camera processes only."""
import math
from pathlib import Path
import numpy as np


def eye_geometry(points, corners, iris, lids):
    a,b = points[list(corners)]
    axis = b-a
    width = np.linalg.norm(axis)
    if width < 12:
        return None
    axis /= width
    vertical = np.array([-axis[1],axis[0]])
    mid = (a+b)/2
    rel = (points[iris]-mid)/width
    openness = abs((points[lids[1]]-points[lids[0]]) @ vertical)/width
    return mid, width, np.array([rel @ axis, rel @ vertical]), openness


class Vision:
    def __init__(self, directory):
        import cv2
        import mediapipe as mp
        import openvino as ov
        self.cv, self.mp = cv2, mp
        root = Path(directory)
        cv2.setNumThreads(1)
        vision = mp.tasks.vision
        options = vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_buffer=(root/'face_landmarker.task').read_bytes()),
            running_mode=vision.RunningMode.VIDEO, num_faces=2,
            min_tracking_confidence=.55, min_face_presence_confidence=.58)
        self.face = vision.FaceLandmarker.create_from_options(options)
        core = ov.Core()
        settings = {'NUM_STREAMS':'1', 'INFERENCE_NUM_THREADS':'2'}
        self.pose = core.compile_model(str(root/'head-pose-estimation-adas-0001.xml'),'CPU',settings)
        self.gaze = core.compile_model(str(root/'gaze-estimation-adas-0002.xml'),'CPU',settings)
        self.last_ms = -1

    def blob(self, frame, center, side):
        h,w = frame.shape[:2]
        x,y = np.rint(center-side/2).astype(int)
        n = max(2,round(side))
        if x < 0 or y < 0 or x+n > w or y+n > h:
            return None
        data = self.cv.resize(frame[y:y+n,x:x+n], (60,60))
        return np.ascontiguousarray(data.transpose(2,0,1)[None],dtype=np.float32)

    def read(self, frame, stamp):
        h,w = frame.shape[:2]
        rgb = self.cv.cvtColor(frame,self.cv.COLOR_BGR2RGB)
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB,data=rgb)
        self.last_ms = max(self.last_ms+1,int(stamp*1000))
        faces = self.face.detect_for_video(image,self.last_ms).face_landmarks
        if len(faces)!=1:
            return None, "No face" if not faces else "Multiple faces"
        p = np.array([(pt.x*w,pt.y*h) for pt in faces[0]])
        if len(p)<478 or not np.isfinite(p).all():
            return None, "Landmarks unavailable"
        # Eye pairs are ordered from left to right in the unmirrored camera image.
        left = eye_geometry(p,(33,133),468,(159,145))
        right = eye_geometry(p,(362,263),473,(386,374))
        if left is None or right is None:
            return None,"Eyes too small"
        aperture = min(left[3],right[3])
        if aperture < .115 or max(abs(left[2][0]),abs(right[2][0])) > .53:
            return None,"Blink or occlusion"
        low,high = np.min(p[:468],axis=0),np.max(p[:468],axis=0)
        face = self.blob(frame, (low+high)/2, max(high-low)*1.04)
        eyes = [self.blob(frame,e[0],e[1]*1.8) for e in (left,right)]
        if face is None or any(x is None for x in eyes):
            return None,"Face near frame edge"
        prediction = self.pose([face])
        angles = np.array([prediction[self.pose.output(n)].item() for n in ('angle_y_fc','angle_p_fc','angle_r_fc')],dtype=np.float32)
        vec = self.gaze({'left_eye_image':eyes[0], 'right_eye_image':eyes[1],
                         'head_pose_angles':angles[None]})[self.gaze.output(0)].reshape(3)
        if not np.isfinite(vec).all() or np.linalg.norm(vec)<1e-5:
            return None,"Gaze unavailable"
        ax,ay = math.atan2(vec[0],abs(vec[2])),math.atan2(vec[1],np.hypot(vec[0],vec[2]))
        center = (left[0]+right[0])/2
        size = np.linalg.norm(left[0]-right[0])/w
        features = [ax,ay,*((left[2]+right[2])/2),*(left[2]-right[2]),
                    *np.radians(angles),center[0]/w,center[1]/h,math.log(max(size,.001))]
        quality = float(np.clip((min(left[1],right[1])-9)/25,.15,1)
                        *np.clip((aperture-.08)/.13,.25,1)
                        *np.clip(1-abs(angles[0])/100,.25,1))
        return (list(map(float,features)),quality),"Eyes visible"

    def close(self):
        self.face.close()
