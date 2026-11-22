"""Personal calibration, multi-camera fusion, and scoring. All model inputs are fixation-level."""
from dataclasses import dataclass
import math
import numpy as np

from .desktop import Screen

# gaze angles, binocular iris offset, eye asymmetry, head angles, eye midpoint, log scale
FLOOR = np.array([.035,.035,.025,.018,.025,.018,.07,.07,.07,.035,.035,.065])
FAMILIES = ((0,1,6,7,9,10,11), (2,3,6,7,8,9,10,11), tuple(range(12)))


@dataclass
class Frame:
    camera: str
    t: float
    features: list
    quality: float


@dataclass
class Estimate:
    screen: str
    xy: np.ndarray
    error: float
    cameras: tuple
    t: float


def design(x, columns):
    selected = x[:, columns]
    # Weak quadratic terms let personal calibration fit curvature near screen edges.
    a, b = selected[:, 0], selected[:, 1]
    return np.column_stack((np.ones(len(x)), selected, .24*a*b, .17*a*a, .17*b*b))


def solve(x, y, columns, alpha):
    mean = np.median(x, axis=0)
    scale = np.maximum(np.std(x, axis=0), FLOOR)
    a = design(np.clip((x-mean)/scale, -6, 6), columns)
    penalty = np.eye(a.shape[1]) * alpha
    penalty[0,0] = 1e-8
    w = np.ones(len(x))
    for _ in range(3):
        b = np.linalg.solve(a.T @ (w[:,None]*a) + penalty, a.T @ (w[:,None]*y))
        residual = np.linalg.norm(a @ b-y, axis=1)
        w = np.minimum(1., max(10., 1.8*np.median(residual))/np.maximum(1., residual))
    return mean, scale, b


def fit(records, layout):
    """Cross-validation groups repeated target positions to prevent fixation leakage."""
    covered = []
    for s in layout:
        uv = [r['uv'] for r in records if r['screen'] == s.id]
        quadrants = {(u>.5,v>.5) for u,v in uv}
        if len(uv) >= 13 and len(set(map(tuple, uv))) >= 9 and len(quadrants) == 4:
            covered.append(s)
    by_id = {s.id:s for s in covered}
    rows = [r for r in records if r['screen'] in by_id]
    if not rows:
        raise ValueError("More valid targets across the screen are needed")
    x = np.array([r['features'] for r in rows], dtype=float)
    y = np.array([by_id[r['screen']].point(r['uv']) for r in rows])
    groups = sorted({(r['screen'], *r['uv']) for r in rows})
    fold_of = {group:i % 5 for i,group in enumerate(groups)}
    folds = np.array([fold_of[(r['screen'], *r['uv'])] for r in rows])
    best = None
    for family in FAMILIES:
        for alpha in (.12, 1., 4.):
            errors = np.empty(len(rows))
            for k in range(5):
                test = folds == k
                m, sd, b = solve(x[~test], y[~test], family, alpha)
                pred = design(np.clip((x[test]-m)/sd,-6,6), family) @ b
                errors[test] = np.linalg.norm(pred-y[test], axis=1)
            objective = np.median(errors) + .4*np.percentile(errors,85)
            if best is None or objective < best[0]:
                best = objective, family, alpha, errors.copy()
    _, family, alpha, errors = best
    m, sd, b = solve(x, y, family, alpha)
    return dict(mean=m.tolist(), scale=sd.tolist(), coef=b.tolist(), columns=list(family),
                screens=[s.record() for s in covered],
                sigma={s.id:max(12.,float(np.median(errors[[r['screen']==s.id for r in rows]])))
                       for s in covered})


def choose(banks, active):
    active = set(active)
    compatible = []
    for i,bank in enumerate(banks):
        ids = {s['id'] for s in bank['screens']}
        if ids & active:
            compatible.append((len(ids & active), -(len(ids-active)), i, bank))
    return max(compatible, key=lambda item:item[:3])[-1] if compatible else None


