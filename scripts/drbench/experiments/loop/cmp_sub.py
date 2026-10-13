import json,statistics as st,os,sys,re
F="runs/dev-full/%s/reports/official_w1-md2md.json"
L=lambda r:{w["window"]:w for w in json.load(open(F%r))["windows"]}
A,B=L(sys.argv[1]),L(sys.argv[2])
done={f.split(".drbench")[0] for f in os.listdir(sys.argv[3]) if f.endswith(".drbench.md")}
def key(w): m=re.match(r"(.*)_page_(\d+)-",w); return f"{m[1]}_p{m[2]}"
ks=[k for k in A if key(k) in done]
print("windows",len(ks))
for m in ("text","reading_order","teds"):
    both=[(A[k][m],B[k][m]) for k in ks if A[k][m] is not None and B[k][m] is not None]
    na=sum(A[k][m] is not None for k in ks); nb=sum(B[k][m] is not None for k in ks)
    if both: print(f"{m:14s} nA={na} nB={nb} both={len(both)} A={st.mean(x for x,_ in both):.2f} B={st.mean(y for _,y in both):.2f} oracle={st.mean(max(x,y) for x,y in both):.2f} Bwins={sum(y>x for x,y in both)}")
