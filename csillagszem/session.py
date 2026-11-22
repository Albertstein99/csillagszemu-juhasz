"""Guided targets, blind validation metrics, and bounded session-only drift correction."""
from collections import defaultdict, deque
import math
import random
import numpy as np

TRAIN = [(u,v) for u in (.08,.5,.92) for v in (.09,.5,.91)] + [
    (.29,.3),(.71,.3),(.29,.7),(.71,.7)]
SECOND = [(u,v) for u in (.08,.5,.92) for v in (.09,.5,.91)]
CHECK = [(.18,.2),(.82,.18),(.2,.8),(.81,.78),(.45,.37),(.62,.61),(.35,.57),
         (.93,.43),(.07,.64)]


def target_list(layout, validate_only=False):
    phases = [('Accuracy check',CHECK)] if validate_only else [
        ('Natural seating position',TRAIN),('Change seating position slightly',SECOND),
        ('Accuracy check',CHECK)]
    result = []
    for phase, points in phases:
        for screen in layout:
            shuffled = points.copy()
            random.SystemRandom().shuffle(shuffled)
            for uv in shuffled:
                result.append((phase,screen,uv))
    return result


class Score:
    def __init__(self):
        self.rows = []

    def add(self, screen, uv, source, samples):
        expected = np.array(screen.point(uv))
        valid = [p for p in samples if p is not None]
        correct = [p for p in valid if p.screen==screen.id]
        error = [float(np.linalg.norm(p.xy-expected)) for p in valid]
        points = np.array([p.xy for p in correct])
        jitter = None
        if len(points)>=2:
            jitter = float(np.median(np.linalg.norm(points-np.median(points,axis=0),axis=1)))
        self.rows.append(dict(screen=screen.id,name=screen.name,uv=list(uv),source=source,
                              samples=len(samples),valid=len(valid),correct=len(correct),
                              median_px=float(np.median(error)) if error else None,jitter_px=jitter))

    def summary(self):
        groups = defaultdict(list)
        for row in self.rows:
            groups[row['screen'],row['source']].append(row)
        summary = []
        for (sid,source), rows in groups.items():
            count = sum(r['samples'] for r in rows)
            valid = sum(r['valid'] for r in rows)
            correct = sum(r['correct'] for r in rows)
            # A target gets an error score only if tracking returned a point at least
            # half the time. Both missing targets and sample coverage are reported.
            errors = [r['median_px'] for r in rows if r['valid']>=max(1,r['samples']*.5)]
            jitter = [r['jitter_px'] for r in rows if r['jitter_px'] is not None]
            summary.append(dict(screen=sid,name=rows[0]['name'],source=source,
                                targets=len(rows),scored=len(errors),coverage=valid/max(1,count),
                                screen_hit=correct/max(1,valid),p50_px=float(np.median(errors)) if errors else None,
                                p90_px=float(np.percentile(errors,90)) if errors else None,
                                jitter_px=float(np.median(jitter)) if jitter else None))
        return summary


def acceptable(row,screen):
    return (row['scored']>=6 and row['coverage']>=.6 and row['screen_hit']>=.80 and
            row['p50_px'] is not None and row['p50_px'] <= .15*math.hypot(screen.w,screen.h))


class Drift:
    """Opt-in click anchors. Discard all adjustments on restart or profile change."""
    def __init__(self):
        self.offsets = {}
        self.anchors = defaultdict(lambda:deque(maxlen=20))
        self.history = deque(maxlen=100)
        self.last_click = -100.
        self.updates = 0

    def observe(self, p):
        if p is None:
            self.history.clear()
        elif not self.history or self.history[-1].t != p.t:
            self.history.append(p)

    def anchor(self, t, xy, screen):
        if t-self.last_click < .8 or not screen.contains(xy):
            return
        self.last_click = t
        before = [p for p in self.history if .045 <= t-p.t <= .40]
        if len(before)<4 or before[-1].t-before[0].t < .14 or any(p.screen!=screen.id for p in before):
            return
        diag = math.hypot(screen.w,screen.h)
        points = np.array([p.xy for p in before])
        center = np.median(points,axis=0)
        if np.max(np.linalg.norm(points-center,axis=1)) > .023*diag:
            return
        residual = np.array(xy)-center
        if np.linalg.norm(residual)>.065*diag:
            return
        anchors = self.anchors[screen.id]
        anchors.append((t,screen.uv(xy),residual))
        fresh = [a for a in anchors if t-a[0]<240]
        if len(fresh)<7:
            return
        regions = {(int(u*3),int(v*3)) for _,(u,v),_ in fresh}
        if len(regions)<3:
            return
        values = np.array([a[2] for a in fresh])
        median = np.median(values,axis=0)
        if np.percentile(np.linalg.norm(values-median,axis=1),75)>.022*diag:
            return
        offset = self.offsets.get(screen.id,np.zeros(2))
        step = (median-offset)*.32
        offset = offset + step*min(1.,.009*diag/max(1.,np.linalg.norm(step)))
        self.offsets[screen.id] = offset*min(1.,.035*diag/max(1.,np.linalg.norm(offset)))
        self.updates += 1
        anchors.clear()
