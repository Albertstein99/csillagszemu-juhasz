import json
import tempfile
import unittest
from pathlib import Path
import numpy as np
from csillagszem.desktop import Screen
from csillagszem.model import Estimate, Frame, Smoother, choose, fit, fuse, stable, track
from csillagszem.session import CHECK, SECOND, TRAIN, Drift, Score, acceptable
from csillagszem.storage import install_bank, load_profile, save_json
from csillagszem.vision import eye_geometry

A=Screen('a','Left',-1600,-140,1600,900)
B=Screen('b','Right',0,0,1920,1080)
LAYOUT={s.id:s for s in (A,B)}


def features(xy,posture=0):
    x,y=np.asarray(xy)/2000
    return np.array([x+.13*posture,y-.04*posture,x*.32+posture*.03,y*.37,
                     .005,-.003,posture*.44,posture*.25,.025,.48+posture*.1,.48,.05+posture*.02])


def make_bank():
    rows=[]
    for s in (A,B):
        for pos,targets in [(0,TRAIN),(.12,SECOND)]:
            for uv in targets:
                rows.append(dict(screen=s.id,uv=uv,features=features(s.point(uv),pos)))
    return fit(rows,[A,B])


def frame(cam,xy,t=20.,noise=0):
    x=features(xy,.04)
    x[:4]+=noise
    return Frame(cam,t,x.tolist(),.9)


class Tracking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank=make_bank()
        cls.banks={'front':[cls.bank],'side':[cls.bank]}

    def test_generalization_on_unseen_targets_and_new_posture(self):
        for s in (A,B):
            for uv in CHECK:
                xy=s.point(uv)
                p=track({'front':frame('front',xy)},self.banks,LAYOUT,20.05)
                self.assertEqual(p.screen,s.id)
                self.assertLess(np.linalg.norm(p.xy-xy),35)

    def test_reboot_reorder_camera_loss_and_resolution(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'profile.json'
            save_json(path,dict(version=1,banks=self.banks))
            saved=load_profile(path)['banks']
            active={'a':Screen('a','New primary',0,0,1280,720)}
            original=A.point((.31,.72))
            p=track({'side':frame('side',original)},saved,active,20.03)
            self.assertEqual(p.cameras,('side',))
            self.assertLess(np.linalg.norm(p.xy-active['a'].point((.31,.72))),30)
            self.assertIsNone(track({'side':frame('side',B.point((.5,.5)))},saved,active,20.03))

    def test_no_observation_or_stale_or_unknown_camera(self):
        for frames in ({},{'new':frame('new',(500,500))},{'front':frame('front',(500,500),17)}):
            self.assertIsNone(track(frames,self.banks,LAYOUT,20))

    def test_rotation_requires_new_calibration(self):
        active={'b':Screen('b','Portrait',0,0,1080,1920)}
        self.assertIsNone(track({'front':frame('front',(600,500))},self.banks,active,20))

    def test_fusion_reduces_independent_noise_and_handles_time_skew(self):
        rng=np.random.default_rng(25)
        target=np.array([700,360])
        errors=[]
        for i in range(150):
            points=[Estimate('b',target+rng.normal(0,12,2),20,(k,),10) for k in ['left','right']]
            p=fuse(points,LAYOUT)
            if p is not None:
                errors.append([np.linalg.norm(points[0].xy-target),np.linalg.norm(p.xy-target)])
        self.assertGreaterEqual(len(errors),145)
        a,b=np.mean(errors,axis=0)
        self.assertLess(b,.85*a)
        points[0].t=9.7
        self.assertEqual(fuse(points,LAYOUT).cameras,('right',))

    def test_disagreement_is_unavailable(self):
        a=Estimate('a',np.array([-700,100]),35,('a',),2)
        b=Estimate('b',np.array([700,100]),35,('b',),2)
        self.assertIsNone(fuse([a,b],LAYOUT))
        b.error=120
        self.assertEqual(fuse([a,b],LAYOUT).screen,'a')

    def test_insufficient_data_cannot_replace_good_bank(self):
        with self.assertRaises(ValueError):
            fit([],list(LAYOUT.values()))
        banks={'front':[self.bank]}
        variant={**self.bank,'screens':[B.record()]}
        install_bank(banks,'front',variant)
        self.assertIs(choose(banks['front'],LAYOUT),self.bank)
        self.assertIs(choose(banks['front'],{'b'}),variant)

    def test_filter_clears_after_loss(self):
        s=Smoother()
        s.update(Estimate('b',np.array([400,300]),20,('a',),1))
        self.assertIsNone(s.update(None))
        p=Estimate('b',np.array([800,300]),20,('a',),2)
        self.assertIs(s.update(p),p)

    def test_fixation_gate(self):
        good=[frame('front',(600,500),t/12) for t in range(9)]
        self.assertIsNotNone(stable(good))
        self.assertIsNone(stable(good[:3]))
        for i,f in enumerate(good):
            f.features[0]=i*.15
        self.assertIsNone(stable(good))

    def test_report_includes_dropouts_and_wrong_monitor(self):
        score=Score()
        p=Estimate('a',np.array([-250,350]),20,('a',),2)
        score.add(B,(.5,.5),'Combined',[None,None,p,p])
        score.add(B,(.25,.2),'Combined',[None,None])
        row=score.summary()[0]
        self.assertAlmostEqual(row['coverage'],1/3)
        self.assertEqual(row['screen_hit'],0)
        self.assertEqual(row['scored'],1)
        self.assertGreater(row['p50_px'],1000)
        self.assertFalse(acceptable(row,B))

    def test_cross_monitor_filter_never_interpolates_across_gap(self):
        flt=Smoother()
        a=Estimate('a',np.array([-600,800]),30,('one',),1.)
        b=Estimate('b',np.array([10,50]),30,('two',),1.03)
        flt.update(a)
        np.testing.assert_equal(flt.update(b).xy,b.xy)

    def test_session_offsets_require_consistent_distributed_clicks(self):
        d=Drift()
        for i in range(8):
            t=i*2+3
            xy=np.array(B.point((.18+.3*(i%3),.2+.3*(i%2))))
            for j in range(7):
                d.observe(Estimate('b',xy-np.array([20,10]),25,('cam',),t-.35+j*.045))
            d.anchor(t,xy,B)
            if i<6:
                self.assertFalse(d.offsets)
        self.assertEqual(d.updates,1)
        self.assertGreater(d.offsets['b'][0],0)
        self.assertLess(d.offsets['b'][0],20)
        self.assertFalse(Drift().offsets)

    def test_iris_geometry_invariant_under_roll_translation_scale(self):
        pts=np.array([[0,0],[20,0],[11,2],[10,-3],[10,4]],float)
        a=eye_geometry(pts,(0,1),2,(3,4))
        rot=np.array([[.8,-.6],[.6,.8]])
        b=eye_geometry(pts@rot.T*2+25,(0,1),2,(3,4))
        np.testing.assert_allclose(a[2],b[2],atol=1e-12)
        self.assertAlmostEqual(a[3],b[3])
