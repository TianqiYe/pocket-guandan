"""Physical-card selection and foreground-only controls for Pocket Guandan."""
import time
from matchplay import Match
from ui_text import language

SEATS = ('你','下家','队友','上家')


class Table:
    def __init__(self, seed=None, lang='en', difficulty='hard'):
        if difficulty not in ('classic','hard'):raise ValueError('unknown bot difficulty')
        self.difficulty=difficulty
        self.lang = language(lang)
        self.visible = False
        self.remote = set()  # seats held by network guests
        self.deal = 0
        self.reset(seed)

    def reset(self, seed=None):
        self.match = Match(seed)
        self.deal = 1
        self.notice = ''
        self.last = '自由领出'
        self.cursor = 0
        self.sync()

    @property
    def game(self): return self.match.game

    @property
    def hand(self): return self.game.hands[0]

    @property
    def top_cards(self): return list(self.game.top.cards) if self.game.top else []

    @property
    def human_turn(self): return self.match.phase == 'play' and not self.game.over and self.game.turn == 0

    def sync(self):
        self.pick_order = []
        self.motion = {}
        self.motion_key = None
        self.selected = set()
        self.meanings = []
        self.mode = 0
        self.feedback = ''
        self.tribute_selected = None
        self.eligible_ids = {c[2] for c in self.match.eligible()} if self.match.phase == 'tribute' and self.match.actor == 0 else set()
        self.cursor = min(self.cursor,max(0,len(self.hand)-1))
        if self.eligible_ids:
            self.cursor = next(i for i,c in enumerate(self.hand) if c[2] in self.eligible_ids)
        self.until = time.monotonic()+(2.2 if self.notice else 1.05)
        self.clear_input()
        self.cache = None

    def clear_input(self):
        self.a = False
        self.a_start = None
        self.fp_down = False
        self.block_tap_until = 0

    def focus(self,on):
        self.visible = on
        self.clear_input()
        self.until = time.monotonic()+1.05

    def choice(self): return self.meanings[self.mode] if self.meanings else None

    @property
    def alternatives(self): return len(self.meanings)

    @property
    def meaning_label(self):
        m = self.choice()
        return m.label if m else ''

    def piles(self):
        groups = {}
        for i,(rank,suit,_) in enumerate(self.hand):
            key = (rank, rank == self.game.level and suit == '♥')
            groups.setdefault(key, []).append(i)
        # Keep the active heart wild outside the natural level-rank pile.
        wilds = groups.pop((self.game.level, True), None)
        return list(groups.values()) + ([wilds] if wilds else [])

    def pile_gesture(self, code):
        piles = self.piles()
        if not piles: return
        k = next(i for i,g in enumerate(piles) if self.cursor in g)
        group = piles[k]
        if code in (7,8):
            group = piles[(k + (1 if code==8 else -1)) % len(piles)]
            self.cursor = next((i for i in group if self.hand[i][2] not in self.selected),group[0])
        elif code == 9:
            self.cursor = group[(group.index(self.cursor)+1) % len(group)]
        elif code == 5:
            j=group.index(self.cursor)
            target=next((i for i in group[j:]+group[:j] if self.hand[i][2] not in self.selected),None)
            if target is not None:
                self.cursor=target; self.select(True)
                j=group.index(target)+1
                self.cursor=next((i for i in group[j:]+group[:j] if self.hand[i][2] not in self.selected),target)
        elif code == 6:
            # Remove the indicated card if selected, otherwise undo the latest pick in this pile.
            ids={self.hand[i][2]:i for i in group}
            uid=self.hand[self.cursor][2]
            if uid not in self.selected:uid=next((u for u in reversed(self.pick_order) if u in ids),None)
            if uid is not None:self.cursor=ids[uid];self.select(False)
        self.cache=None

    def select(self, add):
        card_id = self.hand[self.cursor][2]
        if (card_id in self.selected) == add: return
        now = time.monotonic()
        start = self.lift(card_id, not add)
        self.motion[card_id] = (now, start, 5 if add else 0)
        if add: self.selected.add(card_id); self.pick_order.append(card_id)
        else: self.selected.remove(card_id); self.pick_order.remove(card_id)
        picked = [c for c in self.hand if c[2] in self.selected]
        self.meanings = self.game.legal_interpretations(picked) if picked else []
        self.mode = 0
        self.cache = None

    def lift(self, card_id, selected):
        item = self.motion.get(card_id)
        if not item: return 5 if selected else 0
        at, start, target = item
        # A short ease-out in whole LCD pixels, no dithering or idle animation.
        t = min(1.,max(0.,(time.monotonic()-at)/.105))
        return round(start+(target-start)*(1-(1-t)**2))

    def next_deal(self):
        self.match.advance()
        self.deal += 1
        self.notice = self.match.message if self.match.phase == 'play' else ''
        self.cursor = 0
        self.last = ''
        self.sync()

    def tribute_action(self, card=None):
        if card is None: self.match.auto()
        else: self.match.give(card)
        if self.match.phase == 'play': self.notice = self.match.message
        self.sync()

    def tribute_input(self, code):
        if self.match.actor != 0: return
        if code == 1: self.a = True; return
        if code == 2:
            if not self.a: return
            self.a = False
            card = next((c for c in self.hand if c[2]==self.tribute_selected),None)
            if card is not None: self.tribute_action(card)
            else: self.feedback='上滑选牌'; self.cache=None
            return
        if self.a: return
        if code in (7,8):
            indices = [i for i,c in enumerate(self.hand) if c[2] in self.eligible_ids]
            i = indices.index(self.cursor) if self.cursor in indices else 0
            self.cursor = indices[(i+(1 if code==8 else -1))%len(indices)]
        elif code == 5: self.tribute_selected = self.hand[self.cursor][2]
        elif code == 6: self.tribute_selected = None
        else: return
        self.feedback=''; self.cache=None

    def input(self, flags, at):
        code = flags & 255
        if not self.visible or flags & 256:
            self.clear_input(); return
        if self.match.phase == 'tribute':
            self.tribute_input(code); return
        if code == 1:
            self.a = self.human_turn or self.game.over
            self.a_start = at if self.a else None
            return
        if code == 2:
            if not self.a: return
            self.a = False
            if self.match.phase == 'match_over': self.reset(); return
            if self.match.phase == 'result': self.next_deal(); return
            if self.alternatives > 1 and self.a_start is not None and at - self.a_start >= .55:
                self.mode=(self.mode+1)%self.alternatives;self.cache=None;return
            m = self.choice()
            if m is not None: self.play(m)
            elif not self.selected and self.game.top is not None: self.play(None)
            else:
                self.feedback = '请先选牌' if not self.selected else '不能这样出'
                self.cache = None
            return
        if not self.human_turn or self.a: return
        if code in (5,6,7,8):
            self.block_tap_until = at + .20
            self.fp_down = False
            self.feedback = ''; self.cache = None
            self.pile_gesture(code)
        # On some firmware a light tap is reported as a fingerprint button click.
        # Accept either form once; do not turn a swipe's trailing tap into a cycle.
        elif code == 3: self.fp_down = True
        elif code == 9 or (code == 4 and self.fp_down):
            self.fp_down = False
            if at >= self.block_tap_until:
                self.pile_gesture(9)
                self.block_tap_until = at+.38
                self.cache = None

    def play(self,m):
        seat = self.game.turn
        self.game.play(m)
        self.notice = ''
        if self.game.over: self.match.settle()
        self.last = SEATS[seat]+'：'+(m.label if m else '过')
        self.sync()

    def tick(self):
        # With guests connected the match keeps running while this window is hidden.
        if not (self.visible or self.remote) or time.monotonic()<self.until: return
        actor = self.match.actor
        if actor is None or actor == 0 or actor in self.remote: return
        if self.match.phase == 'tribute': self.tribute_action()
        else: self.play(self.game.bot_move(self.bot_difficulty(actor)))

    def bot_difficulty(self, seat):
        """A human's bot partner plays Classic, so two humans get equal partners."""
        return 'classic' if (seat + 2) % 4 in {0} | self.remote else self.difficulty

    def frame(self):
        from hand_view import render
        if self.motion:
            now=time.monotonic()
            k=tuple((uid,self.lift(uid,uid in self.selected)) for uid in self.motion)
            if k!=self.motion_key: self.cache=None
            self.motion_key=k
            self.motion={uid:val for uid,val in self.motion.items() if now-val[0]<.105}
        if self.cache is None: self.cache=render(self)
        return self.cache
