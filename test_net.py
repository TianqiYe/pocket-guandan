import asyncio
import json
import unittest
from unittest.mock import patch

import net
from pocket import Table


class FastClock:
    now = 0.

    def monotonic(self):
        self.now += 2.
        return self.now


class RotateText(unittest.TestCase):
    def test_seats_and_teams(self):
        self.assertEqual(net.rotate_text('单贡 · 下家选贡牌', 2), '单贡 · 上家选贡牌')
        self.assertEqual(net.rotate_text('首局打2 · 你先出', 2), '首局打2 · 队友先出')
        self.assertEqual(net.rotate_text('头游：上家 · 队友第3 · 我方 2→4', 1),
                         '头游：队友 · 队友第3 · 对方 2→4')


class Snapshot(unittest.TestCase):
    def test_only_own_hand_is_sent(self):
        t = Table(3)
        s = net.snapshot(t, 2)
        self.assertEqual([tuple(c) for c in s['hand']], t.game.hands[2])
        self.assertEqual(s['counts'], [27, 11, 11, 11])
        self.assertEqual(s['turn'], 2)  # host (seat 0) leads; that's 'Partner' for seat 2
        self.assertNotIn(str(list(t.game.hands[0][0])), str({k: v for k, v in s.items() if k != 'hand'}))

    def test_wire_counts_at_threshold_from_each_seat(self):
        for counts in ((27, 14, 11, 10), (9, 0, 20, 1)):
            t = Table(3)
            t.game.hands = [h[:n] for h, n in zip(t.game.hands, counts)]
            for seat in (1, 2, 3):
                with self.subTest(counts=counts, seat=seat):
                    snap = json.loads(json.dumps(net.snapshot(t, seat)))
                    expected = [counts[seat]] + [min(counts[(seat+i)%4], 11) for i in (1, 2, 3)]
                    self.assertEqual(snap['counts'], expected)
                    self.assertEqual(list(map(len, net._mirror_game(snap).hands)), expected)

    def test_forged_move_is_dropped(self):
        t = Table(3)
        t.remote.add(2)
        t.game.turn = 2
        mine = t.game.hands[2][0]
        foreign = t.game.hands[0][0]
        legal = t.game.legal_interpretations([mine])[0]
        forged = net._move_json(legal)
        forged['cards'] = [list(foreign)]
        net.apply_action(t, 2, {'op': 'play', 'move': forged})
        self.assertEqual(len(t.game.hands[2]), 27)
        net.apply_action(t, 1, {'op': 'play', 'move': net._move_json(legal)})  # not seat 1's turn
        self.assertEqual(len(t.game.hands[2]), 27)
        net.apply_action(t, 2, {'op': 'play', 'move': net._move_json(legal)})
        self.assertEqual(len(t.game.hands[2]), 26)


class Seating(unittest.TestCase):
    def test_bot_partners_match_for_two_humans(self):
        t = Table(3, difficulty='hard')
        self.assertEqual([t.bot_difficulty(s) for s in (1, 2, 3)], ['hard', 'classic', 'hard'])
        t.remote.add(net.SEAT_ORDER[0])
        self.assertEqual(net.SEAT_ORDER[0] % 2, 1)  # first guest is an opponent
        self.assertEqual(t.bot_difficulty(2), t.bot_difficulty(3))


class SilentGuest(unittest.TestCase):
    def test_seat_freed_after_timeout(self):
        async def run():
            t = Table(1)
            host = net.Host(t, port=0)
            server = await asyncio.start_server(host._guest, '127.0.0.1', 0)
            _, w = await asyncio.open_connection('127.0.0.1', server.sockets[0].getsockname()[1])
            w.write(b'{"op": "hello"}\n')
            for _ in range(50):
                await asyncio.sleep(.02)
                if t.remote: break
            self.assertEqual(t.remote, {1})
            await asyncio.sleep(.5)  # connection stays open but says nothing
            self.assertEqual(t.remote, set())
            w.close(); server.close()
        with patch.object(net, 'GUEST_TIMEOUT', .2):
            asyncio.run(run())


class FullMatch(unittest.TestCase):
    def test_host_and_two_guests(self):
        with patch('pocket.time', FastClock()):
            asyncio.run(asyncio.wait_for(self._play(), 60))

    async def _play(self):
        host_table = Table(11, difficulty='hard')
        host = net.Host(host_table, port=0)
        server = await asyncio.start_server(host._guest, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        guests = {2: net.RemoteTable('en'), 1: net.RemoteTable('zh')}
        tasks = [asyncio.create_task(net.join(g, f'tcp:127.0.0.1:{port}', seat)) for seat, g in guests.items()]
        while len(host.clients) < 2:
            await asyncio.sleep(.01)
        self.assertEqual(host_table.remote, {1, 2})
        frames = 0
        while host_table.deal < 4 and host_table.match.phase != 'match_over':
            t = host_table
            t.tick()
            for seat, (w, last) in list(host.clients.items()):
                line = json.dumps(net.snapshot(t, seat), ensure_ascii=False)
                if line != last:
                    w.write(line.encode() + b'\n')
                    host.clients[seat] = (w, line)
            m = t.match
            if m.actor == 0:  # drive the host's own seat with the bot
                if m.phase == 'tribute':
                    t.tribute_action()
                else:
                    t.play(t.game.bot_move('classic'))
            elif m.phase == 'result' and t.deal % 2:
                t.next_deal()
            for seat, g in guests.items():
                if g.match is None:
                    continue
                if g.match.phase == 'result' and t.deal % 2 == 0 and m.phase == 'result':
                    g.next_deal()
                if g.human_turn and m.actor == seat and not getattr(g, '_sent', None) == g._key:
                    # Choose with the host's bot, but declare through the guest's mirror.
                    want = t.game.bot_move('classic')
                    if want is None:
                        g.play(None)
                    else:
                        options = g.game.legal_interpretations(want.cards)
                        self.assertIn(want, options)
                        g.play(want)
                    g._sent = g._key
                elif g.match.phase == 'tribute' and g.match.actor == 0 and g._sent != g._key:
                    g.tribute_action(g.match.eligible()[0])
                    g._sent = g._key
                if frames % 25 == 0:
                    self.assertEqual(len(g.frame()), 12000)
            frames += 1
            await asyncio.sleep(.002)
        self.assertGreaterEqual(host_table.deal, 2)
        for g in guests.values():
            self.assertEqual(len(g.frame()), 12000)
        server.close()
        for task in tasks:
            task.cancel()


if __name__ == '__main__':
    unittest.main()
