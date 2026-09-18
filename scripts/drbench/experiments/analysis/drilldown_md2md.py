#!/usr/bin/env python3
"""Drilldown dev-986 md2md: per-component distribution, worst pages, by subject/layout, oracle."""
import json, glob, os, statistics as st, re
from collections import defaultdict

ROOT = "/raid/user_marcospaulo/drdocbench"
RUNS = {r: json.load(open(f"{ROOT}/runs/dev-full/{r}/reports/official_w1-md2md.json"))["windows"]
        for r in ["v3a-clean", "differ-v2", "mineru", "docling"]}

def key(w):  # 'uuid_page_28-28.jpg' -> ('uuid', 28)
    m = re.match(r"(.+)_page_(\d+)-\d+\.jpg", w["window"]); return m.group(1), int(m.group(2))

# metadata: uuid -> subject; page json -> layout/special_issue
subj = {}
for p in glob.glob(f"{ROOT}/data/hf/dev/*/*"):
    subj[os.path.basename(p)] = os.path.basename(os.path.dirname(p))
meta = {}
def page_meta(uuid, page):
    k = (uuid, page)
    if k in meta: return meta[k]
    d = subj.get(uuid); m = {}
    if d:
        jp = f"{ROOT}/data/hf/dev/{d}/{uuid}/json/{uuid}_page_{page}.json"
        if os.path.exists(jp):
            try:
                j = json.load(open(jp))
                if isinstance(j, list): j = j[0]
                pa = j.get("page_info", {}).get("page_attribute") or {}
                dets = j.get("layout_dets") or []
                rot = sorted({d.get("attribute", {}).get("text_rotate") for d in dets if d.get("attribute", {}).get("text_rotate") not in (None, "normal")})
                m = {"layout": pa.get("layout"), "special_issue": pa.get("special_issue"),
                     "language": pa.get("language"), "rotate": rot or None,
                     "cats": dict(sorted(__import__('collections').Counter(d.get("category_type") for d in dets).items()))}
            except Exception: pass
    meta[k] = m; return m

def comp(ws, c):
    return [w[c] for w in ws if w.get(c) is not None]

def f(x):
    return "–" if x is None else f"{x:.1f}"

print("## 1. Distribuição por componente (dev-986 md2md, w1)")
print("| run | comp | n | mean | median | %<50 |\n|---|---|---|---|---|---|")
for r, ws in RUNS.items():
    for c in ["text", "reading_order", "teds", "overall_no_cdm"]:
        v = comp(ws, c)
        if v: print(f"| {r} | {c} | {len(v)} | {st.mean(v):.1f} | {st.median(v):.1f} | {100*sum(x<50 for x in v)/len(v):.0f}% |")

V = {key(w): w for w in RUNS["v3a-clean"]}
M = {key(w): w for w in RUNS["mineru"]}
D = {key(w): w for w in RUNS["docling"]}

print("\n## 2. Piores páginas v3a-clean")
for c in ["text", "reading_order"]:
    print(f"\n### {c} (bottom 20)\n| uuid | page | subject | layout | special | rotate | text | RO | mineru {c} | docling {c} | GT cats |\n|---|---|---|---|---|---|---|---|---|---|---|")
    rows = sorted([(w[c], k) for k, w in V.items() if w.get(c) is not None])[:20]
    for s, k in rows:
        w = V[k]; m = page_meta(*k)
        print(f"| {k[0][:8]} | {k[1]} | {subj.get(k[0],'?')} | {m.get('layout')} | {m.get('special_issue')} | {m.get('rotate')} | {f(w.get('text'))} | {f(w.get('reading_order'))} | {f(M.get(k,{}).get(c))} | {f(D.get(k,{}).get(c))} | {m.get('cats')} |")

print("\n## 3. Por subject (v3a-clean), ordenado por overall_no_cdm")
by = defaultdict(list)
for k, w in V.items(): by[subj.get(k[0], "?")].append(w)
print("| subject | n | overall | text | RO | TEDS(n) | mineru ov | docling ov |\n|---|---|---|---|---|---|---|---|")
rows = []
for s, ws in by.items():
    ks = [key(w) for w in ws]
    mo = st.mean([M[k]["overall_no_cdm"] for k in ks if k in M]); do = st.mean([D[k]["overall_no_cdm"] for k in ks if k in D])
    t = comp(ws, "teds")
    rows.append((st.mean(comp(ws,"overall_no_cdm")), s, len(ws), st.mean(comp(ws,"text")), st.mean(comp(ws,"reading_order")), (st.mean(t) if t else None, len(t)), mo, do))
