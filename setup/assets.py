"""Install versioned, digest-checked models from their publishers."""
from hashlib import new
from pathlib import Path
import os
import sys
import tempfile
import time
from urllib.request import urlopen

BASE='https://storage.openvinotoolkit.org/repositories/open_model_zoo/2023.0/models_bin/1'
FACE='https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'
FILES=[('face_landmarker.task',FACE,'sha256','64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff')]
for model,xml,weights in [
    ('gaze-estimation-adas-0002','840d76c3bc0693f5d10966dfa7cac193519227bfe4762d12d124f24395e3490bf54ec409a09c1e4f962e53900d8b6a14',
     '6b54573b16ef8a3ca0acf53b26a35215eba250024677081b37fa531a79b69d2dceb4d25dfd863439383e002f2162c81f'),
    ('head-pose-estimation-adas-0001','b92f6721a43f87fc5b7edda1d062cd05c97452c8990aa9517da5c959d9cdf4a75a05d3897d6b2bf5bab3dc530ac57947',
     'ff57525f97d3d837baf03344802a195b504148f8fc818844c15a89a9f742e770d411113685ec3f648417299bf443dde2')]:
    for suffix,digest in [('xml',xml),('bin',weights)]:
        name=f'{model}.{suffix}'
        FILES.append((name,f'{BASE}/{model}/FP16/{name}','sha384',digest))


def install(directory):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    for name,url,algorithm,digest in FILES:
        target=directory/name
        if target.exists() and new(algorithm,target.read_bytes()).hexdigest()==digest:
            continue
        for attempt in range(3):
            pending=None
            try:
                h=new(algorithm)
                with urlopen(url,timeout=45) as src,tempfile.NamedTemporaryFile(dir=directory,delete=False) as dst:
                    pending=Path(dst.name)
                    while chunk:=src.read(256*1024):
                        dst.write(chunk)
                        h.update(chunk)
                if h.hexdigest()!=digest:
                    raise ValueError(f'Unexpected digest for {name}')
                os.replace(pending,target)
                print('Verified',name,flush=True)
                break
            except (OSError,ValueError):
                if attempt==2:
                    raise
                time.sleep(1+attempt)
            finally:
                if pending:
                    pending.unlink(missing_ok=True)

if __name__=='__main__':
    install(sys.argv[1] if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/'models')
