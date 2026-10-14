import re,sys,glob,os
sys.path.insert(0,'scripts')
from page_fuse import fuse
from vlm_page_select import strip_comment
A,V,O,R=sys.argv[1],sys.argv[2],sys.argv[3],float(sys.argv[4])
os.makedirs(O,exist_ok=True);n=0
nb=lambda t:len([x for x in re.split(r"\n\s*\n",t) if x.strip()])
nl=lambda t:len([x for x in t.splitlines() if x.strip()])
for f in sorted(glob.glob(A+'/*.drbench.md')):
    ta=open(f).read();p=os.path.join(V,os.path.basename(f));tv=strip_comment(open(p).read()) if os.path.exists(p) else ''
    out=ta
    if tv.strip() and nl(ta)>=10 and nl(ta)/max(nb(ta),1)>=R and nb(tv)>=2*nb(ta):
        out=fuse(ta,tv,'order',0.6);n+=1
    open(os.path.join(O,os.path.basename(f)),'w').write(out)
print('picked',n)
