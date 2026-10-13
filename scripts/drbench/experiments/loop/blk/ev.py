"""Dev eval of LOOP #53: on judged block-divergent pages take Tele (tj3) when pB > th, else keep hyb-judge2 tj3.
usage: ev.py SCRATCH"""
import json, re, hashlib, sys
S = sys.argv[1]
H, T = json.load(open(f"{S}/tj3_hdr.json")), json.load(open(f"{S}/tj3_teleocr-vm-fb.json"))
J = {p: {x["key"]: x["pB"] for x in map(json.loads, open(f"runs/loop/blk/dev-{p}.jsonl"))} for p in ("base", "para")}
J["mean"] = {k: (J["base"][k] + J["para"].get(k, J["base"][k])) / 2 for k in J["base"]}
k2 = lambda k: re.sub(r"_page_(\d+)-\d+\.jpg$", r"_p\1", k)
hold = lambda k: int(hashlib.md5(k.split("_page_")[0].encode()).hexdigest(), 16) % 3 == 0
def sc(ch):
    o = []
    for f in (lambda k: True, lambda k: not hold(k), hold):
        P = [ch(k) for k in H if f(k)]
        m = lambda q: (lambda v: sum(v) / len(v))([p[q] for p in P if p.get(q) is not None])
        o.append((m("text") + m("reading_order")) / 2)
    return "all %.2f tune %.2f hold %.2f" % tuple(o)
print("base", sc(lambda k: H[k]))
for p in J:
    for th in (0.5, 0.7, 0.8, 0.9):
        n = sum(v > th for v in J[p].values())
        print(p, th, sc(lambda k: T[k] if J[p].get(k2(k), 0) > th and k in T else H[k]), "n", n)
