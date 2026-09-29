import struct, lz4b, lsf2
def frame(b):
    assert b[:4]==b'\x04\x22\x4d\x18', b[:4]
    flg=b[4]; bd=b[5]; p=7
    if flg&0x08: p+=8
    out=bytearray()
    while True:
        (sz,)=struct.unpack_from('<I',b,p); p+=4
        if sz==0: break
        unc=sz&0x80000000; sz&=0x7fffffff
        blk=b[p:p+sz]; p+=sz
        if unc: out+=blk
        else: out+=lz4b.decompress(blk, prefix=bytes(out[-65536:]) if not (flg&0x20) else b'')
        if flg&0x10: p+=4
    return bytes(out)
def decompress_sec(data,usize,disk,flags):
    if disk==0: return data[:usize]
    if data[:4]==b'\x04\x22\x4d\x18': return frame(data)
    return lz4b.decompress(data,usize)
def to_uncompressed(b):
    m=list(struct.unpack_from(lsf2.HF,b,16)); off=16+struct.calcsize(lsf2.HF)
    secs=[]
    for i in range(0,10,2):
        u,dsk=m[i],m[i+1]; n=dsk if dsk else u
        secs.append(decompress_sec(b[off:off+n],u,dsk,m[10])); off+=n
    for i in range(5): m[2*i]=len(secs[i]); m[2*i+1]=0
    m[10]=0
    return b[:16]+struct.pack(lsf2.HF,*m)+b''.join(secs)
