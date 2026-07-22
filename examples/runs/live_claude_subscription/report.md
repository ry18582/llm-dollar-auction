# Dollar auction — `s0_smoke_subscription`

Run `20260722T185336Z_s0_smoke_subscription` · 2026-07-22T18:53:36.828197+00:00

**Setup.** 2 agents from the `mbti` roster, 1 game(s), seed 7. Item value $100.00, increment $50.00. Provider(s): cli. Memory: within_game.

## Headline

Bidding stopped at **0.50× the item's value** on average, with a mean winning price of $50.00 over 1.0 rounds. The auctioneer cleared $-50.00 per game.

## Who paid

Both of the top two bidders pay. The winner pays and receives the item; the runner-up pays and receives nothing. Everyone else pays nothing.

| # | 1st — winner (pays) | 2nd — runner-up (also pays) | auctioneer profit |
|---|---|---|---|
| 0 | ESTP — paid $50.00, got the item (net $+50.00) | None — paid $0.00, got nothing (net $-0.00) | $-50.00 |

## Games

| # | winner | price | runner-up | paid | rounds | escalation | stop |
|---|---|---|---|---|---|---|---|
| 0 | ESTP | $50.00 | — | $0.00 | 1 | 0.50× | one_bidder_left |

## Agents

`past rational` counts the rounds an agent kept bidding after its first bid above the item's value — the point from which *even winning* loses money. That is the escalation measure; payoff is not, because the winner and the runner-up can both lose badly in the same game.

| agent | wins | mean payoff | worst | mean committed | mean overbid | escalated | past rational |
|---|---|---|---|---|---|---|---|
| ESTP | 1 | $50.00 | $50.00 | $50.00 | $0.00 | 0/1 | — |
| INTJ | 0 | $0.00 | $0.00 | $0.00 | $0.00 | 0/1 | — |

## Run health

- Tokens: 0 in / 0 out
- Forced actions (budget, cap, parse failure, provider error): 0
- Parse retries: 0
- Errors: 0


## Artifacts

- `escalation.svg` — bid trajectories against the item's value
- `payoffs.svg` — final payoff per agent
- `game_*.jsonl` — full event log (every decision, reason, confidence, token count)
- `metrics.json` — every number in this report
- `manifest.json` — exact configs and seed used
