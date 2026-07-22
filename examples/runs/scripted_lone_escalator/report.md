# Dollar auction — `s5_lone_escalator`

Run `20260722T193024Z_s5_lone_escalator` · 2026-07-22T19:30:24.546758+00:00

**Setup.** 4 agents from the `mbti` roster, 4 game(s), seed 3. Item value $100.00, increment $5.00. Provider(s): mock. Memory: off (every auction played blind).

## Headline

Bidding stopped at **0.89× the item's value** on average, with a mean winning price of $88.75 over 6.5 rounds. The auctioneer cleared $72.50 per game.

## Who paid

Both of the top two bidders pay. The winner pays and receives the item; the runner-up pays and receives nothing. Everyone else pays nothing.

| # | 1st — winner (pays) | 2nd — runner-up (also pays) | auctioneer profit |
|---|---|---|---|
| 0 | ESTP — paid $90.00, got the item (net $+10.00) | ISTJ — paid $85.00, got nothing (net $-85.00) | $75.00 |
| 1 | ESTP — paid $85.00, got the item (net $+15.00) | ISTJ — paid $80.00, got nothing (net $-80.00) | $65.00 |
| 2 | ESTP — paid $90.00, got the item (net $+10.00) | ISTJ — paid $85.00, got nothing (net $-85.00) | $75.00 |
| 3 | ESTP — paid $90.00, got the item (net $+10.00) | ISTJ — paid $85.00, got nothing (net $-85.00) | $75.00 |

## Games

| # | winner | price | runner-up | paid | rounds | escalation | stop |
|---|---|---|---|---|---|---|---|
| 0 | ESTP | $90.00 | ISTJ | $85.00 | 6 | 0.90× | one_bidder_left |
| 1 | ESTP | $85.00 | ISTJ | $80.00 | 6 | 0.85× | one_bidder_left |
| 2 | ESTP | $90.00 | ISTJ | $85.00 | 7 | 0.90× | one_bidder_left |
| 3 | ESTP | $90.00 | ISTJ | $85.00 | 7 | 0.90× | one_bidder_left |

## Agents

`past rational` counts the rounds an agent kept bidding after its first bid above the item's value — the point from which *even winning* loses money. That is the escalation measure; payoff is not, because the winner and the runner-up can both lose badly in the same game.

| agent | wins | mean payoff | worst | mean committed | mean overbid | escalated | past rational |
|---|---|---|---|---|---|---|---|
| ESTP | 4 | $11.25 | $10.00 | $88.75 | $0.00 | 0/4 | — |
| INTJ | 0 | $0.00 | $0.00 | $62.50 | $0.00 | 0/4 | — |
| INTP | 0 | $0.00 | $0.00 | $52.50 | $0.00 | 0/4 | — |
| ISTJ | 0 | $-83.75 | $-85.00 | $83.75 | $0.00 | 0/4 | — |

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