for o, s, n, t, ro, (td, tn), mo, do in sorted(rows):
    print(f"| {s} | {n} | {o:.1f} | {t:.1f} | {ro:.1f} | {td and f'{td:.1f}'}({tn}) | {mo:.1f} | {do:.1f} |")

print("\n## 3b. Por layout / special_issue (v3a-clean)")
for attr in ["layout", "special_issue", "language", "rotate"]:
    g = defaultdict(list)
    for k, w in V.items():
        v = page_meta(*k).get(attr); v = ",".join(v) if isinstance(v, list) else v
        g[str(v)].append(w)
    print(f"\n### {attr}\n| value | n | overall | text | RO |\n|---|---|---|---|---|")
    for v, ws in sorted(g.items(), key=lambda x: st.mean(comp(x[1],"overall_no_cdm"))):
        print(f"| {v} | {len(ws)} | {st.mean(comp(ws,'overall_no_cdm')):.1f} | {st.mean(comp(ws,'text')):.1f} | {st.mean(comp(ws,'reading_order')):.1f} |")

print("\n## 4. Tabelas (TEDS) — piores 10 em v3a-clean vs mineru/docling")
print("| uuid | page | subject | v3a | mineru | docling |\n|---|---|---|---|---|---|")
for s, k in sorted([(w["teds"], k) for k, w in V.items() if w.get("teds") is not None])[:10]:
    print(f"| {k[0][:8]} | {k[1]} | {subj.get(k[0])} | {s:.1f} | {f(M.get(k,{}).get('teds'))} | {f(D.get(k,{}).get('teds'))} |")
# pages where GT has table but pred has none, or vice versa
gt_t = [k for k, w in M.items() if w.get("teds") is not None]
print(f"\npáginas com TEDS (GT tem tabela): mineru {len(gt_t)}, docling {len([k for k,w in D.items() if w.get('teds') is not None])}, v3a {len([k for k,w in V.items() if w.get('teds') is not None])}")

print("\n## 6. Oracle por página (max entre v3a, mineru, docling) — md2md dev-986")
def page_score(w): 
    v = [w[c] for c in ["text", "reading_order", "teds", "cdm"] if w.get(c) is not None]; return st.mean(v) if v else None
def evalai_style(ws):
    v = [page_score(w) for w in ws]; v = [x for x in v if x is not None]; return st.mean(v)
print(f"v3a evalai_style = {evalai_style(RUNS['v3a-clean']):.2f}")
orc_page, orc_comp = [], []
wins = defaultdict(int)
for k, w in V.items():
    cands = {"v3a": w, "mineru": M.get(k), "docling": D.get(k)}
    cands = {n: c for n, c in cands.items() if c}
    best = max(cands.items(), key=lambda x: page_score(x[1]) or -1); wins[best[0]] += 1
    orc_page.append(page_score(best[1]))
    comps = {}
    for c in ["text", "reading_order", "teds", "cdm"]:
        vals = [x[c] for x in cands.values() if x.get(c) is not None]
        if vals: comps[c] = max(vals)
    orc_comp.append(st.mean(comps.values()) if comps else None)
orc_page = [x for x in orc_page if x is not None]; orc_comp = [x for x in orc_comp if x is not None]
print(f"oracle por página = {st.mean(orc_page):.2f} (wins: {dict(wins)})")
print(f"oracle por componente = {st.mean(orc_comp):.2f}")
for c in ["text", "reading_order", "teds"]:
    vals = []
    for k, w in V.items():
        cs = [x[c] for x in [w, M.get(k, {}), D.get(k, {})] if x.get(c) is not None]
        if cs: vals.append(max(cs))
    print(f"  oracle {c}: {st.mean(vals):.1f} (v3a {st.mean(comp(RUNS['v3a-clean'], c)):.1f})")
