# Pocket Guandan

A four-player partnership card game for the **400 × 240 monochrome LCD on a Lapis device**. You and the bot across the table play against two other bots. Your 27 cards fan out by rank, with matching cards stacked vertically so you can see each suit. Once a card reaches the table, it stays spread out beside the name of the player who played it.

[中文说明](docs/README.zh-CN.md) · [Match rules](MATCH_RULES.md)

## Demo

![Animated gameplay: selecting cards from a vertical stack, playing the pair, and watching the next seat respond](docs/media/pocket-guandan-demo.gif)

The demo uses the game's English LCD renderer and a seeded deal. It shows the pixels the app draws, not a camera recording of the device.

| Two 7s selected from one stack | Choosing what the heart wildcard represents |
| :---: | :---: |
| [![Two physical sevens lifted from their stack](docs/media/stacked-hand.png)](docs/media/stacked-hand.png) | [![An ambiguous full house with two possible interpretations](docs/media/wildcard-choice.png)](docs/media/wildcard-choice.png) |

## Run on Lapis

On a Lapis device with mini-app windows and fingerprint gestures enabled:

```sh
gh repo clone TianqiYe/pocket-guandan
cd pocket-guandan
python3 lcd_app.py
```

English is the default. For Chinese, run `python3 lcd_app.py --lang zh`. Keep the process running while you play. In the app switcher, look for **Guandan Hard** (or **Guandan Hand** in Classic mode). Switching away pauses play; exiting the process ends the match.

The app needs Python 3.10+, `dbus_fast`, system Cairo (`libcairo.so.2`), a suitable font (Noto Sans CJK SC for Chinese), and an account permitted to open Lapis display windows. The LCD launcher is device-specific; it isn't a desktop or browser game.

## Multiplayer

One Lapis hosts; up to three others take over bot seats over [tailcat](https://github.com/tailscale/tailcat). Lapis doesn't ship the `tailcat` CLI, so put a Linux arm64 build at `bin/tailcat` on each device (or anywhere on `PATH`).

```sh
python3 lcd_app.py --host                  # prints: python3 lcd_app.py --join <addr>
python3 lcd_app.py --join <addr>           # first guest plays against the host
python3 lcd_app.py --join <addr> --seat 1  # or pick a seat: 1 Right, 2 Partner, 3 Left
```

The host's device runs the match and checks every move; each guest only receives its own hand. Each human's bot partner plays Classic, so two humans get equal partners. A guest who disconnects is replaced by a bot and can rejoin. While guests are connected, the match keeps running when the host switches away. For LAN or local testing, use `--host --no-tailcat` and `--join tcp:HOST:7777`.

## Opponent difficulty

**Hard** is the default for the two opponents. Your partner keeps the original Classic policy in both modes. The deal, level rules, tribute, and legal moves are identical; difficulty does not change the cards. To play the previous version's opponents, use:

```sh
python3 lcd_app.py --difficulty classic
```

Hard scores each play by the shape of its remaining hand, avoids cheap last-card leads to an opponent, and looks for low leads to a nearly-out partner. It gets only its own hand, legal options, the table play and public remaining counts (above ten is just “more than ten”).

On 104 duplicate deals across levels 2–A (208 rounds), Hard took first place 130 times (62.5%) versus 78 for Classic, with 71 vs. 36 partnership sweeps. Reproduce with `python3 tools/bench_ai.py --deals 104 --seed 10000`. Each physical deal is played twice with the teams swapped. The benchmark reports first-outs and 1–2 finishes, not an estimated win rate against people.

## Your first turn

| Control | Action |
| --- | --- |
| Swipe left / right | Move to another rank stack. The heart wildcard has its own stack. |
| Tap the fingerprint pad | Move to the next physical card in the stack to pick a particular suit. |
| Swipe up / down | Add one card from this stack to your selection / remove one. |
| Short-press A | Play the selection. With nothing selected, pass if another play is on the table. |
| Hold A, then release | When a selection has several legal meanings, cycle through them without playing. Short-press A to confirm. |
| B | Open the system app switcher. |

For example, move to the 7s and swipe up twice for a pair. To choose a particular 7 first, tap until its corner is marked, then swipe up. Selected cards are inverted. The highlighted seat shows whose turn it is; the label beside the played cards shows **who played them**, even after someone passes.

A match starts at level 2 and includes promotion, heart wildcards, tribute, and returns. Press **A** on the result screen to continue to the next deal. [See the rules and house conventions.](MATCH_RULES.md)

## Development

Run `python3 -m unittest discover -v`. Rules tests don't need an LCD; frame-rendering tests use Cairo. Regenerate the demo with `python3 tools/render_demo.py` (requires FFmpeg).

Known input issue: some fingerprint pads report both a tap and an upward swipe for one motion. A swipe-first debounce has been discussed but isn't implemented in this version.
