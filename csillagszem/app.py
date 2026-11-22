import hashlib
import json
import math
import os
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
import numpy as np

from . import desktop
from .cameras import Cameras
from .model import Smoother, track
from .session import Drift
from .storage import load_profile, save_json
from .wizard import Wizard


class App:
    def __init__(self,root,models,home):
        self.root,self.home = root,Path(home)
        self.home.mkdir(parents=True,exist_ok=True)
        self.cameras = Cameras(models)
        self.displays = {}
        self.smoother,self.drift = Smoother(),Drift()
        self.wizard,self.dot = None,None
        self.last_display,self.last_paint = -100.,-100.
        self.down = False
        self.report = None
        self.marker = tk.BooleanVar(value=False)
        self.preview = tk.BooleanVar(value=False)
        self.resolution = tk.StringVar(value='1080p')
        self.last_thumb = None
        self.autodrift = tk.BooleanVar(value=False)
        self.notice = tk.StringVar(value='Start the cameras, then calibrate once for each person and setup.')
        self.readout = tk.StringVar(value='Cameras stopped')
        self.person = tk.StringVar()
        self.summary = tk.StringVar(value='')
        self.profile = {}
        self.profile_path = None
        root.title('Csillagszemű Juhász  ·  Desktop eye tracker')
        root.geometry('880x670')
        root.minsize(720,590)
        self.build()
        settings = self.home/'settings.json'
        try:
            self.names = json.loads(settings.read_text('utf8'))
            if not isinstance(self.names,dict) or self.names.get('active') not in self.names['people']:
                raise ValueError
        except (OSError,ValueError,KeyError,TypeError):
            self.names = {'active':'Default','people':['Default']}
        self.use_profile(self.names['active'])
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.after(0,self.tick)

    def build(self):
        base = ttk.Frame(self.root,padding=(22,16))
        base.pack(fill='both',expand=True)
        title = ttk.Frame(base)
        title.pack(fill='x')
        ttk.Label(title,text='Csillagszemű Juhász',font=('Segoe UI',24,'bold')).pack(side='left')
        ttk.Label(title,text='Person').pack(side='right',padx=(6,4))
        self.people = ttk.Combobox(title,textvariable=self.person,state='readonly',width=15)
        self.people.pack(side='right',padx=4)
        self.people.bind('<<ComboboxSelected>>',lambda _:self.use_profile(self.person.get()))
        ttk.Button(title,text='New profile',command=self.new_profile).pack(side='right')
        row = ttk.Frame(base)
        row.pack(fill='x',pady=(12,8))
        self.start = ttk.Button(row,text='Start cameras',command=self.toggle)
        self.start.pack(side='left')
        ttk.Button(row,text='Calibrate',command=lambda:self.begin(False)).pack(side='left',padx=6)
        ttk.Button(row,text='Check accuracy',command=lambda:self.begin(True)).pack(side='left')
        ttk.Checkbutton(row,text='Desktop gaze dot',variable=self.marker).pack(side='left',padx=(14,0))
        ttk.Checkbutton(row,text='Learn from clicks',variable=self.autodrift,command=self.reset_drift).pack(side='left',padx=6)
        ttk.Label(base,textvariable=self.readout,font=('Segoe UI',12,'bold')).pack(anchor='w',pady=(5,7))
        self.tabs = ttk.Notebook(base)
        self.tabs.pack(fill='both',expand=True)
        live = ttk.Frame(self.tabs,padding=10)
        quality = ttk.Frame(self.tabs,padding=10)
        self.tabs.add(live,text='Live tracking')
        self.tabs.add(quality,text='Accuracy report')
        self.quality = quality
        strip=ttk.Frame(live)
        strip.pack(fill='x',pady=(0,5))
        ttk.Checkbutton(strip,text='Show selected camera',variable=self.preview).pack(side='left')
        ttk.Label(strip,text='Requested capture size').pack(side='left',padx=(18,6))
        size=ttk.Combobox(strip,textvariable=self.resolution,values=('1080p','720p','480p'),state='readonly',width=7)
        size.pack(side='left')
        size.bind('<<ComboboxSelected>>',lambda _:self.set_size())
        panel=ttk.Frame(live)
        panel.pack(fill='both',expand=True)
        self.preview_panel=ttk.Label(panel,anchor='center')
        self.map = tk.Canvas(panel,bg='#142a2c',highlightthickness=0,height=165)
        self.map.pack(fill='both',expand=True)
        ttk.Label(live,text='Cameras · double-click or press Space on a row to enable or disable it').pack(anchor='w',pady=(9,4))
        self.tree = ttk.Treeview(live,columns=('name','on','signal'),show='headings',height=4)
        for col,label,width in [('name','Device',220),('on','Enabled',64),('signal','Signal',370)]:
            self.tree.heading(col,text=label)
            self.tree.column(col,width=width,stretch=col!='on')
        self.tree.pack(fill='x')
        self.tree.bind('<Double-1>',lambda e:self.switch_camera(self.tree.identify_row(e.y)))
        self.tree.bind('<space>',lambda _:self.switch_camera(self.tree.focus()))
        ttk.Label(quality,textvariable=self.summary,wraplength=740).pack(anchor='w',pady=5)
        self.table = ttk.Treeview(quality,columns=('screen','source','px','tail','coverage','route','jitter'),show='headings')
        for key,label,width in zip(self.table['columns'],('Display','Source','Median px','P90 px','Coverage','Screen hit','Jitter px'),(125,145,75,75,85,85,75)):
            self.table.heading(key,text=label)
            self.table.column(key,width=width,anchor='w')
        self.table.pack(fill='both',expand=True,pady=6)
        ttk.Button(quality,text='Export report…',command=self.export).pack(anchor='w')
        ttk.Label(base,textvariable=self.notice,wraplength=780).pack(fill='x',pady=(10,0))

    def use_profile(self,name):
        path = self.home/'profiles'/(hashlib.sha256(name.encode()).hexdigest()[:20]+'.json')
        try:
            profile = load_profile(path)
        except (OSError,ValueError,TypeError,KeyError) as e:
            messagebox.showerror('Profile could not be opened',str(e)+'\nChoose or create another profile.')
            self.person.set(self.names.get('active','Default'))
            return
        self.profile_path,self.profile = path,profile
        self.person.set(name)
        self.names['active']=name
        self.people['values']=self.names['people']
        save_json(self.home/'settings.json',self.names)
        self.cameras.disabled=set(profile.get('disabled',[]))
        self.resolution.set(profile.get('resolution','1080p'))
        self.set_size(False)
        self.smoother = Smoother()
        self.reset_drift()
        self.report = profile.get('report')
        self.show_report()
        self.notice.set(f'{name} · {len(profile["banks"])} calibrated camera modes. Start cameras to track.' if not self.cameras.running else f'Using profile {name}.')

    def new_profile(self):
        name = simpledialog.askstring('New person','Profile name',parent=self.root)
        if name and name.strip():
            name = name.strip()[:60]
            if name not in self.names['people']:
                self.names['people'].append(name)
            self.use_profile(name)

    def reset_drift(self):
        self.drift=Drift()
        self.down=desktop.mouse()[0]
        if self.autodrift.get():
            self.notice.set('Learning small session-only offsets from consistent clicks. Untick to reset.')

    def set_size(self,persist=True):
        size={'1080p':(1920,1080),'720p':(1280,720),'480p':(640,480)}.get(self.resolution.get(),(1920,1080))
        if size!=self.cameras.size:
            for key in list(self.cameras.workers):
                self.cameras.detach(key)
            self.cameras.size=size
        if persist and self.profile_path:
            self.profile['resolution']=self.resolution.get()
            save_json(self.profile_path,self.profile)

    def toggle(self):
        self.cameras.running=not self.cameras.running
        self.start.configure(text='Stop cameras' if self.cameras.running else 'Start cameras')
        if not self.cameras.running:
            for key in list(self.cameras.workers):
                self.cameras.detach(key)
            self.smoother=Smoother()

    def switch_camera(self,key):
        if not key or not self.profile_path:
            return
        disabled=self.cameras.disabled
        if key in disabled:
            disabled.remove(key)
        else:
            disabled.add(key)
            self.cameras.detach(key)
        self.profile['disabled']=sorted(disabled)
        save_json(self.profile_path,self.profile)

    def begin(self,check):
        if self.wizard or not self.profile_path:
            return
        if not self.cameras.running:
            self.toggle()
        if not self.cameras.frames:
            self.notice.set('Waiting for visible eyes. When a camera reports Eyes visible, press the button again.')
            return
        if check and not self.profile['banks']:
            self.notice.set('Calibrate this person before checking accuracy.')
            return
        if self.displays:
            self.hide_dot()
            self.smoother=Smoother()
            self.wizard=Wizard(self,check)

    def finish_session(self,profile,report):
        profile['report']=report
        save_json(self.profile_path,profile)
        self.profile,self.report=profile,report
        self.show_report()
        self.tabs.select(self.quality)
        if report['kind']=='calibration':
            self.drift=Drift()
        self.smoother=Smoother()
        n=len(report['saved'])
        self.notice.set('Accuracy check complete.' if report['kind']=='validation' else
                        f'{n} camera mode(s) passed and were saved. Older calibrations are retained for other device combinations.')

    def show_report(self):
        self.table.delete(*self.table.get_children())
        if not self.report:
            self.summary.set('Run Check accuracy to measure gaze error on separate targets.')
            return
        self.summary.set(self.report['time']+' · Median and P90 use target-level errors. Coverage counts available samples. Screen hit counts correctly routed samples among those returned.')
        for r in sorted(self.report['summary'],key=lambda r:(r['screen'],r['source']!='Combined',r['source'])):
            def px(n):
                return '—' if r[n] is None else str(round(r[n]))
            src=self.report.get('labels',{}).get(r['source'],r['source'][:12])
            self.table.insert('', 'end',values=(r['name']+' '+r['screen'][-4:],src,px('p50_px'),px('p90_px'),
                f"{r['coverage']:.0%}",f"{r['screen_hit']:.0%}",px('jitter_px')))

    def export(self):
        if self.report:
            name=filedialog.asksaveasfilename(defaultextension='.json',initialfile='csillagszem-accuracy.json',
                                              filetypes=[('JSON report','*.json')])
            if name:
                save_json(Path(name),self.report)

    def hide_dot(self):
        if self.dot is not None:
            self.dot.withdraw()

    def show_dot(self,p):
        if self.dot is None:
            self.dot=tk.Toplevel(self.root)
            self.dot.withdraw()
            self.dot.overrideredirect(True)
            self.dot.attributes('-transparentcolor','#010203')
            self.dot.configure(bg='#010203')
            canvas=tk.Canvas(self.dot,bg='#010203',highlightthickness=0)
            canvas.pack(fill='both',expand=True)
            canvas.create_oval(2,2,21,21,outline='#0c2120',width=4)
            canvas.create_oval(2,2,21,21,outline='#70ffd4',width=2)
        if self.dot.state()=='withdrawn':
            self.dot.deiconify()
        desktop.place(self.dot,p.xy[0]-12,p.xy[1]-12,24,24,True)

    def draw(self,p):
        c=self.map
        selected=self.tree.focus() or next(iter(self.cameras.devices),None)
        self.cameras.preview_key=selected if self.preview.get() else None
        thumb=self.cameras.thumbnail
        if self.preview.get() and thumb and thumb[0]==selected and time.monotonic()-thumb[1]<1.1:
            if thumb[1]!=self.last_thumb:
                self.thumb_image=tk.PhotoImage(data=thumb[2])
                self.preview_panel.configure(image=self.thumb_image)
                self.last_thumb=thumb[1]
            if not self.preview_panel.winfo_manager():
                self.preview_panel.pack(side='right',before=self.map)
        else:
            self.preview_panel.pack_forget()
        c.delete('all')
        screens=list(self.displays.values())
        if not screens:
            return
        x=min(s.x for s in screens)
        y=min(s.y for s in screens)
        w=max(s.x+s.w for s in screens)-x
        h=max(s.y+s.h for s in screens)-y
        cw,ch=c.winfo_width(),c.winfo_height()
        k=max(.001,min((cw-36)/w,(ch-30)/h))
        ox,oy=(cw-k*w)/2-x*k,(ch-k*h)/2-y*k
        for i,s in enumerate(screens,1):
            ax,ay=ox+s.x*k,oy+s.y*k
            c.create_rectangle(ax,ay,ax+s.w*k,ay+s.h*k,outline='#85b4ae',fill='#254548',width=2)
            c.create_text(ax+8,ay+8,text=f'{i} · {s.w} × {s.h}',anchor='nw',fill='#d4e8e4',font=('Segoe UI',9))
        if p:
            a,b=ox+p.xy[0]*k,oy+p.xy[1]*k
            c.create_oval(a-6,b-6,a+6,b+6,fill='#7bf0cb',outline='#edfdfa')
        for key in self.tree.get_children():
            if key not in self.cameras.devices:
                self.tree.delete(key)
        for key,d in self.cameras.devices.items():
            enabled=key not in self.cameras.disabled
            status=self.cameras.status.get(key,'Ready') if self.cameras.running and enabled else 'Idle'
            values=(d.name,'Yes' if enabled else 'No',status)
            if self.tree.exists(key):
                self.tree.item(key,values=values)
            else:
                self.tree.insert('','end',iid=key,values=values)
        if self.cameras.discovery_error:
            self.notice.set('Camera discovery: '+self.cameras.discovery_error)

    def tick(self):
        now=time.monotonic()
        self.cameras.maintenance(now)
        if now-self.last_display>1:
            self.last_display=now
            try:
                display={s.id:s for s in desktop.screens()}
            except OSError:
                display=self.displays
            if self.wizard and display!=self.displays:
                self.wizard.cancel('Display layout changed. Restart calibration when the layout is stable.')
            self.displays=display
        for mode in self.cameras.frames:
            key=mode.split('/')[0]
            if key in self.cameras.devices and self.profile_path:
                self.profile.setdefault('labels',{})[mode]=self.cameras.devices[key].name+' '+key[-4:]
        if self.wizard:
            self.wizard.tick(now)
            self.root.after(28,self.tick)
            return
        p=track(self.cameras.frames,self.profile.get('banks',{}),self.displays,now)
        if self.autodrift.get():
            self.drift.observe(p)
            down,xy=desktop.mouse()
            if down and not self.down:
                s=next((s for s in self.displays.values() if s.contains(xy)),None)
                if s:
                    self.drift.anchor(now,xy,s)
            self.down=down
            if p:
                s=self.displays[p.screen]
                p.xy=np.clip(p.xy+self.drift.offsets.get(p.screen,0),(s.x,s.y),(s.x+s.w-1,s.y+s.h-1))
        p=self.smoother.update(p)
        if now-self.last_paint>.075:
            self.last_paint=now
            self.draw(p)
            if p:
                self.readout.set(f'{self.displays[p.screen].name}   ·   x {p.xy[0]:.0f}   y {p.xy[1]:.0f} px   ·   {len(p.cameras)} camera(s)')
            else:
                self.readout.set('Cameras stopped' if not self.cameras.running else
                                 'No cameras detected' if not self.cameras.devices else
                                 'Awaiting calibration' if not self.profile.get('banks') else 'Gaze unavailable')
        if p and self.marker.get():
            self.show_dot(p)
        else:
            self.hide_dot()
        self.root.after(28,self.tick)

    def close(self):
        self.cameras.close()
        self.root.destroy()
