"""End-to-end: analyse -> design -> AutoCAD DXF + calc report."""
from culvert import Culvert, Params
from design import design_flexure, check_shear
from dxf_export import export_dxf
import os

ULS = {"SW":1.35,"EV":1.35,"EH":1.5,"SUR":1.5,"LL":1.5,"WA":1.0}

def run(p: Params, outdir="outputs", name="box_culvert"):
    os.makedirs(outdir, exist_ok=True)
    c = Culvert(p); c.analyse(); f = c.combine(ULS)
    def mm_(m):
        Ms=[f[ei][2] for ei in c.members[m]]+[f[c.members[m][-1]][5]]
        return min(Ms), max(Ms)
    Vof={m:max(abs(f[ei][1]) for ei in c.members[m]) for m in ['top','bottom','left','right']}
    tmap={'top':p.t_top,'bottom':p.t_bot,'left':p.t_wall,'right':p.t_wall}
    faces={}; report=[]
    report.append(f"# Box Culvert Design Report\n")
    report.append(f"Cell {p.clear_span:.2f} x {p.clear_height:.2f} m | cover fill "
                  f"{p.cover_fill:.2f} m | C{p.fck:.0f} | fyk {p.fyk:.0f}\n")
    report.append("| Member | Face | M (kNm) | As,req | Bars | As,prov | Util | Shear |")
    report.append("|---|---|---:|---:|---|---:|---:|---|")
    for m in ['top','bottom','left','right']:
        lo,hi=mm_(m); t=tmap[m]
        outer,_=design_flexure(m,lo,t,p.fck,p.fyk,p.cover)   # support/outer
        inner,_=design_flexure(m,hi,t,p.fck,p.fyk,p.cover)   # span/inner
        sh=check_shear(m,Vof[m],t,p.fck,p.cover,outer.As_prov)
        faces[m]=[(outer.dia,outer.spacing),(inner.dia,inner.spacing)]
        for tag,fd in [("support/outer",outer),("span/inner",inner)]:
            report.append(f"| {m} | {tag} | {fd.M:.1f} | {fd.As_req:.0f} | "
                          f"T{fd.dia}@{fd.spacing} | {fd.As_prov:.0f} | {fd.util:.2f} | "
                          f"{'OK' if sh.ok else 'FAIL'} ({sh.util:.2f}) |")
    dxf=os.path.join(outdir,f"{name}.dxf")
    export_dxf(dxf,p,faces)
    rep=os.path.join(outdir,f"{name}_report.md")
    open(rep,"w").write("\n".join(report)+"\n")
    return dxf, rep

if __name__ == "__main__":
    dxf, rep = run(Params())
    print("DXF :", dxf)
    print("RPT :", rep)
    print(open(rep).read())
