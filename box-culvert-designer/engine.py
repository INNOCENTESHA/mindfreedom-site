"""
Multi-cell RC box culvert engine (BS 5400 HB loading + EN 1992-1-1 design).
Clean-room reimplementation of the CBC Parametric Designer's modFrame/DESIGN.
Reuses the validated plane-frame solver in frame.py.
Units: m, kN, kPa. 1 m longitudinal strip.
"""
from __future__ import annotations
import numpy as np
from dataclasses import dataclass, field
from frame import Frame


@dataclass
class P:
    n_cells: int = 4
    span: float = 1.5          # clear span per cell (m)
    height: float = 1.5        # clear height (m)
    t_top: float = 0.25
    t_base: float = 0.25
    t_wall: float = 0.25       # outer walls
    t_pier: float = 0.25       # inner (pier) walls
    fill: float = 1.0          # design fill depth over top slab (m)
    # materials
    fck: float = 25.0          # MPa (C25/30)
    fyk: float = 460.0
    Ecm: float = 31000.0       # MPa
    cover: float = 0.050
    gamma_conc: float = 25.0   # kN/m3
    gamma_soil: float = 20.0
    K0: float = 0.5            # at-rest
    surcharge: float = 16.67   # kPa
    ks: float = 30000.0        # Winkler kN/m3
    # HB (BS 5400)
    hb_units: float = 37.5
    hb_wheel: float = 93.75    # kN  (= units*10/4)
    hb_axle_sp: float = 1.8    # m (inner axle spacing)
    hb_wheel_sp: float = 1.0   # m (across axle)
    hb_disp_fill: float = 1.0  # m, fill used to disperse (2V:1H)
    hb_step: float = 0.225     # m
    # factors
    gG: float = 1.35
    gG_min: float = 1.0
    gQ: float = 1.35
    n_div: int = 10            # divisions per cell span

    @property
    def W_ext(self):           # external width
        return self.n_cells*self.span + (self.n_cells+1)*self.t_wall if self.t_pier==self.t_wall \
               else self.n_cells*self.span + 2*self.t_wall + (self.n_cells-1)*self.t_pier
    @property
    def Hc(self):              # centreline height
        return self.height + (self.t_top + self.t_base)/2


