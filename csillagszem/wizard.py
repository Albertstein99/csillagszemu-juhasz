import time
import tkinter as tk
from collections import defaultdict
from copy import deepcopy
from tkinter import messagebox
import numpy as np

from .desktop import place
from .model import Smoother, fit, stable, track
from .session import Score, acceptable, target_list
from .storage import install_bank


class Wizard:
    def __init__(self,app,check_only):
        self.app = app
        self.check_only = check_only
        self.layout = list(app.displays.values())
        self.targets = target_list(self.layout,check_only)
        self.index = -1
        self.last_group = None
        self.train = defaultdict(list)
        self.candidates = {}
        self.score = Score()
        self.sources = set()
        self.pending = True
        self.waiting = False
        self.started = time.monotonic()
        self.samples = defaultdict(list)
        self.filters = defaultdict(Smoother)
        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes('-topmost',True)
        self.canvas = tk.Canvas(self.win,bg='#102323',highlightthickness=0,cursor='none')
        self.canvas.pack(fill='both',expand=True)
        self.win.bind('<Escape>',lambda _:self.cancel())
        self.win.bind('<space>',lambda _:self.resume())
        self.win.bind('<Button-1>',lambda _:self.resume())
        self.win.bind('<s>',lambda _:self.skip())
        self.next()

    def next(self):
        self.index += 1
        if self.index==len(self.targets):
            self.finish()
            return
        self.phase,self.screen,self.uv = self.targets[self.index]
        is_check = self.phase=='Accuracy check'
        if is_check and self.pending:
            self.pending = False
            if self.check_only:
                self.candidates = self.app.profile['banks']
            else:
                for cam,rows in self.train.items():
                    try:
                        self.candidates[cam]=[fit(rows,self.layout)]
                    except ValueError:
                        pass
            if not self.candidates:
                self.cancel("No camera collected enough distinct targets. Your saved profile was preserved.")
                return
            self.sources = set(self.candidates)
        group = (self.phase,self.screen.id)
        self.waiting = group != self.last_group
        self.last_group = group
        self.samples.clear()
        self.filters.clear()
        self.win.deiconify()
        s = self.screen
        place(self.win,s.x,s.y,s.w,s.h)
        self.win.focus_force()
        self.paint()
        self.win.update_idletasks()
        self.started = time.monotonic()

    def paint(self):
        c,s = self.canvas,self.screen
        c.delete('all')
        if self.waiting:
            c.create_text(s.w/2,s.h*.42,text=self.phase,fill='white',font=('Segoe UI',26,'bold'))
            hint = {'Natural seating position':'Sit comfortably and look at the center of each dot.',
                    'Change seating position slightly':'Lean a few centimeters to one side or change your viewing distance. Follow the dots from there.',
                    'Accuracy check':'Follow the new targets. Your gaze marker is hidden during measurement.'}[self.phase]
            c.create_text(s.w/2,s.h*.52,text=hint,fill='#c3dcda',width=s.w*.75,justify='center',font=('Segoe UI',15))
            c.create_text(s.w/2,s.h*.65,text='Space or click to begin    ·    Esc to cancel',fill='#7de0c8',font=('Segoe UI',13))
            return
        x,y = self.uv[0]*(s.w-1),self.uv[1]*(s.h-1)
        c.create_text(s.w/2,17,text=f'{self.phase}    {self.index+1} / {len(self.targets)}',fill='#a0b8b3',font=('Segoe UI',10))
        c.create_oval(x-17,y-17,x+17,y+17,outline='#79e4c7',width=2)
        c.create_oval(x-3,y-3,x+3,y+3,fill='white',outline='')
        self.message = c.create_text(s.w/2,s.h-22,text='',fill='#d6b97f',font=('Segoe UI',10))

    def resume(self):
        if self.waiting:
            self.waiting = False
            self.paint()
            self.win.update_idletasks()
            self.started = time.monotonic()

    def skip(self):
        if not self.waiting and self.phase!='Accuracy check':
            self.next()

    def cancel(self,message=None):
        self.win.destroy()
        self.app.wizard = None
        if message:
            self.app.notice.set(message)

    def tick(self, now):
        if self.waiting:
            return
        elapsed = now-self.started
        if elapsed < .72:
            return
        if self.phase=='Accuracy check':
            # Score wall-clock samples including intervals with no tracking. Each
            # camera and fusion see the same stream age and calibration geometry.
            live = self.app.cameras.frames
            for name in self.sources:
                f = {name:live[name]} if name in live else {}
                self.samples[name].append(self.filters[name].update(track(f,self.candidates,self.app.displays,now)))
            combined = track(live,self.candidates,self.app.displays,now)
            if combined and self.check_only and self.app.autodrift.get():
                s = self.app.displays[combined.screen]
                combined.xy = np.clip(combined.xy+self.app.drift.offsets.get(s.id,0),
                                      (s.x,s.y),(s.x+s.w-1,s.y+s.h-1))
            self.samples['Combined'].append(self.filters['Combined'].update(combined))
            if elapsed>=1.72:
                for source in (*self.sources,'Combined'):
                    self.score.add(self.screen,self.uv,source,self.samples[source])
                self.next()
            return
        if elapsed<1.50:
            return
        accepted = {}
        for cam,history in self.app.cameras.history.items():
            ff = [f for f in history if max(self.started+.70,now-.94)<=f.t<=now]
            if ff and now-ff[-1].t < .27:
                found = stable(ff)
                if found:
                    accepted[cam] = found
        eligible = len(self.app.cameras.workers)
        if accepted and (len(accepted)>=eligible or elapsed>=2.55):
            for cam,f in accepted.items():
                self.train[cam].append(dict(screen=self.screen.id,uv=self.uv,features=f.features))
            self.next()
        elif elapsed>2.5:
            self.canvas.itemconfigure(self.message,text='Waiting for steady, visible eyes. S skips this target. Esc cancels.')

    def finish(self):
        rows = self.score.summary()
        saved = []
        profile = deepcopy(self.app.profile)
        if not self.check_only:
            for cam,(bank,) in self.candidates.items():
                relevant = {s['id'] for s in bank['screens']}
                checked = [r for r in rows if r['source']==cam and r['screen'] in relevant]
                if len(checked)==len(relevant) and all(acceptable(r,self.app.displays[r['screen']]) for r in checked):
                    install_bank(profile['banks'],cam,bank)
                    saved.append(cam)
        report = dict(version=1,time=time.strftime('%Y-%m-%d %H:%M:%S'),kind='validation' if self.check_only else 'calibration',
                      saved=saved,screens=[s.record() for s in self.layout],summary=rows,targets=self.score.rows,
                      labels=self.app.profile.get('labels',{}))
        self.cancel()
        self.app.finish_session(profile,report)
