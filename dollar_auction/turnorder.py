"""Who bids first, and why it matters.

The auction is **strictly sequential**: agents act one at a time in a fixed
round-robin, and there is no such thing as two agents bidding at once. The
engine asks one agent for a decision, applies it, then asks the next. So a
"simultaneous bid" collision cannot occur — the price an agent is quoted is
always the live price at the moment it is asked, and by the time the next agent
is asked, that raise has already landed.

That design removes one problem and creates another. **Turn position is not
neutral.** Going first means being the one who opens at the lowest price and
being outbid immediately; going last in a round means watching everyone else
commit before you choose. With a fixed order, that positional effect is
confounded with the agent's persona for the entire experiment — agent A always
gets seat 1, so you cannot tell a trait effect from a seat effect.

Hence three policies:

    rotate   (default) seat order rotates by one each game, so over N games an
             agent occupies N different seats. Positional bias averages out
             across repeats while any single game stays perfectly reproducible.
    fixed    roster order, every game. Use when you deliberately want to study
             the seat effect itself.
    shuffle  seeded shuffle per game. Breaks position/persona correlation
             faster than rotation, at the cost of an order you can predict by
             eye. Still fully deterministic for a given seed.

`rotate` is the default because a repeated experiment is the normal case, and
leaving a known confound switched on by default would be the wrong bias.
"""

from __future__ import annotations

import hashlib
import random

POLICIES = ("rotate", "fixed", "shuffle")


def _stable_seed(*parts) -> int:
    """A seed that survives process restarts.

    Python's built-in hash() is randomized per process for str, so using it
    here would make `shuffle` reproducible within one run and different on the
    next — which would quietly break replay.
    """
    key = "|".join(str(p) for p in parts).encode()
    return int(hashlib.sha256(key).hexdigest()[:16], 16)


def order_for_game(
    names: list[str], *, policy: str = "rotate", game_index: int = 0, seed: int = 0
) -> list[str]:
    """Seat order for one game. Deterministic given (names, policy, index, seed)."""
    if policy not in POLICIES:
        raise ValueError(f"unknown turn_order {policy!r}; expected one of {POLICIES}")

    if not names:
        return []

    if policy == "fixed":
        return list(names)

    if policy == "rotate":
        shift = game_index % len(names)
        return list(names[shift:]) + list(names[:shift])

    order = list(names)
    random.Random(_stable_seed(seed, game_index, *names)).shuffle(order)
    return order
