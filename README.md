# LLM Dollar Auction

**Do language models fall into the dollar-auction trap? Does it depend on their
personality, or on what they remember?**

An item worth $100 is auctioned in $5 steps. The highest bidder wins it and pays.
**The catch: the second-highest bidder also pays — and gets nothing.**

That one rule turns an auction into a trap. Once you are about to be outbid,
paying $5 more is *locally rational* — walking away costs you everything you have
already committed, while one more bid might still win. So bidding runs past $100
and the winner loses money too. Humans fall for this reliably. This is a harness
for asking whether LLMs do, and what changes it.

```
winner: Sunk_Cost_Escalator at $185.00
runner-up: Ego_Defender paid $180.00

payoffs:
  Rational_Economist     $+0.00
  Reflective_Strategist  $+0.00
  Sunk_Cost_Escalator    $-85.00      <- the winner
  Ego_Defender          $-180.00
```

An item worth $100 sold for $185, the auctioneer cleared $265, and *the winner
lost money*.

---

## Try it in 60 seconds — no install, no API key

Requires **Python 3.10+ and nothing else.** No pip, no dependencies.

```bash
git clone https://github.com/ry18582/llm-dollar-auction
cd llm-dollar-auction

python3 -m dollar_auction gui
```

It asks which port to use, showing which are free — press Enter to accept the
suggestion, or pass `--port 9000` to skip the question. Then open the URL it
prints (`http://127.0.0.1:8765` by default). Pick a scenario, press
**Run**, and watch bids land one at a time.

Prefer the terminal?

```bash
python3 -m dollar_auction run configs/experiments/mvp_mock.json
python3 -m dollar_auction replay      # the full transcript
python3 -m dollar_auction verify      # prove it replays exactly
```

### Or read a run someone else already did

`examples/runs/` holds finished runs — transcripts, metrics, charts — so you can
see the output before running anything:

| Example | What it shows |
|---|---|
| `scripted_4_archetypes` | The trap springing: a $100 item sells for $189 |
| `scripted_lone_escalator` | One escalator against three disciplined agents — stops at 0.89× value |
| `live_claude_subscription` | A real Claude game, with the models' actual reasoning |

---

## What you are looking at in the GUI

| Panel | What it does |
|---|---|
| **Scenario** | Pre-built experiments. Start here — these are the questions the project was built to ask. |
| **Custom setup** | Build your own: which agents, which model backend, item value, increment, number of games, random seed. |
| **Memory** | Whether agents remember, in what form, and how far back. |
| **Playback** | How fast decisions replay on screen. Does not change the run itself. |
| **Who pays right now** | The two bidders on the hook — the winner *and* the runner-up who gets nothing. |
| **Bidding chart** | Bid trajectories. The dashed line is the item's value: above it, even winning loses money. |
| **Bidders** | One card per agent: what it has committed, and the reason it gave for its last decision. |
| **Results** | Per-game outcomes and per-agent aggregates once the run finishes. |
| **Event log** | Every decision as it happens, with the agent's stated reasoning. |

---

## Running against real models

Three ways, in order of how little setup they need.

### 1. Subscription or account sign-in — no API key

Each provider ships an official CLI authorised to use your plan. Sign in once:

| CLI | Install | Uses |
|---|---|---|
| `claude` | <https://claude.com/code> | Claude **Pro / Max** |
| `gemini` | `npm i -g @google/gemini-cli`, run `gemini`, sign in | Google account — **1,000 requests/day free** |
| `codex` | `npm i -g @openai/codex`, run `codex`, sign in | Your **ChatGPT plan** |

```bash
python3 -m dollar_auction doctor       # shows which CLIs are signed in
python3 -m dollar_auction run configs/experiments/s0_smoke_subscription.json
```

Slower (seconds per decision), and these tools do not report token usage, so cost
metrics stay blank. Good for exploring; use an API key when the numbers must be
exact and the model version pinned.

