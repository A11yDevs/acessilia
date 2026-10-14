import json,re,shutil,sys
from pathlib import Path
R=json.load(open("runs/loop/sel_rows.json")); f,th,rat,out=sys.argv[1],float(sys.argv[2]),float(sys.argv[3]),Path(sys.argv[4])
B=sys.argv[5] if len(sys.argv)>5 else "vf-order"
D="runs/dev-full/"
key=lambda w:(lambda m:f"{m[1]}_p{m[2]}")(re.match(r"(.*)_page_(\d+)-",w))
pick={key(r["w"]) for r in R if r[f]<th and r["lb"]>rat*r["la"] and r["fin"]=="stop"}
out.mkdir(parents=True,exist_ok=True)
for p in Path(D+"v25-sc/predictions").glob("*.drbench.md"):
    k=p.name.split(".drbench")[0]
    shutil.copy(Path(D+B+"/predictions")/p.name if k in pick else p, out/p.name)
print(len(pick))
