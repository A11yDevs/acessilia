import json,statistics as st
R=json.load(open("runs/loop/sel_rows.json"))
M=("text","reading_order","teds")
def score(rows,pick):
    out=[]
    for m in M:
        v=[(r["B"] if pick(r) else r["A"])[m] for r in rows]; v=[x for x in v if x is not None]
        out.append(st.mean(v))
    return st.mean(out),out
tune=[r for r in R if not r["hold"]]; hold=[r for r in R if r["hold"]]
base=lambda r:False
print("base",score(tune,base)[0],score(hold,base)[0])
orc=lambda r:(r["B"]["text"] or 0)>(r["A"]["text"] or 0)
print("oracle-text",score(tune,orc)[0],score(hold,orc)[0])
# winners profile
import collections
w=[r for r in R if (r["B"]["text"] or 0)-(r["A"]["text"] or 0)>10]
l=[r for r in R if (r["A"]["text"] or 0)-(r["B"]["text"] or 0)>10]
for name,g in (("Bbig",w),("Abig",l),("all",R)):
    print(name,len(g),{f:round(st.mean(r[f] for r in g),3) for f in ("ab","ad","am","bd","bm","dm")},
      "lb/la",round(st.median(r["lb"]/max(r["la"],1) for r in g),2), collections.Counter(r["fin"] for r in g))
best=[]
for f in ("ab","dm","ad","am"):
  for th in (0.3,0.4,0.5,0.6,0.7,0.8):
    for rat in (1.0,1.2,1.5,2.0):
      p=lambda r,f=f,th=th,rat=rat: r[f]<th and r["lb"]>rat*r["la"] and r["fin"]=="stop"
      best.append((score(tune,p)[0],score(hold,p)[0],f,th,rat,sum(map(p,R))))
best.sort(reverse=True)
for b in best[:10]: print([round(x,2) if isinstance(x,float) else x for x in b])