class Box:
    def __init__(self, p: P):
        self.p = p
        self._build()

    def _wall_xs(self):
        """Centreline x of each vertical wall (outer, piers..., outer)."""
        p = self.p; xs = [0.0]
        xs.append(p.span + p.t_wall/2 + p.t_pier/2)       # first gap: outer->pier
        for k in range(p.n_cells-2):
            xs.append(xs[-1] + p.span + p.t_pier)          # pier->pier
        if p.n_cells >= 2:
            xs.append(xs[-1] + p.span + p.t_pier/2 + p.t_wall/2)  # pier->outer
        return xs

    def _build(self):
        p = self.p; self.fr = Frame()
        self.wall_x = self._wall_xs()
        W = self.wall_x[-1]; self.W_cl = W; Hc = p.Hc
        # horizontal x-stations: divide each cell span, include wall centrelines
        xset = set(round(x,6) for x in self.wall_x)
        for i in range(len(self.wall_x)-1):
            a,b = self.wall_x[i], self.wall_x[i+1]
            for k in range(p.n_div+1):
                xset.add(round(a + (b-a)*k/p.n_div, 6))
        xst = sorted(xset)
        self.xst = xst
        # node lookup by (x,z)
        self.nid = {}
        def N(x,z):
            key=(round(x,6),round(z,6))
            if key not in self.nid: self.nid[key]=self.fr.add_node(x,z)
            return self.nid[key]
        # base & top chains
        self.base_nodes=[N(x,0.0) for x in xst]
        self.top_nodes =[N(x,Hc) for x in xst]
        self.members={'top':[], 'base':[], 'walls':[], 'piers':[]}
        A=lambda t:(1.0*t, 1.0*t**3/12)
        At,It=A(p.t_top); Ab,Ib=A(p.t_base)
        for i in range(len(xst)-1):
            e=self.fr.add_element(self.base_nodes[i],self.base_nodes[i+1],p.Ecm*1e3,Ab,Ib)
            self.members['base'].append(e)
            e=self.fr.add_element(self.top_nodes[i],self.top_nodes[i+1],p.Ecm*1e3,At,It)
            self.members['top'].append(e)
        # walls (vertical chains) at each wall_x
        zst=sorted(set([round(Hc*k/p.n_div,6) for k in range(p.n_div+1)]))
        self.wall_chains=[]
        for wi,wx in enumerate(self.wall_x):
            outer = wi in (0,len(self.wall_x)-1)
            t = p.t_wall if outer else p.t_pier
            Aw,Iw=A(t)
            ids=[N(wx,z) for z in zst]
            els=[self.fr.add_element(ids[k],ids[k+1],p.Ecm*1e3,Aw,Iw) for k in range(len(zst)-1)]
            self.wall_chains.append(dict(x=wx,outer=outer,t=t,ids=ids,els=els))
            self.members['walls' if outer else 'piers'].extend(els)
        # Winkler springs under base nodes
        for i,nid in enumerate(self.base_nodes):
            if i==0: trib=(xst[1]-xst[0])/2
            elif i==len(xst)-1: trib=(xst[-1]-xst[-2])/2
            else: trib=(xst[i+1]-xst[i-1])/2
            self.fr.nodes[nid].ky += p.ks*trib
            self.fr.nodes[nid]._trib=trib
        # remove horizontal rigid-body: tiny x-restraint at base mid
        self.fr.nodes[self.base_nodes[0]].kx += 1e-3

    # ---------- loads ----------
    def _fresh(self):
        for e in self.fr.elements: e.wt_i=e.wt_j=e.wa=e.gy=0.0
    def _inward(self, ei, cx, cz):
        e=self.fr.elements[ei]; ni,nj=self.fr.nodes[e.ni],self.fr.nodes[e.nj]
        dx,dz=nj.x-ni.x,nj.y-ni.y; L=np.hypot(dx,dz); c,s=dx/L,dz/L
        tx,tz=-s,c; mx,mz=(ni.x+nj.x)/2,(ni.y+nj.y)/2
        return 1.0 if (tx*(cx-mx)+tz*(cz-mz))>=0 else -1.0

    def case(self, name, hb_pos=None, hb_two=False, hb_wall=None):
        p=self.p; self._fresh(); Hc=p.Hc
        if name=='SW':
            tmap={'top':p.t_top,'base':p.t_base}
            for m in ('top','base'):
                for ei in self.members[m]: self.fr.elements[ei].gy+=-p.gamma_conc*tmap[m]
            for wc in self.wall_chains:
                for ei in wc['els']: self.fr.elements[ei].gy+=-p.gamma_conc*wc['t']
        elif name=='EV':
            q=p.gamma_soil*p.fill
            for ei in self.members['top']: self.fr.elements[ei].gy+=-q
        elif name=='EH':
            kg=p.K0*p.gamma_soil
            for wc in self.wall_chains:
                if not wc['outer']: continue
                for k,ei in enumerate(wc['els']):
                    ni,nj=wc['ids'][k],wc['ids'][k+1]
                    zi=(Hc-self.fr.nodes[ni].y)+p.fill; zj=(Hc-self.fr.nodes[nj].y)+p.fill
                    pi=kg*max(zi,0); pj=kg*max(zj,0); sgn=self._inward(ei,self.W_cl/2,Hc/2)
                    self.fr.elements[ei].wt_i+=sgn*pi; self.fr.elements[ei].wt_j+=sgn*pj
        elif name in ('LS','LS1'):
            press=p.K0*p.surcharge
            for wi,wc in enumerate(self.wall_chains):
                if not wc['outer']: continue
                if name=='LS1' and wi!=0: continue
                for ei in wc['els']:
                    sgn=self._inward(ei,self.W_cl/2,Hc/2)
                    self.fr.elements[ei].wt_i+=sgn*press; self.fr.elements[ei].wt_j+=sgn*press
        elif name=='HB':
            self._hb(hb_pos, hb_two)
        u,res=self.fr.solve(); self._last_u=u; return res

    def _hb(self, x0, two):
        """Dispersed HB wheel load as downward patch on top slab, 2V:1H."""
        p=self.p
        # dispersal width (along strip) = contact + fill spread; per-metre line load
        contact=np.sqrt(p.hb_wheel/ (p.__dict__.get('hb_press',1.1)*1000))  # m (approx square)
        bw=contact + p.hb_disp_fill                # 2V:1H -> +H each... total +fill
        # load per metre of strip over width bw, for one wheel line in 1 m strip
        w_line = p.hb_wheel / bw                    # kN/m over bw
        axles=[x0] + ([x0+p.hb_axle_sp] if two else [])
        for ax in axles:
            a=ax-bw/2; b=ax+bw/2
            self._patch_top(a,b,w_line)

    def _patch_top(self, a, b, w):
        """Apply downward UDL w (kN/m) on top slab between x=a..b (clipped)."""
        for i,ei in enumerate(self.members['top']):
            e=self.fr.elements[ei]
            xi=self.fr.nodes[e.ni].x; xj=self.fr.nodes[e.nj].x
            lo,hi=min(xi,xj),max(xi,xj); ov=max(0,min(hi,b)-max(lo,a))
            if ov>0:
                frac=ov/(hi-lo); e.gy+=-w*frac   # approx: fraction of element covered

    def hb_positions(self):
        p=self.p; xs=[]; x=0.0
        while x<=self.W_cl+1e-9: xs.append(round(x,4)); x+=p.hb_step
        return xs

    # ---------- analysis driver ----------
    def analyse(self):
        """Run all static cases + HB moving positions; store u and member forces."""
        self.u={}; self.F={}
        for nm in ('SW','EV','EH','LS','LS1'):
            res=self.case(nm); self.u[nm]=self._last_u.copy()
            self.F[nm]=[np.array(r) for r in res]
        # HB moving: single & двух-axle at each position -> keep envelope per element
        self.hb_keys=[]
        for two in (False,True):
            for x in self.hb_positions():
                k=f"HB{'2' if two else '1'}@{x:.3f}"
                res=self.case('HB',hb_pos=x,hb_two=two)
                self.u[k]=self._last_u.copy(); self.F[k]=[np.array(r) for r in res]
                self.hb_keys.append(k)
        return self

    def combine_u(self, fmap):
        tot=None
        for k,fac in fmap.items():
            tot=fac*self.u[k] if tot is None else tot+fac*self.u[k]
        return tot
    def combine_F(self, fmap):
        ne=len(self.fr.elements); out=[np.zeros(6) for _ in range(ne)]
        for k,fac in fmap.items():
            Fk=self.F[k]
            for i in range(ne): out[i]=out[i]+fac*Fk[i]
        return out

    def bearing(self, fmap):
        u=self.combine_u(fmap); pr=[]; Rs=[]
        for nid in self.base_nodes:
            ky=self.fr.nodes[nid].ky; R=abs(ky*u[3*nid+1]); trib=self.fr.nodes[nid]._trib
            pr.append(R/trib); Rs.append(ky* -u[3*nid+1])
        return max(pr),min(pr),min(Rs)

    def envelope(self, member, combos):
        els=self.members[member]; Mmin=Mmax=Vmax=Nmax=0.0
        for fmap in combos:
            F=self.combine_F(fmap)
            for ei in els:
                f=F[ei]
                Mmin=min(Mmin,f[2],f[5]); Mmax=max(Mmax,f[2],f[5])
                Vmax=max(Vmax,abs(f[1]),abs(f[4])); Nmax=max(Nmax,abs(f[0]),abs(f[3]))
        return dict(Mmin=Mmin,Mmax=Mmax,Vmax=Vmax,Nmax=Nmax)

    def uls_combos(self):
        """EC2 STR: 1.35G + 1.35Q, HB leading (one HB case at a time)."""
        p=self.p; base={'SW':p.gG,'EV':p.gG,'EH':p.gG}
        combos=[]
        for hb in self.hb_keys:
            c=dict(base); c['LS']=p.gQ; c[hb]=p.gQ; combos.append(c)
        # also surcharge-leading without HB, and min-G uplift case
        c=dict(base); c['LS']=p.gQ; combos.append(c)
        return combos

    def sls_combos(self):
        p=self.p; base={'SW':1.0,'EV':1.0,'EH':1.0}
        combos=[]
        for hb in self.hb_keys:
            c=dict(base); c['LS']=1.0; c[hb]=1.0; combos.append(c)
        c=dict(base); c['LS']=1.0; combos.append(c)
        return combos
