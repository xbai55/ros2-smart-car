"""Build the Windows application and installer without bundling project data."""
import argparse
import json
import subprocess
import sys
import runpy
from pathlib import Path


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--compiler',type=Path);parser.add_argument('--output-dir',type=Path);args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];out=(args.output_dir or root/'output/windows-app-20261021').resolve()
    out.mkdir(parents=True,exist_ok=True)
    version=runpy.run_path(str(root/'desktop/insightrover_desktop/__init__.py'))['VERSION']
    subprocess.run(['cmd','/c','npm','run','build'],cwd=root/'web-console',check=True)
    subprocess.run([sys.executable,str(root/'desktop/collect_notices.py')],check=True)
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed','--onedir',
             '--name','InsightRover','--icon',str(root/'desktop/assets/insightrover.ico'),
             '--distpath',str(out/'dist'),'--workpath',str(out/'build'),
             '--specpath',str(out),'--paths',str(root/'desktop'),'--paths',str(root/'backend'),
             '--add-data',str(root/'web-console/dist')+';web',
             '--add-data',str(root/'desktop/assets')+';desktop-assets',
             '--add-data',str(root/'scripts/switch_wifi_remote.py')+';vehicle',
             '--add-data',str(root/'desktop/insightrover_desktop/vehicle_start.sh')+';vehicle',
             '--collect-submodules','app','--collect-submodules','paramiko',
             '--hidden-import','uvicorn.logging','--hidden-import','uvicorn.loops.asyncio',
             '--hidden-import','uvicorn.protocols.http.h11_impl','--hidden-import','uvicorn.protocols.websockets.websockets_impl',
             '--hidden-import','uvicorn.lifespan.on','--hidden-import','websockets.legacy.client']
    for module in ['torch','tensorflow','pandas','numpy','scipy','matplotlib','PyQt5','PyQt6','PySide6','IPython','pytest','redis','minio']:
        command+=['--exclude-module',module]
    command+=[str(root/'desktop/desktop_entry.py')]
    with (out/'build.log').open('w',encoding='utf-8') as log:
        subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT,check=True)
    if args.compiler:
        subprocess.run([str(args.compiler),'/Q','/DAppVersion='+version,'/DBundleDir='+str(out/'dist/InsightRover'),
                        '/DOutputDir='+str(out/'installer'),str(root/'desktop/installer.iss')],check=True)
    print(json.dumps({'application':str(out/'dist/InsightRover/InsightRover.exe'),
                      'installer':str(out/f'installer/InsightRover-Setup-{version}-x64.exe')},ensure_ascii=False))


if __name__=='__main__':main()
