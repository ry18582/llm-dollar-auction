# How agents decide, and where the numbers came from

Read this before drawing conclusions from a run. Some of what follows is
standard game theory; some of it I made up. This document is about telling you
which is which.

---

## 1. Why it runs without any LLM

Because there is a second implementation of "an agent" that never calls a model:
the **scripted provider** (`providers/mock.py`). It sits behind the same
interface as the Anthropic, OpenAI, and Google adapters —
`complete(system, user) -> Completion` — and returns a decision in the same
`Decision: BID / Reason: … / Confidence: …` format a model would. The engine
cannot tell the difference, which is the point: it lets the entire harness
(rules, logging, metrics, replay, charts, GUI) be built and regression-tested
for free.

### The scripted policy, in full

Each agent has a private **walk-away price** and bids while the next bid sits
under it:

```
walk_away = item_value × (base + sunk_stretch) + noise
bid  if  next_bid < walk_away
exit otherwise
```

**base** — standing disposition, from the agent's traits:

```
heat  = mean(competitiveness, status_sensitivity, loss_aversion)
gap   = heat − rational_discipline

base  = 1.0 + (0.08 × gap   if gap > 0   else 0.04 × gap)
      − 0.02 × reflection
```

So an agent whose escalatory traits outweigh its discipline tolerates a price
above the item's value; a disciplined, reflective one walks away below it.

**sunk_stretch** — the sunk-cost effect. What it has already committed raises
what it will tolerate:

```
sunk_stretch = (loss_aversion / 10) × (committed / item_value) × 0.4
```

The 0.4 coefficient is deliberately **below 1**. The threshold chases the
committed total but never catches it, so escalation converges to a finite price.
At ≥ 1 the agent literally cannot stop and every game ends at the budget cap —
a degenerate run, not an interesting one.

**memory adjustments** — only when the switches are on:

```
cross-game:  base −= (0.06 + 0.010 × reflection) × min(times_burned, 5)
within-game: sunk_stretch ×= max(0.15, 1 − reflection / 12)
```

Cross-game memory is the learning channel — being burned lowers what you'll pay
next time, and reflective agents learn faster from the same evidence.
Within-game memory is the self-awareness channel — watching your own commitment
climb blunts the sunk-cost pull without removing it.

**noise** — a seeded Gaussian, `σ = item_value × 0.08 × (10 − patience) / 10`.
Impatient agents are noisier. Derived from a SHA-256 of
`(seed, agent, round, bid)`, so a run replays identically.

### What this is and is not

It **is** a transparent, tunable stand-in that reproduces the qualitative
phenomenon — escalation past value, sunk-cost persistence, and a winner who
loses money.

It is **not** a model of how an LLM behaves, and not fitted to any human data.
Every coefficient above is one I chose to produce legible behaviour. Findings
from scripted runs are findings about this formula. The open question — the one
worth spending tokens on — is what real models do in the same conditions.

---

## 2. Turn order, and why there are no simultaneous bids

The auction is **strictly sequential**. The engine asks one agent for a
decision, applies it, then asks the next. Two agents bidding "at the same time"
cannot occur: the price quoted to an agent is the live price at the moment it is
asked, and by the time the next agent is asked, any raise has already landed.
There is no tie to break and no race to resolve.

Within a round, agents act in seat order, and **an agent holding the standing
high bid is skipped** — nobody bids against themselves. A round ends when every
active non-leading agent has acted. The auction ends when at most one agent is
still active.

Sequential play removes ties but introduces **positional bias**: seat 1 opens at
the lowest price and is immediately outbid; a later seat watches others commit
first. With a fixed order, seat effect is confounded with persona for the whole
experiment. So `turn_order` has three settings:

| policy | behaviour | use when |
|---|---|---|
| `rotate` *(default)* | seat order rotates one place per game | the normal case — positional bias averages out over repeats |
| `fixed` | roster order every game | you want to study the seat effect itself |
| `shuffle` | seeded shuffle per game | you want position/persona correlation broken faster |

All three are deterministic for a given seed. `rotate` is the default because
leaving a known confound switched on by default would be the wrong bias.

A caveat that rotation does not fix: with an odd interaction between seat count
and rounds, seats are not perfectly balanced unless the number of games is a
multiple of the number of agents. For a clean positional control, use
`repeats = n_agents` (or a multiple).

---

## 3. The trait framework

Six dimensions, each 0–10. **These are my design, not a validated instrument.**
They are chosen because they map onto well-documented behavioural-economics
effects and because they are the smallest set that produces distinguishable
bidding:

| trait | what it does in the policy | grounded in |
|---|---|---|
| `competitiveness` | raises `heat`, so tolerates a higher price | — |
| `loss_aversion` | raises `heat`, and drives `sunk_stretch` | loss aversion (Kahneman & Tversky) |
| `rational_discipline` | lowers the walk-away price toward the item's value | expected-value reasoning |
| `status_sensitivity` | raises `heat` — being seen to fold is costly | social/face-saving motives |
| `reflection` | lowers the threshold, damps sunk cost, speeds learning | System-2 / deliberation |
| `patience` | lowers the noise term | — |

The *effects* are real and documented. The *numbers I assigned to each agent*
are not measurements.

---

## 4. MBTI: what it is here, and what it is not

**Where the 16 codes come from.** MBTI (Myers–Briggs Type Indicator) is a
widely-known personality questionnaire built by Katharine Briggs and Isabel
Myers from Carl Jung's typology. It sorts people on four axes:

| axis | poles | in one line |
|---|---|---|
| **E / I** | Extraversion / Introversion | where attention is directed — outward, or inward |
| **S / N** | Sensing / Intuition | concrete detail, or patterns and possibilities |
| **T / F** | Thinking / Feeling | decisions weighed by logic, or by values and people |
| **J / P** | Judging / Perceiving | preference for closure, or for keeping options open |

Four axes × two poles = the 16 codes (INTJ, ESFP, …).

**Where the trait numbers in this repo come from: me.** There is no published
mapping from MBTI codes to competitiveness or loss-aversion scores, and I did
not derive one. I assigned all six trait values per type by hand, reasoning
informally from the axis descriptions — for example, giving `ESTP` maximum
competitiveness and minimum reflection because "extraverted, sensing,
thinking, perceiving" reads as act-now-and-assess-later. **That is an authored
interpretation, not data.**

**And MBTI itself is contested.** It is popular in workplaces but has a poor
reputation in personality psychology: weak test–retest reliability (people
commonly get a different type on re-testing), and forced binary categories where
the underlying evidence favours continuous traits. Academic work generally
prefers the Big Five / Five-Factor Model, which has far better empirical
support.

**So why use it?** As a *prompt scaffold for behavioural diversity*, not as a
scientific claim. The 16 codes are a convenient, memorable, mutually-distinct
set of personas that produces clearly separable agents and that anyone can
reason about at a glance. Nothing in the harness depends on MBTI being valid.

**How not to read the results.** "ESTP escalates the most" is a fact about the
trait numbers I assigned to the agent labelled ESTP. It is **not** evidence
about people of that type, and not evidence that MBTI predicts bidding. If you
want a defensible personality axis, swap the roster for Big Five profiles —
the roster is just a directory of JSON files, and nothing else changes.

The archetype roster (`Rational_Economist`, `Ego_Defender`,
`Sunk_Cost_Escalator`, `Reflective_Strategist`) is the more honest option for a
behavioural claim: it names the mechanism being tested rather than borrowing a
personality taxonomy to stand in for it.
