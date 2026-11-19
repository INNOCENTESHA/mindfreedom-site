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
    hb_disp_fill: object = None  # m added to the wheel contact length; None = the fill depth (2V:1H through the fill)
    hb_step: float = 0.225     # m
    # factors
    gG: float = 1.35
    gG_min: float = 1.0
    gQ: float = 1.35
    n_div: int = 10            # divisions per cell span
    toe: float = 0.0           # projection of the base slab beyond the outer wall faces (m) - same toe as the wing walls
    profile: object = None     # detailing.soil.Profile: layered ground (earth pressure, water, subgrade stiffness)
    ks_from_profile: bool = True

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
        # the base slab runs on to the toes: from the wall centre line to the wall face (t/2) plus the toe
        bx=list(xst); self.toe_len=0.0
        if p.toe>1e-9:
            self.toe_len=p.t_wall/2+p.toe; nt=max(2,int(round(self.toe_len/(xst[1]-xst[0]))))
            left=[round(-self.toe_len+self.toe_len*k/nt,6) for k in range(nt)]
            right=[round(W+self.toe_len*k/nt,6) for k in range(1,nt+1)]
            bx=left+bx+right
        self.bx=bx
        self.base_nodes=[N(x,0.0) for x in bx]
        self.top_nodes =[N(x,Hc) for x in xst]
        self.members={'top':[], 'base':[], 'walls':[], 'piers':[], 'toe':[]}
        A=lambda t:(1.0*t, 1.0*t**3/12)
        At,It=A(p.t_top); Ab,Ib=A(p.t_base)
        for i in range(len(bx)-1):
            e=self.fr.add_element(self.base_nodes[i],self.base_nodes[i+1],p.Ecm*1e3,Ab,Ib)
            self.members['base'].append(e)
            if bx[i+1]<=1e-9 or bx[i]>=W-1e-9: self.members['toe'].append(e)
        for i in range(len(xst)-1):
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
        # Winkler springs under base nodes; stiffness from the layered ground when a profile is given
        self.base_width=bx[-1]-bx[0]+(p.t_wall if p.toe<=1e-9 else 0.0)
        self.founding_depth=p.fill+p.t_top+p.height+p.t_base
        self.ks=p.ks
        if p.profile is not None and p.ks_from_profile:
            self.ks=p.profile.subgrade_modulus(self.base_width,self.founding_depth)
        for i,nid in enumerate(self.base_nodes):
            if i==0: trib=(bx[1]-bx[0])/2
            elif i==len(bx)-1: trib=(bx[-1]-bx[-2])/2
            else: trib=(bx[i+1]-bx[i-1])/2
            self.fr.nodes[nid].ky += self.ks*trib
            self.fr.nodes[nid]._trib=trib
        # remove horizontal rigid-body: tiny x-restraint at base mid
        # horizontal restraint at the middle of the base: it carries only the out-of-balance of one-sided surcharge,
        # and is stiff so that the model has no near-rigid-body sway (which costs numerical precision)
        self.fr.nodes[self.base_nodes[len(self.base_nodes)//2]].kx += 1e7

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
            pr=p.profile
            q=pr.sigma_v(p.fill)[0] if pr is not None else p.gamma_soil*p.fill
            for ei in self.members['top']: self.fr.elements[ei].gy+=-q
            # soil standing on the toes (from the toe top up to ground level)
            zt=p.fill+p.t_top+p.height
            qt=pr.sigma_v(zt)[0] if pr is not None else p.gamma_soil*zt
            for ei in self.members['toe']: self.fr.elements[ei].gy+=-qt
        elif name=='EH':
            pr=p.profile; kg=p.K0*p.gamma_soil
            for wc in self.wall_chains:
                if not wc['outer']: continue
                for k,ei in enumerate(wc['els']):
                    ni,nj=wc['ids'][k],wc['ids'][k+1]
                    if pr is not None:                      # layered ground: K0 sigma'v + pore water, true depth below ground
                        zi=(Hc-self.fr.nodes[ni].y)+p.fill+p.t_top/2; zj=(Hc-self.fr.nodes[nj].y)+p.fill+p.t_top/2
                        li=pr.lateral_at_rest(max(zi,0)); lj=pr.lateral_at_rest(max(zj,0))
                        pi=li['earth']+li['water']; pj=lj['earth']+lj['water']
                    else:                                   # depth below ground: fill + half the top slab + below its centre line
                        zi=(Hc-self.fr.nodes[ni].y)+p.fill+p.t_top/2; zj=(Hc-self.fr.nodes[nj].y)+p.fill+p.t_top/2
                        pi=kg*max(zi,0); pj=kg*max(zj,0)
                    sgn=self._inward(ei,self.W_cl/2,Hc/2)
                    self.fr.elements[ei].wt_i+=sgn*pi; self.fr.elements[ei].wt_j+=sgn*pj
        elif name in ('LS','LS1'):
            pr=p.profile
            for wi,wc in enumerate(self.wall_chains):
                if not wc['outer']: continue
                if name=='LS1' and wi!=0: continue
                for k,ei in enumerate(wc['els']):
                    if pr is not None:
                        ni,nj=wc['ids'][k],wc['ids'][k+1]
                        zi=(Hc-self.fr.nodes[ni].y)+p.fill+p.t_top/2; zj=(Hc-self.fr.nodes[nj].y)+p.fill+p.t_top/2
                        pi=pr.layer_at(max(zi,0)).k0*p.surcharge; pj=pr.layer_at(max(zj,0)).k0*p.surcharge
                    else: pi=pj=p.K0*p.surcharge
                    sgn=self._inward(ei,self.W_cl/2,Hc/2)
                    self.fr.elements[ei].wt_i+=sgn*pi; self.fr.elements[ei].wt_j+=sgn*pj
            if name=='LS':
                for ei in self.members['toe']: self.fr.elements[ei].gy+=-p.surcharge
        elif name=='HB':
            self._hb(hb_pos, hb_two)
        u,res=self.fr.solve(); self._last_u=u; return res

    def _hb(self, x0, two):
        """Dispersed HB wheel load as downward patch on top slab, 2V:1H."""
        p=self.p
        # dispersal width (along strip) = contact + fill spread; per-metre line load
        contact=np.sqrt(p.hb_wheel/ (p.__dict__.get('hb_press',1.1)*1000))  # m (approx square)
        bw=contact + (p.fill if p.hb_disp_fill is None else p.hb_disp_fill)   # 2V:1H: half the depth each side
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
        """Axle positions: every cell divided into an even number of steps, so mid-span and quarter points are always loaded."""
        p=self.p; xs=[]
        for k in range(len(self.wall_x)-1):
            a,b=self.wall_x[k],self.wall_x[k+1]
            nd=2*max(4,int((b-a)/p.hb_step/2+0.5))
            for j in range(0 if k==0 else 1,nd+1): xs.append(round(a+(b-a)*j/nd,4))
        return xs

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
        tot=None
        for k,fac in fmap.items():
            Fk=self.F[k]
            if not isinstance(Fk,np.ndarray): Fk=self.F[k]=np.array(Fk)
            tot=fac*Fk if tot is None else tot+fac*Fk
        return tot

    def bearing(self, fmap):
        u=self.combine_u(fmap); pr=[]; Rs=[]
        for nid in self.base_nodes:
            ky=self.fr.nodes[nid].ky; R=abs(ky*u[3*nid+1]); trib=self.fr.nodes[nid]._trib
            pr.append(R/trib); Rs.append(ky*u[3*nid+1])      # + = compression on the ground (checked: sum equals the applied load)
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
        """EN 1990 STR with HB as the leading variable action, one axle position at a time:
        a) full lateral earth pressure with surcharge on both walls,
        b) minimum lateral pressure (gamma_G,inf) and no surcharge - governs the sagging of the slabs,
        c) minimum lateral pressure with surcharge on one wall only - sway.
        Plus the same three without traffic."""
        p=self.p; combos=[]
        for hb in self.hb_keys+[None]:
            a={'SW':p.gG,'EV':p.gG,'EH':p.gG,'LS':p.gQ}
            b={'SW':p.gG,'EV':p.gG,'EH':p.gG_min}
            c={'SW':p.gG,'EV':p.gG,'EH':p.gG_min,'LS1':p.gQ}
            for cmb in (a,b,c):
                if hb: cmb[hb]=p.gQ
                combos.append(cmb)
        return combos

    def sls_combos(self):
        """Characteristic combination: all actions at 1.0, each axle position in turn (and none)."""
        base={'SW':1.0,'EV':1.0,'EH':1.0,'LS':1.0}; combos=[]
        for hb in self.hb_keys+[None]:
            c=dict(base)
            if hb: c[hb]=1.0
            combos.append(c)
        return combos

    def qp_combo(self):
        """Quasi-permanent combination: permanent actions only (psi2 = 0 for HB and surcharge)."""
        return {'SW':1.0,'EV':1.0,'EH':1.0}

    # ---------- internal actions along the members ----------
    def _chain(self, els):
        """x (or z) stations and element list of a straight member chain."""
        fr=self.fr; e0=fr.elements[els[0]]
        horiz=abs(fr.nodes[e0.nj].x-fr.nodes[e0.ni].x)>abs(fr.nodes[e0.nj].y-fr.nodes[e0.ni].y)
        st=[(fr.nodes[fr.elements[e].ni].x if horiz else fr.nodes[fr.elements[e].ni].y) for e in els]
        last=fr.elements[els[-1]]; st.append(fr.nodes[last.nj].x if horiz else fr.nodes[last.nj].y)
        return st,horiz

    def diagram(self, els, F):
        """Internal moment (positive = tension on the -local-y side, i.e. sagging for a slab drawn left to right),
        shear and axial force at the element ends of a chain: lists of (station, M, V, N) with two entries per joint."""
        st,_=self._chain(els); out=[]
        for k,e in enumerate(els):
            f=F[e]
            out.append((st[k],   f[2],  f[1], -f[0]))      # checked on dead load: mid-span sags (+), supports hog (-)
            out.append((st[k+1], -f[5], -f[4],  f[3]))
        return out

    def shear_at(self, els, F, pos):
        """Shear force at station pos of a chain (linear inside an element)."""
        st,_=self._chain(els)
        for k,e in enumerate(els):
            a,b=st[k],st[k+1]
            if min(a,b)-1e-9<=pos<=max(a,b)+1e-9:
                f=F[e]; xi=(pos-a)/(b-a) if abs(b-a)>1e-12 else 0.0
                return f[1]+(-f[4]-f[1])*xi
        return 0.0

    def faces(self, member):
        """Chains of a member with the stations of the support faces: [(elements, [(face station, direction into the span)])]."""
        p=self.p; out=[]
        if member in('top','base'):
            sup=[]
            for wc in self.wall_chains:
                sup.append((wc['x']+wc['t']/2,+1.0)); sup.append((wc['x']-wc['t']/2,-1.0))
            lo,hi=(self.bx[0],self.bx[-1]) if member=='base' else (self.xst[0],self.xst[-1])
            out.append((self.members[member],[(x,d) for x,d in sup if lo-1e-9<=x<=hi+1e-9]))
        else:
            for wc in self.wall_chains:
                if wc['outer']!=(member=='walls'): continue
                out.append((wc['els'],[(p.t_base/2,+1.0),(p.Hc-p.t_top/2,-1.0)]))
        return out

    def design_actions(self, member, combos, d):
        """Envelope for the design of one member type.
        M_in / M_out: largest moments putting the inner / outer face in tension (kNm/m),
        V_d: largest shear at the effective depth d from a support face (6.2.1(8)), V_face: at the face."""
        p=self.p; M_in=M_out=V_d=V_f=N_c=0.0
        for fmap in combos:
            F=self.combine_F(fmap)
            for ci,(els,sup) in enumerate(self.faces(member)):
                for stn,m,v,n in self.diagram(els,F):
                    if member=='top': a,b=m,-m                      # sagging -> inner (bottom) face
                    elif member=='base': a,b=-m,m                   # sagging -> outer (bottom) face
                    else:
                        x=self.fr.nodes[self.fr.elements[els[0]].ni].x
                        right=x>self.W_cl/2
                        a,b=((-m,m) if right else (m,-m)) if member=='walls' else (abs(m),abs(m))
                    M_in=max(M_in,a); M_out=max(M_out,b); N_c=max(N_c,n)
                st,_=self._chain(els); lo,hi=min(st),max(st)
                for x,dr in sup:
                    V_f=max(V_f,abs(self.shear_at(els,F,x)))
                    xd=x+dr*d
                    if lo<=xd<=hi: V_d=max(V_d,abs(self.shear_at(els,F,xd)))
        return dict(M_in=M_in,M_out=M_out,V_d=V_d,V_face=V_f,N=N_c)
