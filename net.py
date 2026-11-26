"""Multiplayer: the host owns the match, guests mirror it from their own seat.

Newline-delimited JSON over a local TCP port. `tailcat serve PORT` exposes that
port; guests reach it with `tailcat ADDR PORT` as a stdin/stdout pipe.

Host -> guest: a snapshot already rotated so the guest sits at seat 0. Only the
guest's own hand is sent; other counts are exact at 0..10, or 11 for 'more than 10'.
Guest -> host: {"op": "hello", "seat": n?} once, then play / pass / tribute / next.
"""
import asyncio
import json
import os
import re
import shutil
import sys

from guandan import PhysicalGame, PhysicalMove, _level_rules
from ink import Canvas
from pocket import Table
from ui_text import language

PORT = 7777
PING, GUEST_TIMEOUT = 5, 20  # seconds; a killed tailcat client never sends EOF
_BUNDLED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bin', 'tailcat')


def tailcat_bin():
    """Prefer a tailcat dropped into ./bin (Lapis doesn't ship the CLI)."""
    if sys.platform.startswith('linux') and os.access(_BUNDLED, os.X_OK):
        return _BUNDLED
    return shutil.which('tailcat')


SEAT_ORDER = (1, 2, 3)  # first guest plays against the host
_NAMES = ('你', '下家', '队友', '上家')
# '队友第N' in a result line is the head's partner, not a seat name.
_WORDS = re.compile('下家|队友(?!第)|上家|你|我方|对方')


def rotate_text(text, seat):
    """Rewrite host-relative seat and team words for the guest at `seat`."""
    def swap(m):
        w = m.group()
        if w in ('我方', '对方'):
            return w if seat % 2 == 0 else ('对方' if w == '我方' else '我方')
        return _NAMES[(_NAMES.index(w) - seat) % 4]
    return _WORDS.sub(swap, text) if seat else text


def _move_json(m):
    return {'cards': [list(c) for c in m.cards], 'kind': m.kind, 'power': m.power,
            'ranks': list(m.ranks), 'suit': m.suit, 'level': m.level}


def _move(d):
    return PhysicalMove(tuple(tuple(c) for c in d['cards']), d['kind'], d['power'],
                        tuple(d['ranks']), d['suit'], d['level'])


def snapshot(t, seat):
    g, m = t.game, t.match
    rel = lambda s: None if s is None else (s - seat) % 4
    turns = lambda xs: [xs[(seat + i) % 4] for i in range(4)]
    return {
        'level': g.level,
        'hand': [list(c) for c in g.hands[seat]],
        'counts': turns([len(h) if i == seat else min(len(h), 11)
                         for i, h in enumerate(g.hands)]),
        'turn': rel(g.turn), 'owner': rel(g.owner), 'over': g.over,
        'finish': [rel(s) for s in g.finish],
        'top': _move_json(g.top) if g.top else None,
        'last': turns(g.last),
        'phase': m.phase, 'actor': rel(m.actor),
        'message': rotate_text(m.message, seat), 'summary': rotate_text(m.summary, seat),
        'champion': None if m.champion is None else (m.champion - seat) % 2,
        'levels': [m.levels[seat % 2], m.levels[1 - seat % 2]],
        'eligible': [c[2] for c in m.eligible()] if m.phase == 'tribute' and m.actor == seat else [],
        'notice': rotate_text(t.notice, seat), 'deal': t.deal,
    }


def apply_action(t, seat, msg):
    """Validate a guest's action against the real match. Illegal ones are dropped."""
    g, m, op = t.game, t.match, msg.get('op')
    try:
        if op in ('play', 'pass') and m.phase == 'play' and not g.over and g.turn == seat:
            if op == 'pass':
                if g.top is not None:
                    t.play(None)
                return
            move = _move(msg['move'])
            if move in g.legal_interpretations(move.cards):
                t.play(move)
        elif op == 'tribute' and m.phase == 'tribute' and m.actor == seat:
            card = next((c for c in g.hands[seat] if c[2] == msg['card']), None)
            if card is not None:
                t.tribute_action(card)
        elif op == 'next':
            if m.phase == 'result':
                t.next_deal()
            elif m.phase == 'match_over':
                t.reset()
    except (KeyError, TypeError, ValueError) as e:
        print(f'seat {seat}: dropped {op}: {e!r}', flush=True)


