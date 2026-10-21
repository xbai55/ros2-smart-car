import sys
from pathlib import Path

if not getattr(sys,'frozen',False):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from insightrover_desktop.launcher import main

if __name__=='__main__':
    main()
