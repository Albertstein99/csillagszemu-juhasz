import json
import os
from pathlib import Path
import tempfile

VERSION = 1


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('w',encoding='utf8',dir=path.parent,delete=False) as stream:
        temp = Path(stream.name)
        try:
            json.dump(value,stream,allow_nan=False,separators=(',',':'))
            stream.flush()
            os.fsync(stream.fileno())
        except Exception:
            stream.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp,path)
    finally:
        temp.unlink(missing_ok=True)


def load_profile(path):
    if not path.exists():
        return {'version':VERSION,'banks':{},'labels':{},'disabled':[]}
    data = json.loads(path.read_text('utf8'))
    if data.get('version')!=VERSION or not isinstance(data.get('banks'),dict):
        raise ValueError('Unsupported or damaged profile')
    import numpy as np
    from .desktop import Screen
    from .model import FLOOR
    for banks in data['banks'].values():
        for b in banks:
            cols = b['columns']
            if (not cols or any(type(i) is not int or i<0 or i>=len(FLOOR) for i in cols)
                or np.shape(b['coef'])!=(len(cols)+4,2) or np.shape(b['mean'])!=(12,)
                or np.shape(b['scale'])!=(12,) or min(b['scale'])<=0
                or not all(np.isfinite(b[k]).all() for k in ('coef','mean','scale'))):
                raise ValueError('Damaged calibration coefficients')
            for item in b['screens']:
                s = Screen(**item)
                if s.w<2 or s.h<2 or not 0 < b['sigma'][s.id] < 1e7:
                    raise ValueError('Damaged display calibration')
    return data


def install_bank(banks, camera, bank):
    def ids(b):
        return {s['id'] for s in b['screens']}
    previous = banks.get(camera,[])
    banks[camera] = [b for b in previous if ids(b)!=ids(bank)] + [bank]