class Host:
    def __init__(self, table, port=PORT):
        self.t, self.port = table, port
        self.clients = {}  # seat -> (writer, last sent line)

    async def start(self, tailcat=True):
        await asyncio.start_server(self._guest, 'localhost', self.port)
        asyncio.create_task(self._pump())
        if tailcat and tailcat_bin():
            asyncio.create_task(self._tailcat())
        else:
            print(f'hosting on localhost:{self.port} (no tailcat)', flush=True)

    async def _tailcat(self):
        proc = await asyncio.create_subprocess_exec(
            tailcat_bin(), 'serve', str(self.port), stderr=asyncio.subprocess.PIPE)
        try:
            async for line in proc.stderr:
                text = line.decode(errors='replace').strip()
                # "...new address: ADDR" or '...saved key "default": ADDR'
                if m := re.search(r'listening with .*:\s*(\S{40,})$', text):
                    print(f'\nGuests join with:\n  python3 lcd_app.py --join {m.group(1)}\n', flush=True)
                elif text:
                    print('tailcat:', text, flush=True)
        finally:
            if proc.returncode is None:
                proc.terminate()
                await proc.wait()

    async def _guest(self, reader, writer):
        seat = None
        try:
            hello = json.loads(await reader.readline())
        except (ValueError, ConnectionError):
            writer.close()  # not a guest (e.g. a bare port probe)
            return
        try:
            free = [s for s in SEAT_ORDER if s not in self.t.remote]
            want = hello.get('seat')
            seat = want if want in free else (free[0] if free else None)
            if seat is None:
                writer.write(b'{"error": "table full"}\n')
                return
            self.t.remote.add(seat)
            self.clients[seat] = (writer, None)
            print(f'guest joined seat {seat}', flush=True)
            while line := await asyncio.wait_for(reader.readline(), GUEST_TIMEOUT):
                apply_action(self.t, seat, json.loads(line))
        except asyncio.TimeoutError:
            print(f'guest seat {seat}: silent for {GUEST_TIMEOUT}s', flush=True)
        except (ConnectionError, json.JSONDecodeError, asyncio.IncompleteReadError) as e:
            print(f'guest seat {seat}: {e!r}', flush=True)
        finally:
            if seat is not None:
                self.t.remote.discard(seat)
                self.clients.pop(seat, None)
                print(f'guest left seat {seat}; a bot takes over', flush=True)
            writer.close()

    async def _pump(self):
        while True:
            self.t.tick()
            for seat, (writer, last) in list(self.clients.items()):
                line = json.dumps(snapshot(self.t, seat), ensure_ascii=False)
                if line != last:
                    writer.write(line.encode() + b'\n')
                    self.clients[seat] = (writer, line)
            await asyncio.sleep(.05)


class _Mirror:
    """Enough of Match for the renderer and the seat-0 input code."""

    def __init__(self, game, s):
        self.game = game
        self.phase, self.actor = s['phase'], s['actor']
        self.message, self.summary = s['message'], s['summary']
        self.champion, self.levels = s['champion'], s['levels']
        self._eligible = set(s['eligible'])

    def eligible(self):
        return [c for c in self.game.hands[0] if c[2] in self._eligible]


def _mirror_game(s):
    g = PhysicalGame.__new__(PhysicalGame)
    g._rules = _level_rules(s['level'])
    g.hands = [[tuple(c) for c in s['hand']]] + [[None] * n for n in s['counts'][1:]]
    g.turn, g.owner, g.over = s['turn'], s['owner'], s['over']
    g.top = _move(s['top']) if s['top'] else None
    g.finish, g.last, g._passed = s['finish'], s['last'], set()
    return g


class RemoteTable(Table):
    """A guest's Table: same controls and rendering, actions go to the host."""

    def __init__(self, lang='en', send=print):
        self.lang = language(lang)
        self.send = send
        self.visible = False
        self.remote = set()
        self.match = None
        self.status = 'Connecting…'
        self.deal, self.notice, self.last, self.cursor = 0, '', '', 0
        self._key = None
        self.cache = None

    def apply(self, s):
        self.match = _Mirror(_mirror_game(s), s)
        self.notice, self.deal = s['notice'], s['deal']
        key = (s['turn'], s['phase'], s['actor'], s['top'], s['over'], len(s['hand']), s['deal'])
        if key != self._key:
            self._key = key
            self.sync()  # new turn or new cards: drop any half-made selection
        self.cache = None

    def input(self, flags, at):
        if self.match is not None:
            super().input(flags, at)

    def play(self, m):
        self.send({'op': 'pass'} if m is None else {'op': 'play', 'move': _move_json(m)})
        self.sync()

    def tribute_action(self, card=None):
        if card is not None:
            self.send({'op': 'tribute', 'card': card[2]})

    def next_deal(self):
        self.send({'op': 'next'})

    def reset(self, seed=None):
        self.send({'op': 'next'})

    def tick(self):
        pass

    def frame(self):
        if self.match is None:
            if self.cache is None:
                c = Canvas()
                c.text(200, 100, 'GUANDAN', 18, True, align='center')
                c.text(200, 130, self.status, 15, align='center', maxw=360)
                self.cache = c.finish()
            return self.cache
        return super().frame()


async def join(t, addr, seat=None, port=PORT):
    """Connect `t` (a RemoteTable) to a host. `addr` is a tailcat address or tcp:HOST:PORT."""
    outbox = asyncio.Queue()
    t.send = outbox.put_nowait
    if addr.startswith('tcp:'):
        host, _, p = addr[4:].rpartition(':')
        reader, writer = await asyncio.open_connection(host or '127.0.0.1', int(p))
        proc = None
    else:
        proc = await asyncio.create_subprocess_exec(
            tailcat_bin() or 'tailcat', addr, str(port), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
        reader, writer = proc.stdout, proc.stdin
    t.status = 'Waiting for host…'; t.cache = None

    async def pump_out():
        while True:
            writer.write(json.dumps(await outbox.get()).encode() + b'\n')
            await writer.drain()

    async def ping():
        while True:
            await asyncio.sleep(PING)
            outbox.put_nowait({'op': 'ping'})

    outbox.put_nowait({'op': 'hello', 'seat': seat})
    sender, pinger = asyncio.create_task(pump_out()), asyncio.create_task(ping())
    try:
        async for line in reader:
            s = json.loads(line)
            if 'error' in s:
                t.status = s['error']
                break
            t.apply(s)
    finally:
        sender.cancel(); pinger.cancel()
        writer.close()  # EOF lets the host free the seat at once
        if proc and proc.returncode is None:
            try:
                await asyncio.wait_for(proc.wait(), 2)  # let tailcat pass the EOF on
            except asyncio.TimeoutError:
                proc.terminate()
                await proc.wait()
        t.match = None
        if t.status in ('Connecting…', 'Waiting for host…'):
            t.status = 'Disconnected from host'
        t.cache = None