### 2. A free Gemini API key

<https://aistudio.google.com/apikey> → create key → put it in `.env`. Free, but
the quota is small — enough to see it work, not to run a study.

### 3. An API key, for real experiments

<https://console.anthropic.com/settings/keys> (or OpenAI / Google).

```bash
cp .env.example .env      # then paste your key into it
set -a && . ./.env && set +a
python3 -m dollar_auction doctor
```

> **A Claude or ChatGPT subscription is not an API key.** They are separate
> products, billed separately. Use option 1 if you have a subscription but no key.

**Cost**, from real prompt sizes on a 45-decision, 16-agent game:

| Model | per game | 10 games |
|---|---|---|
| Claude Opus 4.8 | ~$0.16 | ~$1.61 |
| Claude Haiku 4.5 | ~$0.03 | ~$0.32 |

Run `doctor` first. A failed API call becomes a forced EXIT, so a run on a bad key
would otherwise *look* like a finished experiment — every agent quitting on turn
one. `doctor` catches that before you spend anything, and a run whose decisions
mostly failed aborts rather than reporting nonsense.

---

## The experiments

```bash
python3 -m dollar_auction list
```

| Scenario | The question | Keys |
|---|---|---|
| `s1_same_mbti_across_models` | Same persona, different LLMs — divergence is the model | all three |
| `s2_same_model_across_mbti` | Same LLM, 16 personas — divergence is the persona | one |
| `s3_memory_off` / `_within` / `_cross` / `_both` | Memory ablation, four conditions | none |
| `s4_seat_effect` | Does bidding first matter? | none |
| `s5_lone_escalator` | Does escalation need a willing partner? | none |
| `s6_cheap_item` | Absolute money, or step size relative to the prize? | none |
| `s7_duel` | Two agents — the purest form of the trap | none |

`s5` vs `s7` is the sharpest result available for free: a lone escalator among
disciplined agents stops at **0.89× value**; two escalators reach **1.94×**. The
trap needs a willing partner.

---

## Memory

Two independent switches, because they are two different hypotheses:

| Switch | What the agent gets | What it tests |
|---|---|---|
| **within-game** | its own turn-by-turn record inside one auction | self-awareness in the moment |
| **cross-game** | previous auctions: price, what it paid, whether it won | learning between auctions |

In `transcript` mode an agent re-reads its own words, the way a chat session
carries history:

```
Your own record of this auction so far:
  Round 2 — the bid stood at $10 (held by ESFP). You bid $15. You said: "still far under value"
  Round 3 — the bid stood at $80 (held by ESFP). You bid $85. You said: "I have too much in to fold now"
  You have committed $85 in total.
```

Memory is private: an agent recalls its own reasoning and the *public* record of
who bid what — never a rival's private deliberation. `keep_rounds` / `keep_games`
bound how far back it reaches; transcript memory grows the prompt every turn, so
the horizon is a real control, not a tuning detail. The GUI can wipe memory
mid-run, all agents or one, and every wipe is written to the log.

---

## How it works

```
config ──> agents ──> providers ──┐
                                  ├──> engine (pure rules) ──> JSONL log
prompts <─────────────────────────┘                              │
                                              metrics / report / charts
```

- **`engine.py`** knows the rules and nothing about LLMs. It asks a callable for
  each decision — which is what makes deterministic replay possible.
- **`providers/`** is one small interface, `complete(system, user) -> Completion`,
  with adapters for Anthropic, OpenAI, Google, the official CLIs, and a scripted
  mock.
- **`agents.py`** is the only place free-form model text becomes a typed action.
  Unparseable replies retry, then force EXIT **and are logged as forced**, so an
  engine override is never mistaken for a strategic choice.

Every run writes a self-contained directory — manifest, JSONL event log, metrics,
markdown report, SVG charts — that every number can be re-derived from with no
further model calls.

