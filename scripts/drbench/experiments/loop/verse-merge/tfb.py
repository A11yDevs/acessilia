import sys,re
from pathlib import Path
T,V,O,r=Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]),float(sys.argv[4])
O.mkdir(parents=True,exist_ok=True); n=0
nz=lambda s:len(re.sub(r"\W","",s))
for pv in sorted(V.glob("*.drbench.md")):
    v=pv.read_text(); pt=T/pv.name; t=pt.read_text() if pt.exists() else ""
    out=t
    if nz(t)<r*nz(v): out=v; n+=1
    (O/pv.name).write_text(out)
print("fallback",n)
