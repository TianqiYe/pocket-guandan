"""App-window protocol v1: foreground-only A and fingerprint gestures."""
import argparse,asyncio,signal,socket,struct,sys
from pocket import Table
from ui_text import LANGUAGES
SVC='ai.pamir.Lapis1'; MGR=SVC+'.AppWindowManager'; PATH='/ai/pamir/Lapis1/AppWindowManager'; HDR=struct.Struct('<4sHHHHIIIQQQII')
async def main(opening_seed=None, lang='en', difficulty='hard', host=False, join=None, seat=None, port=7777, tailcat=True):
    from dbus_fast.aio import MessageBus
    from dbus_fast import Message,MessageType,BusType
    if join:
        import net;t=net.RemoteTable(lang);asyncio.create_task(net.join(t,join,seat,port))
    else:
        t=Table(opening_seed, lang=lang, difficulty=difficulty)
        if host:
            import net;await net.Host(t,port).start(tailcat)
    bus=await MessageBus(bus_type=BusType.SYSTEM,negotiate_unix_fd=True).connect();loop=asyncio.get_running_loop()
    async def call(method,sig='',body=(),fds=()):
        r=await bus.call(Message(destination=SVC,path=PATH,interface=MGR,member=method,signature=sig,body=list(body),unix_fds=list(fds)))
        if r.message_type==MessageType.ERROR:raise RuntimeError(method,r.error_name,r.body)
        return r.body
    caps=(await call('GetInputCapabilities'))[0]
    if caps&3!=3:raise RuntimeError('Missing focused-input or back support')
    srv,sock=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
    with srv,sock:
        sock.setblocking(False)
        title='Guandan Guest' if join else 'Guandan Host' if host else 'Guandan Hard' if difficulty=='hard' else 'Guandan Hand'
        win=await call('CreateWindow','ssh',[title,'gamepad',0],[srv.fileno()]);srv.close();print('window:',win,flush=True)
        ident=None;seq=last_input=0;shown=False
        while True:
            pkt=await loop.sock_recv(sock,1024)
            if not pkt:break
            _,_,kind,_,fl,wid,wg,vg,serial,token,ns,_,_=HDR.unpack_from(pkt);grant=(wid,wg,vg,token)
            if kind==2:
                seq=last_input=0;ident=grant if fl&1 else None;t.focus(bool(ident));print('visible:',bool(ident),flush=True)
            elif kind==3 and ident==grant:
                t.tick();frame=t.frame();seq+=1
                sock.send(HDR.pack(b'LPFW',1,1,HDR.size,15,wid,wg,vg,seq,token,0,len(frame),0)+frame)
            elif kind==8 and ident==grant and serial>last_input:
                if serial!=last_input+1:t.clear_input()
                last_input=serial;t.input(fl,ns/1e9)
            elif kind==4 and not shown:shown=True;print('first frame presented; focused gesture routing requested',flush=True)
            elif kind==6:break
    bus.disconnect()
def parse_args(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--opening-seed',type=int,help='Reproducible first deal only; replays are shuffled normally.')
    parser.add_argument('--lang', choices=LANGUAGES, default='en', help='Display language (default: en).')
    parser.add_argument('--difficulty', choices=('classic','hard'), default='hard',
                        help='Opponent difficulty. Your partner stays Classic in both modes.')
    parser.add_argument('--host', action='store_true', help='Host a match; guests take bot seats.')
    parser.add_argument('--join', metavar='ADDR', help='Join a host: a tailcat address, or tcp:HOST:PORT.')
    parser.add_argument('--seat', type=int, choices=(1,2,3), help='Seat to request when joining: 1 Right, 2 Partner, 3 Left (default: first free, opponents first).')
    parser.add_argument('--port', type=int, default=7777)
    parser.add_argument('--no-tailcat', action='store_true', help='Host on plain localhost TCP only.')
    return parser.parse_args(argv)

if __name__=='__main__':
    args=parse_args()
    signal.signal(signal.SIGTERM,lambda*_:sys.exit(0))  # unwind so the tailcat child is stopped
    asyncio.run(main(args.opening_seed, args.lang, args.difficulty, args.host, args.join, args.seat, args.port, not args.no_tailcat))
