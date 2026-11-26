"""Tiny grayscale canvas backed by system libcairo; export 1-bit LCD frames."""
import ctypes as C, ctypes.util, struct, zlib
from functools import lru_cache
try:lib=C.CDLL('libcairo.so.2')
except OSError:lib=C.CDLL(ctypes.util.find_library('cairo') or '/opt/homebrew/lib/libcairo.2.dylib')
P=C.c_void_p; I=C.c_int; D=C.c_double; S=C.c_char_p
class Ext(C.Structure):
    _fields_=[(k,D) for k in ('x','y','w','h','dx','dy')]
def bind(name,out,*args):
    f=getattr(lib,'cairo_'+name); f.restype=out; f.argtypes=list(args); return f
surface=bind('image_surface_create',P,I,I,I); create=bind('create',P,P)
data=bind('image_surface_get_data',P,P); flush=bind('surface_flush',None,P)
rect=bind('rectangle',None,P,D,D,D,D); fill=bind('fill',None,P); color=bind('set_source_rgb',None,P,D,D,D)
move=bind('move_to',None,P,D,D); select=bind('select_font_face',None,P,S,I,I); size=bind('set_font_size',None,P,D)
show=bind('show_text',None,P,S); measure=bind('text_extents',None,P,S,C.POINTER(Ext)); destroy=bind('destroy',None,P); free=bind('surface_destroy',None,P)
class Canvas:
    def __init__(self):
        self.sf=surface(1,400,240); self.c=create(self.sf); self.box(0,0,400,240,1)
    def box(self,x,y,w,h,white=0):
        color(self.c,white,white,white);rect(self.c,x,y,w,h);fill(self.c)
    def text(self,x,y,s,px,bold=False,white=False,align='left',maxw=None):
        # y is baseline. Use real glyph advances; fonts are installed on Lapis.
        s=str(s).encode(); select(self.c,b'Noto Sans CJK SC',0,int(bold)); size(self.c,px)
        e=Ext(); measure(self.c,s,C.byref(e))
        if maxw and e.dx>maxw:
            size(self.c,px*maxw/e.dx); measure(self.c,s,C.byref(e))
        if align=='center': x-=e.dx/2
        if align=='right': x-=e.dx
        color(self.c,*([int(white)]*3));move(self.c,round(x),y);show(self.c,s)
    def finish(self):
        flush(self.sf); raw=C.string_at(data(self.sf),400*240*4)[::4]; destroy(self.c);free(self.sf)
        return int(raw.translate(bytes([48]*140+[49]*116)),2).to_bytes(12000,'big')
def png(frame,path):
    def chunk(k,v):return struct.pack('>I',len(v))+k+v+struct.pack('>I',zlib.crc32(k+v)&0xffffffff)
    scan=b''.join(b'\0'+frame[i:i+50] for i in range(0,12000,50))
    with open(path,'wb') as f:f.write(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',400,240,1,0,0,0,0))+chunk(b'IDAT',zlib.compress(scan))+chunk(b'IEND',b''))