def project(frame, bank, current):
    if bank is None or frame.quality < .12:
        return None
    z = (np.asarray(frame.features)-bank['mean'])/np.asarray(bank['scale'])
    if not np.all(np.isfinite(z)) or max(abs(z[i]) for i in bank['columns']) > 7:
        return None
    raw = (design(np.clip(z[None,:],-6,6), bank['columns']) @ bank['coef'])[0]
    # Route in the saved geometry first. Changing the Windows primary display shifts
    # all current origins and must not change which physical screen is predicted.
    saved = [Screen(**d) for d in bank['screens']]
    screen = next((s for s in saved if s.contains(raw)), None)
    if screen is None:
        # Small edge overshoot is common. Never jump across a large desktop gap.
        def distance(s):
            return math.hypot(max(s.x-raw[0],0,raw[0]-(s.x+s.w-1)),
                              max(s.y-raw[1],0,raw[1]-(s.y+s.h-1)))
        screen = min(saved, key=distance)
        if distance(screen) > .025*math.hypot(screen.w,screen.h):
            return None
    now = current.get(screen.id)
    if now is None or abs(math.log((now.w/now.h)/(screen.w/screen.h))) > .12:
        return None
    uv = np.clip(screen.uv(raw), 0, 1)
    scale = math.hypot(now.w,now.h)/math.hypot(screen.w,screen.h)
    sigma = bank['sigma'][screen.id] * scale / max(.22,frame.quality)**.5
    return Estimate(screen.id, np.array(now.point(uv)), sigma, (frame.camera,), frame.t)


def fuse(estimates, current):
    if not estimates:
        return None
    newest = max(p.t for p in estimates)
    candidates = [p for p in estimates if newest-p.t <= .09]
    if len(candidates)==1:
        return candidates[0]
    # Select the largest precision-weighted neighbourhood of mutually plausible observations.
    def agrees(a,b):
        s = current[a.screen]
        gate = min(.15*math.hypot(s.w,s.h), max(42.,2.5*math.hypot(a.error,b.error)))
        return a.screen==b.screen and np.linalg.norm(a.xy-b.xy) <= gate
    pools = [[b for b in candidates if agrees(a,b)] for a in candidates]
    weight = lambda p: 1 / max(12.,p.error)**2
    pool = max(pools, key=lambda ps:sum(map(weight,ps)))
    rivals = [p for p in candidates if all(p is not b for b in pool)]
    if rivals and sum(map(weight,rivals)) > .7*sum(map(weight,pool)):
        return None  # two comparably reliable views disagree
    weights = np.array([weight(p) for p in pool])
    points = np.array([p.xy for p in pool])
    xy = np.average(points,axis=0,weights=weights)
    spread = np.average(np.sum((points-xy)**2,axis=1),weights=weights)
    error = math.sqrt(1/weights.sum()+spread)
    return Estimate(pool[0].screen, xy, error, tuple(p.cameras[0] for p in pool), newest)


def track(frames, banks, current, now):
    estimates = []
    for cam, f in frames.items():
        if 0 <= now-f.t <= .32:
            p = project(f, choose(banks.get(cam,[]), current), current)
            if p is not None:
                estimates.append(p)
    return fuse(estimates,current)


class Smoother:
    def __init__(self):
        self.last = None

    def update(self, p):
        old = self.last
        if p is None:
            self.last = None
            return None
        if old and p.screen == old.screen and 0 <= p.t-old.t < .20:
            dt = p.t-old.t
            distance = np.linalg.norm(p.xy-old.xy)
            tau = .064 if distance < max(16.,old.error*.7) else .012
            xy = old.xy + (1-math.exp(-dt/tau))*(p.xy-old.xy)
            p = Estimate(p.screen,xy,p.error,p.cameras,p.t)
        self.last = p
        return p


def stable(frames):
    """Aggregate distinct captured frames of one camera in a settled target window."""
    if len(frames) < 5 or frames[-1].t-frames[0].t < .30:
        return None
    x = np.asarray([f.features for f in frames])
    med = np.median(x,axis=0)
    jitter = np.median(np.abs(x-med),axis=0)
    if max(jitter[:2]) > .075 or max(jitter[2:4]) > .036 or max(jitter[6:8]) > .055:
        return None
    return Frame(frames[-1].camera, frames[-1].t, med.tolist(),
                 float(np.median([f.quality for f in frames])))
