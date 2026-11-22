"""Build the small Windows installer and a repository-ready source distribution."""
import argparse
from io import BytesIO
import os
from pathlib import Path
import subprocess
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo

ROOT=Path(__file__).resolve().parents[1]


def archive(names):
    buffer=BytesIO()
    with ZipFile(buffer,'w',compression=ZIP_DEFLATED,compresslevel=9) as z:
        for name in sorted(names):
            info=ZipInfo(name,(2026,1,1,0,0,0))
            info.compress_type=ZIP_DEFLATED
            z.writestr(info,(ROOT/name).read_bytes())
    return buffer.getvalue()


def build(out):
    out.mkdir(parents=True,exist_ok=True)
    code=[p.relative_to(ROOT).as_posix() for p in (ROOT/'csillagszem').glob('*.py')]
    payload=['run.py','requirements.txt','setup/assets.py','README.md','LICENSE','THIRD-PARTY.md',*code]
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    with tempfile.TemporaryDirectory() as temp:
        package=Path(temp)/'app.zip'
        package.write_bytes(archive(payload))
        exe=out/'Csillagszemu-Juhasz-Setup.exe'
        subprocess.run([str(compiler),'/nologo','/codepage:65001','/target:winexe','/platform:x64','/optimize+',
                        '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',
                        '/reference:System.IO.Compression.dll','/reference:System.IO.Compression.FileSystem.dll',
                        '/reference:Microsoft.CSharp.dll',f'/resource:{package},csillagszem.zip',
                        f'/out:{exe}',str(ROOT/'setup/Setup.cs')],check=True)
    source=payload+['setup/Setup.cs','setup/build.py','.gitignore','.github/workflows/windows.yml']
    source += [p.relative_to(ROOT).as_posix() for p in (ROOT/'tests').glob('*.py')]
    (out/'Csillagszemu-Juhasz-source.zip').write_bytes(archive(source))
    with ZipFile(out/'Csillagszemu-Juhasz-Windows.zip','w',compression=ZIP_DEFLATED) as bundle:
        bundle.write(exe,exe.name)
        bundle.write(ROOT/'README.md','README.md')
        bundle.write(out/'Csillagszemu-Juhasz-source.zip','Csillagszemu-Juhasz-source.zip')
    return exe


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--out',type=Path,default=ROOT/'dist')
    print(build(p.parse_args().out.resolve()))