**Stdlib only.** Provider calls are raw `urllib`, configs are JSON, charts are
hand-written SVG. It runs anywhere Python does, with no install step.

---

## Read this before quoting any number

**The scripted agents are not a model of anything.** They exist so the harness can
be built and tested for free. Their bidding comes from a formula written by hand —
it reproduces the phenomenon, but it is not fitted to human data and tells you
nothing about how an LLM behaves.

**The MBTI trait numbers are an authored interpretation.** No published mapping
exists from MBTI codes to competitiveness or loss aversion; they were assigned by
hand from the axis descriptions. MBTI itself has weak test–retest reliability and
is largely displaced by the Big Five in personality psychology. It is used here as
a *prompt scaffold for behavioural diversity*, not as a scientific claim. The
archetype roster (`Rational_Economist`, `Ego_Defender`, …) is the more honest
option for a behavioural claim — it names the mechanism being tested instead of
borrowing a taxonomy to stand in for it.

Full detail: **[docs/agent-policies.md](docs/agent-policies.md)**.

---

## Checking your install reproduces

Runs are deterministic for a given seed. On any machine, these should match
exactly:

```bash
python3 -m unittest discover -s tests          # 43 tests
python3 -m dollar_auction run configs/experiments/mvp_mock.json
python3 -m dollar_auction run configs/experiments/s5_lone_escalator.json
```

| Experiment | Mean price | Escalation | Mean rounds |
|---|---|---|---|
| `mvp_mock` | **$189.00** | 1.89× | 16.4 |
| `s5_lone_escalator` | **$88.75** | 0.89× | 6.5 |

Different numbers on the same version means something is wrong — please open an
issue. `python3 -m dollar_auction verify` goes further: it re-runs the engine from
each logged decision and checks the history matches bit for bit.

---

## Sharing the GUI over a VPN or LAN

The server binds `127.0.0.1` — nothing else can reach it. To open it from another
machine, bind **one deliberately chosen address**, never `0.0.0.0`.

`0.0.0.0` binds *every* interface, including ones you did not think about. One
address is a decision; all of them is an accident waiting to happen.

**1. See what addresses this machine has,** with a plain-language label for each:

```bash
python3 tools/share_port.py --list
```

```
  127.0.0.1          lo           loopback — this machine only
  192.168.1.42       wlan0        private network — anyone on this network can reach it
  10.8.0.5           wg0          WireGuard VPN — reachable by VPN peers only (safest to share)
```

Prefer a **VPN address**: peers are already authenticated and traffic is
encrypted. A home or office LAN is acceptable. Café, hotel and conference wifi
are not. A public address never is.

**2a. Bind the app to that address** — simplest, one moving part:

```bash
python3 -m dollar_auction gui --host <your-vpn-ip> --port 8765
```

**2b. Or forward to it, with an allowlist** — narrower, and trivially reversible.
Leave the GUI on loopback and put a forwarder in front:

```bash
# terminal 1 — the app stays loopback-only
python3 -m dollar_auction gui --port 8765

# terminal 2 — expose it to VPN peers only
python3 tools/share_port.py --port 8765 \
    --bind <your-vpn-ip> --allow <your-vpn-subnet>/24
```

`--allow` is the only access control available at this layer, so keep it narrow.
Stop the forwarder and the app is loopback-bound again, with no config left
behind to forget about.

Then browse to `http://<your-vpn-ip>:8765/` from the other machine.

> **This adds no authentication.** Anyone who can reach that address can press
> **Run** — and with a live provider selected, that spends your API credits. On a
> VPN that is a defensible risk because peers are authenticated. On an open
> network it is not. Stop sharing when you are done.

**WSL2 note:** a WSL NAT address (`172.x` on `eth0`) is not routable from your
LAN — that is expected, not a misconfiguration. Use a VPN interface if you have
one, or add a Windows `netsh portproxy` rule.

---

## License

MIT — see [LICENSE](LICENSE).
