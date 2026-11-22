"""Windows application and diagnostic entry points."""
import ctypes
import multiprocessing as mp
import os
from pathlib import Path
import sys
import traceback

ROOT=Path(__file__).resolve().parent
MODELS=ROOT/'models'
HOME_DIR=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'Csillagszemű Juhász'
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')


def verify():
    import cv2
    import tkinter
    from csillagszem.vision import Vision
    from csillagszem.cameras import enumerate_devices
    vis=Vision(MODELS)
    try:
        import numpy as np
        assert vis.read(np.zeros((480,640,3),np.uint8),1.)[0] is None
    finally:
        vis.close()
    win=tkinter.Tk()
    win.withdraw()
    win.update_idletasks()
    win.destroy()
    print('Vision models loaded, blank-frame inference and Windows UI initialization passed.')


def main():
    if '--verify' in sys.argv:
        verify()
        return
    from ctypes import wintypes as W
    from csillagszem import desktop
    desktop.aware()
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.restype=W.HANDLE
    mutex=kernel.CreateMutexW(None,False,'Local\\CsillagszemuJuhaszDesktop-v1')
    if ctypes.get_last_error()==183:
        ctypes.windll.user32.MessageBoxW(None,'Csillagszemű Juhász is already open.','Csillagszemű Juhász',64)
        return
    try:
        import tkinter as tk
        from csillagszem.app import App
        application=tk.Tk()
        App(application,MODELS,HOME_DIR)
        application.mainloop()
    finally:
        if mutex:
            kernel.CloseHandle(W.HANDLE(mutex))


if __name__=='__main__':
    mp.freeze_support()
    try:
        main()
    except Exception:
        if '--verify' in sys.argv:
            raise
        HOME_DIR.mkdir(parents=True,exist_ok=True)
        path=HOME_DIR/'startup-error.txt'
        path.write_text(traceback.format_exc(),'utf8')
        ctypes.windll.user32.MessageBoxW(None,'Csillagszemű Juhász could not start. Details are in '+str(path),'Csillagszemű Juhász',16)
        sys.exit(1)
