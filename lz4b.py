def decompress(src, uncompressed_size=None, prefix=b''):
    dst=bytearray(prefix); P=len(prefix); i=0; n=len(src)
    while i<n:
        t=src[i]; i+=1; ll=t>>4
        if ll==15:
            while True:
                b=src[i]; i+=1; ll+=b
                if b!=255: break
        dst+=src[i:i+ll]; i+=ll
        if i>=n: break
        off=src[i]|(src[i+1]<<8); i+=2; ml=t&15
        if ml==15:
            while True:
                b=src[i]; i+=1; ml+=b
                if b!=255: break
        ml+=4; s=len(dst)-off
        if off>=ml: dst+=dst[s:s+ml]
        else:
            for k in range(ml): dst.append(dst[s+k])
    return bytes(dst[P:])
