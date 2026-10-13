import re,sys
from pathlib import Path
i,o=Path(sys.argv[1]),Path(sys.argv[2]); o.mkdir(parents=True,exist_ok=True)
for p in i.glob("*.drbench.md"):
    bs=[b for b in re.split(r"\n\s*\n",p.read_text()) if b.strip()]
    out=[]
    for b in bs:
        s=b.strip()
        if s.startswith("<table") or s.startswith("$$") or s.startswith("\\["): out.append(s); continue
        out.append(re.sub(r"[ \t]*\n[ \t]*"," ",s))
    (o/p.name).write_text("\n\n\n\n\n".join(out)+"\n")
