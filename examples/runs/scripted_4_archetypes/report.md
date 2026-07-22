# Dollar auction — `mvp_mock`

Run `20260722T193024Z_mvp_mock` · 2026-07-22T19:30:24.222296+00:00

**Setup.** 4 agents from the `archetypes` roster, 5 game(s), seed 7. Item value $100.00, increment $5.00. Provider(s): mock. Memory: off (every auction played blind).

## Headline

Bidding ran **1.89× past the item's value** on average, with a mean winning price of $189.00 over 16.4 rounds. The auctioneer cleared $273.00 per game.

## Who paid

Both of the top two bidders pay. The winner pays and receives the item; the runner-up pays and receives nothing. Everyone else pays nothing.

| # | 1st — winner (pays) | 2nd — runner-up (also pays) | auctioneer profit |
|---|---|---|---|
| 0 | Sunk_Cost_Escalator — paid $185.00, got the item (net $-85.00) | Ego_Defender — paid $180.00, got nothing (net $-180.00) | $265.00 |
| 1 | Sunk_Cost_Escalator — paid $190.00, got the item (net $-90.00) | Ego_Defender — paid $185.00, got nothing (net $-185.00) | $275.00 |
| 2 | Sunk_Cost_Escalator — paid $190.00, got the item (net $-90.00) | Ego_Defender — paid $185.00, got nothing (net $-185.00) | $275.00 |
| 3 | Sunk_Cost_Escalator — paid $195.00, got the item (net $-95.00) | Ego_Defender — paid $190.00, got nothing (net $-190.00) | $285.00 |
| 4 | Sunk_Cost_Escalator — paid $185.00, got the item (net $-85.00) | Ego_Defender — paid $180.00, got nothing (net $-180.00) | $265.00 |

## Games

| # | winner | price | runner-up | paid | rounds | escalation | stop |
|---|---|---|---|---|---|---|---|
| 0 | Sunk_Cost_Escalator | $185.00 | Ego_Defender | $180.00 | 16 | 1.85× | one_bidder_left |
| 1 | Sunk_Cost_Escalator | $190.00 | Ego_Defender | $185.00 | 17 | 1.90× | one_bidder_left |
| 2 | Sunk_Cost_Escalator | $190.00 | Ego_Defender | $185.00 | 16 | 1.90× | one_bidder_left |
| 3 | Sunk_Cost_Escalator | $195.00 | Ego_Defender | $190.00 | 17 | 1.95× | one_bidder_left |
| 4 | Sunk_Cost_Escalator | $185.00 | Ego_Defender | $180.00 | 16 | 1.85× | one_bidder_left |

## Agents

`past rational` counts the rounds an agent kept bidding after its first bid above the item's value — the point from which *even winning* loses money. That is the escalation measure; payoff is not, because the winner and the runner-up can both lose badly in the same game.

| agent | wins | mean payoff | worst | mean committed | mean overbid | escalated | past rational |
|---|---|---|---|---|---|---|---|
| Rational_Economist | 0 | $0.00 | $0.00 | $47.00 | $0.00 | 0/5 | — |
| Reflective_Strategist | 0 | $0.00 | $0.00 | $71.00 | $0.00 | 0/5 | — |
| Sunk_Cost_Escalator | 5 | $-89.00 | $-95.00 | $189.00 | $89.00 | 5/5 | 9 |
| Ego_Defender | 0 | $-184.00 | $-190.00 | $184.00 | $84.00 | 5/5 | 8.60 |

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
