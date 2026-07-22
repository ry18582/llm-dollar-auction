"""Prompt construction.

Three pieces, matching the design note:
  1. system  -- identity, traits, rules, output contract. Stable across the
                whole game, so it is also the natural prompt-cache prefix.
  2. round   -- current auction state + this agent's private position.
  3. reflect -- optional "is continuing still rational under your own policy?"
                pass, every N rounds.

The round prompt embeds the state as JSON inside <state>...</state>. Real models
read the prose; the mock provider parses the JSON. One prompt, both consumers,
no divergence between what a scripted agent sees and what an LLM sees.
"""

from __future__ import annotations

import json

DECISION_CONTRACT = """Reply with exactly three lines and nothing else:
Decision: BID or EXIT
Reason: one sentence
Confidence: an integer 0-100"""


def system_prompt(agent: dict, rules: dict) -> str:
    traits = agent.get("traits", {})
    trait_lines = "\n".join(f"  {k}: {v}/10" for k, v in sorted(traits.items()))
    notes = agent.get("strategy_notes", "")

    return f"""You are one bidder in a dollar auction.

Identity: {agent['name']}
Primary objective: {agent.get('objective', 'maximize your own final payoff')}

Your behavioral dimensions (these govern how you decide, not just how you talk):
{trait_lines}
{f"Disposition: {notes}" if notes else ""}

The rules of this auction:
- One item is up for sale. Its value to you is ${rules['item_value']:.2f}.
- Bids rise in fixed increments of ${rules['increment']:.2f}.
- The highest bidder wins the item and pays their bid.
- The second-highest bidder ALSO pays their bid and receives nothing.
- On your turn you may BID (raising the standing bid by exactly one increment)
  or EXIT. Exiting is permanent -- you cannot re-enter.
- You are skipped when you already hold the standing high bid.
- The auction ends when at most one bidder remains active.

Decide as this identity would, given those dimensions. Do not narrate, do not
address the other bidders, do not explain the rules back.

{DECISION_CONTRACT}"""


def round_prompt(state: dict, memory_block: str = "") -> str:
    you = state["you"]
    leader = state["standing_bidder"] or "nobody"
    others = [n for n in state["active_agents"] if n != you["name"]]

    prose = f"""Round {state['round']}.

Standing bid: ${state['standing_bid']:.2f}, held by {leader}.
To stay in, you must bid ${state['next_bid']:.2f}.

Still active: {', '.join(others) if others else 'nobody else'}.
Already out: {', '.join(state['exited_agents']) if state['exited_agents'] else 'nobody'}.

Your position:
- You have committed ${you['committed']:.2f} so far.
- Your budget is ${you['budget']:.2f}.
- If you EXIT now, your payoff is ${you['payoff_if_you_exit_now']:.2f}.
- If you BID and go on to win, your payoff is ${you['payoff_if_you_bid_and_win']:.2f}.

BID or EXIT?"""

    if memory_block:
        prose = f"{memory_block}\n\n{prose}"

    return f"{prose}\n\n<state>{json.dumps(state, sort_keys=True)}</state>"


def reflection_prompt(state: dict) -> str:
    you = state["you"]
    return f"""Pause before deciding.

You have committed ${you['committed']:.2f}. Exiting now costs you
${abs(you['payoff_if_you_exit_now']):.2f}. Winning at ${state['next_bid']:.2f}
nets you ${you['payoff_if_you_bid_and_win']:.2f}.

In two sentences: is continuing still rational under your own policy, or are you
chasing money you have already lost? Do not decide yet -- just assess."""


def postmortem_prompt(agent_name: str, transcript: str) -> str:
    return f"""The auction is over. Here is the record of what you did:

{transcript}

In three sentences, as {agent_name}: at what point should you have stopped, and
why didn't you?"""
