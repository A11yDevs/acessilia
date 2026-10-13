import json,re,os,sys,hashlib
sys.path.insert(0,"scripts")
from page_select import norm, read
from rapidfuzz import fuzz
from pathlib import Path
D="runs/dev-full/"
F=D+"%s/reports/official_w1-md2md.json"
L=lambda r:{w["window"]:w for w in json.load(open(F%r))["windows"]}
A,B=L("v25-sc"),L(sys.argv[1])
key=lambda w:(lambda m:f"{m[1]}_p{m[2]}")(re.match(r"(.*)_page_(\d+)-",w))
raw={f"{r['doc']}_p{r['page']}":r["finish"] for r in map(json.loads,open(D+"vlm-page/predictions-raw.jsonl"))}
rows=[]
for w in A:
    k=key(w); n=k+".drbench.md"
    t={s:norm(read(Path(D+s+"/predictions/"+n))) for s in ("v25-sc",sys.argv[1],"docling+rot","mineru-hyb+rot")}
    a,b,d,m=t["v25-sc"],t[sys.argv[1]],t["docling+rot"],t["mineru-hyb+rot"]
    r=lambda x,y:fuzz.ratio(x,y)/100 if x and y else 0.0
    rows.append(dict(w=w,hold=int(hashlib.md5(w.split("_page_")[0].encode()).hexdigest(),16)%3==0,
      ab=r(a,b),ad=r(a,d),am=r(a,m),bd=r(b,d),bm=r(b,m),dm=r(d,m),la=len(a),lb=len(b),ld=len(d),lm=len(m),
      fin=raw.get(k),A={x:A[w][x] for x in ("text","reading_order","teds")},B={x:B[w][x] for x in ("text","reading_order","teds")}))
json.dump(rows,open("runs/loop/sel_rows.json","w"))
print(len(rows))
