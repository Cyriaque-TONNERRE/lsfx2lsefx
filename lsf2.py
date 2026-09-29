import struct, collections
HF='<IIIIIIIIIIBBHI'
def parse(b):
    ver=struct.unpack_from('<I',b,4)[0]
    if ver>=6:
        m=struct.unpack_from(HF,b,16); su,_,_,_,nu,_,au,_,vu,_,_,_,_,sib=m; off=16+struct.calcsize(HF)
    else:
        m=struct.unpack_from('<IIIIIIIIBBHI',b,16); su,_,nu,_,au,_,vu,_,cf,_,_,sib=m; off=16+struct.calcsize('<IIIIIIIIBBHI')
        assert all(x==0 for x in (m[1],m[3],m[5],m[7])) and cf==0, 'compressed v5'
    S=b[off:off+su]; off+=su; N=b[off:off+nu]; off+=nu; A=b[off:off+au]; off+=au; Voff=off; V=b[off:off+vu]
    names=[]; p=0; (nh,)=struct.unpack_from('<I',S,p); p+=4
    for h in range(nh):
        (cnt,)=struct.unpack_from('<H',S,p); p+=2; row=[]
        for i in range(cnt):
            (l,)=struct.unpack_from('<H',S,p); p+=2; row.append(S[p:p+l].decode()); p+=l
        names.append(row)
    nm=lambda x: names[x>>16][x&0xffff]
    if sib==1:
        raw=[struct.unpack_from('<Iiii',N,i) for i in range(0,len(N),16)]  # name,parent,nextsib,firstattr
        nodes=[dict(name=nm(n),first=f,parent=p) for n,p,s,f in raw]
        araw=[struct.unpack_from('<IIiI',A,i) for i in range(0,len(A),16)]
        owner={}
        for ni,nd in enumerate(nodes):
            a=nd['first']
            while a!=-1: owner[a]=ni; a=araw[a][2]
        attrs=[dict(name=nm(h),type=tl&63,len=tl>>6,node=owner.get(i,-1),off=o) for i,(h,tl,nx,o) in enumerate(araw)]
    else:
        raw=[struct.unpack_from('<Iii',N,i) for i in range(0,len(N),12)]
        nodes=[dict(name=nm(n),first=f,parent=p) for n,f,p in raw]
        attrs=[]; o=0
        for i in range(0,len(A),12):
            h,tl,node=struct.unpack_from('<IIi',A,i); t=tl&63; l=tl>>6
            attrs.append(dict(name=nm(h),type=t,len=l,node=node,off=o)); o+=l
    return dict(nodes=nodes,attrs=attrs,V=V,Voff=Voff,sib=sib)
import uuid
def gdec(raw):
    t=raw[8:]; fixed=raw[:8]+bytes(x for i in range(0,8,2) for x in (t[i+1],t[i]))
    return str(uuid.UUID(bytes_le=fixed))
def val(d,a):
    raw=d['V'][a['off']:a['off']+a['len']]; t=a['type']
    if t==31: return gdec(raw)
    if t in (20,21,22,23,29,30): return raw.rstrip(b'\0').decode(errors='replace')
    if t==6: return struct.unpack('<f',raw)[0]
    if t==13: return struct.unpack('<4f',raw)
    if t==12: return struct.unpack('<3f',raw)
    if t==19: return raw[0]
    if t in (4,5): return struct.unpack('<i' if t==4 else '<I',raw)[0]
    return raw.hex()
def subtree(d,root):
    kids={}
    for i,n in enumerate(d['nodes']): kids.setdefault(n['parent'],[]).append(i)
    byn={}
    for a in d['attrs']: byn.setdefault(a['node'],[]).append(a)
    out=[]
    def rec(i,dep):
        out.append('  '*dep+d['nodes'][i]['name']+' '+' '.join(f"{a['name']}={val(d,a)}" for a in byn.get(i,[])))
        for k in kids.get(i,[]): rec(k,dep+1)
    rec(root,0); return out
