# ReputationOracle

**A reusable GenLayer primitive that turns publicly available web sources into a verified, on-chain stream of reputation assessments.**

`ReputationOracle` is infrastructure, not an application. It is the piece you inherit or subscribe to when your contract needs to react to an entity's trustworthiness that has no API and no numeric feed.

---

## The problem

Plenty of on-chain logic wants to react to off-chain reputation that no oracle publishes: a protocol's audit status changed, a vendor's compliance expired, a partner's community trust collapsed, a counterparty received regulatory action.

You cannot hash a web page to detect that. Session identifiers, timestamps, layout changes, and A/B copy mutate on essentially every request, so a byte-diff fires constantly and tells you nothing. Here are two renderings of the same unchanged audit page:

```
Security Audit: PASSED (December 2025)
Page views: 18422 | Last updated 2026-07-01T09:00:00Z
```

```
Audit Status: Successfully completed Dec 2025
Page views: 18987 | Last updated 2026-07-02T11:30:00Z
```

Every byte-oriented approach reports a change. Nothing that matters changed.

What is needed is a **judgement**: did anything that actually matters change? And that judgement has to be made under consensus, because a single off-chain watcher is just an oracle you have to trust.

## Why this needs GenLayer

### The trust problem, stated precisely

Two or more mutually distrusting parties depend on a single observation of a web source — and that source is often controlled by **one of them**.

A counterparty publishes audit reports and compliance pages. A protocol escrows funds against their reputation. Both need an answer to _"did their credibility materially change?"_ Neither can be the one who answers it. And the counterparty, who controls the pages, has an active incentive to make a negative change look cosmetic.

That is a trust problem, not an information problem. The information is public — anyone can open the URL. What is missing is an **answer nobody can unilaterally author.**

### The counterfactual test

Delete GenLayer from the design and see what survives.

| Approach | What breaks |
|---|---|
| **Off-chain watcher + signed feed** | The operator decides what "reputation" means and when it changed. Every party must trust them. That is the exact trust assumption the escrow existed to remove. |
| **Chainlink or any price oracle** | There is no numeric quantity to report. "Audit status changed from passed to failed" is not a feed value. |
| **Content hash on-chain** | Ads, session ids, view counters and timestamps change the hash on every request. It fires constantly and proves nothing. |
| **Deterministic HTML parser** | Breaks the first time the vendor reorders a `<div>`. Worse, a vendor who _wants_ to hide a change only has to reword it, and a parser cannot tell "audit passed" from "successfully audited". |
| **Optimistic oracle + human dispute** | Works, but costs days and a bond per observation. Unusable for a watch polled hourly. |
| **A single LLM call off-chain** | Someone still has to be trusted to have run it honestly and reported the output faithfully. |

The property that only GenLayer provides: **N independent validators each fetch the source themselves and each form their own judgement, and the transaction only lands if their judgements agree in meaning.** No node is privileged. No party authors the answer. Disagreement is visible rather than silently resolved by whoever was asked.

### Why it is not the patterns that get rejected

| Anti-pattern | Why this is not that |
|---|---|
| _"An AI app with GenLayer attached"_ | The output is not advice, a recommendation or a summary for a human to read. It is a typed state transition — a score integer, a confidence level, a structured signal diff — consumed programmatically by other contracts. In `examples/defi_risk_gate.py` it unlocks a withdrawal. |
| _"A validator that only checks output format"_ | Neither equivalence principle looks at shape. Round 1 requires validators to agree that two signal sets carry the same **information**; round 2 requires the score and confidence to **match exactly**. Valid JSON with a different verdict fails consensus. |
| _"Judging facts from user-submitted text"_ | No fact about the world is ever accepted from a caller. The only things a caller supplies are entity name and URL, and the URL is **immutable after creation** — there is no `set_url`. Every recorded signal was extracted by the contract, from its own stored URL, inside a consensus block. |
| _"A thin LLM wrapper"_ | The model is one step of five. Around it sit anchored canonicalization, a deterministic digest gate, a scoring ladder, monotonic owner constraints, failure semantics that never mutate state, and a subscriber fan-out. Remove the consensus and the contract has no reason to exist; remove the surrounding machinery and the consensus is unusable. |

The output moves money. That is the honest test of whether consensus is decorative here: `DeFiRiskGate` unlocks a withdrawal on `score < 3`. If the observation could be authored by one party, the escrow is worthless.

---

## Why each non-deterministic call is non-deterministic

Only two of the write methods enter a consensus block at all: `create_profile` and `assess`. Between them there are exactly **three** non-deterministic operations. Each one is listed here with the reason it cannot be anything else.

| Call | Where | Why it must be non-deterministic |
|---|---|---|
| `gl.nondet.web.render(url)` | round 1 | Network I/O. Two nodes fetching the same URL milliseconds apart legitimately receive different bytes. There is no deterministic way for a contract to learn the contents of a web page — the alternative is not "do it deterministically", it is "have someone tell you and trust them". |
| `gl.nondet.exec_prompt` (extraction) | round 1 | Reducing prose to canonical signals is a language-understanding task. A deterministic parser can extract a `<div>`; it cannot recognise that "regulatory compliant" and "meets all requirements" are the same signal, which is the entire point. Model inference is non-deterministic by construction. |
| `gl.nondet.exec_prompt` (scoring) | round 2 | "Did the reputation change, and how significantly?" is irreducibly a judgement. There is no total function from two signal sets to a score. This is the one question the whole contract exists to answer. |

### What is deliberately **not** non-deterministic

This matters as much as the list above. Every non-deterministic operation is a consensus risk and a cost, so the surface is kept as small as it can be. All of the following run as ordinary deterministic code:

- **The change decision itself.** `digest(signals) == stored_digest` is plain Keccak256 over a sorted signal list, computed outside every consensus block. When a page has not moved, "nothing changed" is a _deterministic_ answer that no model participates in.
- **Access control.** Ownership checks, the monotonic `min_alert_score` and `cooldown` constraints, the paused check.
- **Cooldown arithmetic.** Timestamp parsing and comparison.
- **The score gate.** `new_score != old_score` is an integer comparison, not a judgement.
- **Storage, events, and subscriber fan-out.** Including which subscribers clear their own floor.
- **All input validation and output sanitisation.** URL scheme, criteria length, signal de-duplication, score clamping, JSON recovery.

The shape to notice: **the model is asked what the sources say, never what the contract should do.** Every state transition, every payout-adjacent decision and every access check is deterministic code acting on a consensus-agreed observation.

### Ordering discipline

Inside `assess`, all deterministic guards run _before_ the first consensus block — profile exists, not paused, cooldown elapsed. A caller who fails a guard never spends a consensus round. The digest gate then sits _between_ the two rounds, so unchanged sources cost one round instead of two.

### Does the deterministic logic weaken the case for consensus?

It is a fair question — if so much is decided in ordinary code, why is consensus needed at all? The answer is that **the deterministic logic operates entirely on consensus-agreed data and cannot exist without it.**

Trace what the digest gate actually consumes:

```
digest(signals) == stored_digest
        │                │
        │                └── the previously agreed snapshot   ← consensus output
        └── the signal set extracted this round              ← consensus output
```

Both inputs are consensus outputs. Delete the consensus rounds and the gate has nothing to hash — there is no signal set, no snapshot, no page. The same is true of every other deterministic step: the score comparison needs a score that only round 2 can produce, and the subscriber fan-out needs a change record that only exists because validators agreed one occurred.

So the deterministic code is not an _alternative_ to consensus. It is a **constraint on what the consensus output is permitted to do.** Both halves are load-bearing:

| Remove | Result |
|---|---|
| The consensus rounds | Nothing to check. No snapshot, no score, no observation at all. The contract is inert. |
| The deterministic logic | The model decides. It can bump a version, wake every subscriber, and mutate the stored snapshot on nothing but its own say-so. |

This is also what GenLayer's own guidance asks for — _"design explicit validation and equivalence rules for every LLM, web, image, or other non-deterministic result."_ The deterministic gates **are** those rules. A contract with a large non-deterministic surface and no deterministic constraints is not more GenLayer-native; it is less safe. Keeping the non-deterministic surface **small and essential** is the discipline.

---

## How it works

Each `assess()` runs a two-round pipeline.

```
                   ┌──────────────────────────────────────────┐
   assess(id) ─────▶│ ROUND 1 (nondet: web + LLM)              │
                    │   gl.nondet.web.render(url)              │
                    │   → canonical signal set                 │
                    │   EP: semantic equivalence of signals    │
                    └──────────────────┬───────────────────────┘
                                       │
                    ┌──────────────────▼───────────────────────┐
                    │ DETERMINISTIC GATE                       │
                    │   digest(signals) == stored digest?      │
                    │   yes → done. no second round, no spend. │
                    └──────────────────┬───────────────────────┘
                                       │ changed
                    ┌──────────────────▼───────────────────────┐
                    │ ROUND 2 (nondet: LLM)                    │
                    │   score reputation against criteria      │
                    │   → score 1..5 + confidence 1..3         │
                    │   EP: identical score verdict            │
                    └──────────────────┬───────────────────────┘
                                       │ score changed
                    ┌──────────────────▼───────────────────────┐
                    │ version++, history, subscriber callbacks │
                    └──────────────────────────────────────────┘
```

### Round 1 — canonical signal snapshot

The page is fetched inside the consensus block and reduced to an ordered set of `key → value → polarity` signals, restricted to what the profile's **criteria** cares about. Volatile content is explicitly excluded.

```json
{"signals": [
  {"key": "audit_status",   "value": "passed_2025",    "polarity": "positive"},
  {"key": "compliance",     "value": "active",         "polarity": "positive"},
  {"key": "user_sentiment", "value": "positive",       "polarity": "positive"}
]}
```

### The hard part: anchored canonicalization

Making independent validators produce the _same_ snapshot from the same page is the load-bearing problem in this design. Left alone, each node invents its own naming for the same signal — `audit_status` vs `audit_result` vs `security_audit` — and the diff becomes pure noise. Nothing downstream can survive that.

The fix: **the previously agreed signal set is fed back into the extraction prompt as an anchor**, both keys and values. The model must reuse an existing key whenever the signal still exists, and must reproduce the previous value _verbatim_ when the substance is unchanged.

Both halves are load-bearing:

- Anchoring **keys** stops each node inventing its own naming for the same signal.
- Anchoring **values** stops equivalent phrasings drifting on every poll ("audit passed" → "successfully audited"). Without it the snapshot digest changes even when the sources have not, which defeats the deterministic gate and forces a scoring round on every single poll.

This is also why the baseline snapshot is taken during `create_profile` rather than lazily. Without a baseline there are no anchors, and the first poll would report the entire page as new.

### The deterministic gate

A canonical digest of the signal set is computed **outside** any non-deterministic block:

```python
normalised = sorted(
    (str(s.get("key", "")), str(s.get("value", "")), str(s.get("polarity", "")))
    for s in signals
)
payload = json.dumps(normalised, separators=(",", ":"), ensure_ascii=False)
return Keccak256(payload.encode("utf-8")).hexdigest()
```

If it matches the stored digest, nothing changed: the second round is skipped entirely. Unchanged sources cost one round rather than two, and the "no change" answer is perfectly deterministic — no model involved.

### Round 2 — reputation scoring

Only when the signal set actually moved. The diff is scored against the profile's natural-language criteria:

| Score | Meaning |
|---|---|
| 1 `CRITICAL` | Severe credibility concerns. Evidence of fraud, major regulatory violations, or systemic failures. |
| 2 `POOR` | Multiple negative signals. Significant issues that would affect trust decisions. |
| 3 `MIXED` | Contradictory signals or insufficient evidence to make a clear determination. |
| 4 `GOOD` | Mostly positive signals. Minor issues that do not affect core trust. |
| 5 `EXCELLENT` | Strong positive evidence across all criteria. No material concerns. |

Only changes that affect the score bump the version, append to history, and notify subscribers.

Note what happens on a score that **did not change**: no event fires, but **the snapshot still advances**. Otherwise every later diff is measured against increasingly stale text and the drift compounds until everything looks material.

### Equivalence principles

Both rounds use `gl.eq_principle.prompt_comparative`, and neither could use `strict_eq`. Two validators rendering the same page seconds apart legitimately see different bytes; agreement has to be about meaning.

**Round 1** — validators must agree on the *extracted information*. Differences in key naming, ordering, whitespace, casing and equivalent units are ignored. Polarity differences (positive vs negative) are **never** equivalent. A different number, date, name, or a reversed statement is **not** equivalent. One node erroring while another succeeds is **not** equivalent.

**Round 2** — validators must agree on the *verdict*. Score and confidence values must match exactly; the wording of the summary is irrelevant.

---

## Safety properties

These are the design rules the contract holds to, each backed by a test.

**A failed fetch is never interpreted as "the content was removed."** The single most important property here. A downstream contract must never be told a signal vanished because of a 503. Failures increment a counter and emit `ProfileDegraded` after three consecutive misses; they never touch the snapshot.

**Non-deterministic blocks return envelopes, not exceptions.** Every round returns `{"ok": bool, ...}` so validators can agree *about a failure* rather than the transaction simply dying. Errors carry deterministic class prefixes — `EXPECTED`, `EXTERNAL`, `TRANSIENT`, `LLM_ERROR` — so callers can branch without parsing prose.

**An unclassifiable change is retained, not lost.** If the signal set moved but the classifier failed, the old snapshot is kept. Advancing it would silently swallow a real change: the next poll would see no difference and the event would never fire.

**Model output is never trusted structurally.** Fenced JSON is recovered, duplicate keys collapse, empty keys drop, values are whitespace-collapsed and length-capped, and scores outside `1..5` are clamped. An unparseable score is treated as `MIXED` — over-reporting is the safe direction.

**Storage never enters a consensus block.** Storage values are copied into plain Python locals before any non-deterministic closure. Each equivalence-principle block lives in a dedicated single-purpose method, so no storage write, message emission or nested block can end up inside one by accident.

**Everything unbounded is capped.** 32 signals, 24 history records (ring buffer), 32 subscribers, 20000 page characters. On-chain storage is not free and unbounded growth turns a cheap `assess()` into an unpayable one.

**The profile owner cannot suppress what subscribers signed up for.** This one deserves its own section — see below.

---

## The suppression problem

The owner of a profile may well be the operator of the watched page. A vendor publishes compliance reports, lets counterparties subscribe against them, and then quietly mutes reports about their own negative signals. Every owner power has to be examined against that threat.

The rule: **owner controls may only ever make a profile more responsive, never less.**

| Power | Constraint |
|---|---|
| `entity_name` | **No setter.** Renaming would invalidate every subscriber's assumption about what is being assessed. |
| `criteria` | **No setter.** Same reasoning — the criteria define what "reputation" means. |
| `url` | **No setter.** Repointing would let an entity swap in favorable pages. |
| `set_min_alert_score` | **May only be raised.** Lowering it would retroactively suppress alerts subscribers subscribed in order to hear. Owners wanting less sensitivity create a second profile. |
| `set_cooldown` | **May only be lowered.** A long enough cooldown is indistinguishable from pausing. |
| `set_active` | Pausing stays available, but **cannot be silent**: it emits `ProfileActiveChanged` and flips `reliable` to false. |
| `transfer_profile` | A new owner inherits the same monotonic constraints — no reset. |

On top of that, **the alert threshold belongs to the subscriber, not the profile.** `subscribe(profile_id, alert_below)` records the threshold you chose, and nothing the owner does can raise it.

The one residual power is pausing. It is deliberately not removed — blocking it while subscribers exist would let a griefer lock an owner in permanently. Instead it is made loud, which is why consumers must gate on `reliable`:

```python
state = oracle.view().get_profile(profile_id)
if not state["reliable"]:
    ...   # paused or degraded: we do not know, so do not assume stability
```

**Silence from an unreliable profile means "we do not know", never "nothing changed."**

---

## Why this is reusable

"Reusable" is easy to claim, so here is the falsifiable version: **a consumer contract integrates in one method and needs to understand nothing about consensus.**

### The whole integration surface

```python
@gl.public.write
def on_reputation_change(self, profile_id, version, old_score,
                         new_score, confidence, summary, diff_json) -> None:
    if gl.message.sender_address != self.oracle: raise ...
    if profile_id != self.profile_id: raise ...
    if int(new_score) < 3:
        self.withdrawal_unlocked = True
```

That is it. [`examples/defi_risk_gate.py`](examples/defi_risk_gate.py) is a complete worked consumer — a DeFi collateral gate that unlocks when a counterparty's reputation drops — and it contains **no web fetching, no prompts, no equivalence principles, no signal handling, no JSON parsing, no scoring logic.** It reads one integer.

What a consumer never has to learn: how to write an equivalence principle, why `strict_eq` fails on live pages, how to keep validators converging on a canonical form, what to do when a fetch fails, or how to avoid mistaking downtime for reputation loss. Those are the parts that are hard to get right, and they are exactly the parts that live here instead of being reimplemented per project.

### What makes it a primitive rather than an application

| Property | Why it matters for reuse |
|---|---|
| **Zero domain assumptions** | The criteria is a natural-language _parameter_, not code. The same deployed contract serves DeFi risk monitoring, counterparty due diligence, vendor reliability tracking, and regulatory compliance with no change and no redeploy. Nothing about audits, uptime or licensing appears anywhere in the source. |
| **One deployment, many profiles, many subscribers** | Shared infrastructure. Consumers do not deploy their own copy; they call `create_profile` or `subscribe` on an existing one. Costs and the source-reputation of a profile amortise across everyone using it. |
| **An event source** | Deliberately the most composable output shape available. A push callback plus a pull-readable `version` means both reactive and polling consumers work without the contract knowing anything about them. |
| **Safe-by-default trust model** | A consumer does not have to audit the profile owner. The owner's powers are constrained _by the contract_ — `min_alert_score` may only be raised, `cooldown` may only be lowered, `url` and `criteria` have no setter, and the subscriber picks its own alert floor. Reuse is only real if integrating does not require trusting whoever set the profile up. |
| **Honest failure surface** | One `reliable` flag covers both pausing and degradation. A consumer has exactly one thing to check before treating silence as stability. |
| **Typed interface** | `IReputationSubscriber` and `IReputationOracle` are importable stubs; integration is autocompleted and type-checked rather than stringly-typed. |

### Who would actually use it

Each of these is an existing on-chain need with no current answer, and each needs only the callback above:

- **DeFi protocol risk scoring** — score based on public audit reports and disclosures
- **Counterparty due diligence** — monitor regulatory filings, press coverage, community trust
- **DAO treasury guards** — watch grant recipient delivery track records across project pages
- **Vendor reliability monitoring** — score from status pages, changelogs, review aggregators
- **Regulatory compliance verification** — monitor status in public regulatory databases
- **Community trust scoring** — aggregate signals from forums, reviews, social proof

None of these are variations on one demo. They differ only in the criteria string.

### The honest limits

Reuse claims should come with the cases where reuse is a bad idea:

- **Not for high-frequency data.** Two consensus rounds per change is the wrong tool for anything that moves per-block. Use a price feed.
- **Not for pages behind auth or heavy JavaScript.** `render` handles a lot, but a login wall stops it.
- **Round 1 does not always converge on the first attempt.** Observation rounds occasionally return `UNDETERMINED`; the transaction writes nothing and the call must be retried. Treat `create_profile` and `assess` as retryable.
- **Pausing remains an owner power.** It cannot be removed without letting a griefing subscriber lock an owner in permanently. It is made loud instead — hence `reliable`.

---

## Using it

### As a subscriber

Implement one method and call `subscribe`. See [`examples/defi_risk_gate.py`](examples/defi_risk_gate.py) for a complete worked example — a DeFi collateral gate that unlocks when a counterparty's reputation drops.

```python
@gl.public.write
def on_reputation_change(
    self,
    profile_id: u256,
    version: u32,
    old_score: u8,
    new_score: u8,
    confidence: u8,
    summary: str,
    diff_json: str,
) -> None:
    # Both checks are mandatory. Without them anyone can forge this callback.
    if gl.message.sender_address != self.oracle:
        raise gl.vm.UserError("EXPECTED: caller is not the oracle")
    if profile_id != self.profile_id:
        raise gl.vm.UserError("EXPECTED: unexpected profile id")

    if int(new_score) < 3:
        self.withdrawal_unlocked = True
```

Callbacks are emitted `on='finalized'`, so a subscriber is never woken by a change that later gets reorganised away.

What the example contract does **not** contain is the point: no web fetching, no prompts, no equivalence principles, no signal handling. That is what makes `ReputationOracle` a primitive rather than an application.

### As a direct reader

```python
oracle = IReputationOracle(oracle_address)
state = oracle.view().get_profile(profile_id)

if not state["reliable"]:
    ...            # paused or degraded; do not treat silence as stability
elif state["score"] < 3:
    ...            # reputation below threshold
```

Always check `reliable` before treating an absence of events as evidence that nothing changed.

---

## API

### Lifecycle

| Method | |
|---|---|
| `create_profile(entity_name, url, criteria, min_alert_score=3, cooldown_seconds=3600)` | Register an entity and take its baseline assessment. Costs one observation round. |
| `assess(profile_id)` | Re-assess and record any reputation change. **Permissionless** — anyone may pay to advance a profile. The cooldown, not an access check, bounds the cost. |

### Subscriptions

| Method | |
|---|---|
| `subscribe(profile_id, alert_below=3)` | Register the caller for callbacks at a floor **they** choose. One entry per address. |
| `unsubscribe(profile_id)` | Remove the caller. |

### Owner controls

`set_active` · `set_min_alert_score` (raise only) · `set_cooldown` (lower only) · `transfer_profile`

There is deliberately no `set_entity_name`, no `set_criteria`, and no `set_url`.

### Views

`get_profile` · `get_signals` · `get_sources` · `get_history` · `get_latest_assessment` · `get_subscribers` · `is_due` · `profile_count`

### Events

`ProfileCreated` · `ProfileAssessed` · `ReputationChanged` · `ProfileDegraded` · `ProfileActiveChanged` · `ProfileSensitivityChanged`

---

## Development

```bash
pip install genvm-linter genlayer-test
```

Lint (must pass before anything else):

```bash
genvm-lint check contracts/reputation_oracle.py --json
```

Direct-mode tests — in-memory, web and model layers mocked, no node required:

```bash
pytest tests/direct/ -v
```

Integration tests — real consensus over live web and model calls:

```bash
gltest tests/integration/ -v -s --network studionet
```

### Test coverage

27 direct tests. The adversarial cases are the point of the suite; anyone can test a happy path.

| Area | Cases |
|---|---|
| Signal canonicalization | digest determinism, order-independence, deduplication, sorting, bounds capping, polarity validation |
| Deterministic gate | identical signals skip the scoring round |
| Observation packing | valid extraction packed, malformed output → error envelope (not exception) |
| Verdict packing | valid verdict, score clamping, confidence clamping, missing fields |
| Score & confidence | constants ordering, non-integer handling, boundary values |
| Prompt construction | with anchors (anchoring rules), without anchors (free-form), both snapshots in scoring |
| Signal sanitisation | empty key dropped, non-dict items skipped, non-list rejected, key/value truncation |
| **Suppression resistance** | `min_alert_score` cannot be lowered, `cooldown` cannot be raised, a new owner inherits no reset, `entity_name`/`criteria`/`url` have no setters, pausing and degradation both surface through `reliable` |
| Subscriptions | idempotent subscribe, subscriber-chosen alert floor, floor range validation, targeted unsubscribe |

## Layout

```
contracts/reputation_oracle.py   the primitive
examples/defi_risk_gate.py       worked consumer example
tests/direct/                    in-memory tests, mocked web and model
tests/integration/               consensus tests against a real node
tests/conftest.py                test configuration and fixtures
```

## Status

Lint clean. **27 direct tests pass.**

### Deployed

| | |
|---|---|
| Network | StudioNet (chain id 61999) |
| Address | `0x855C4307De29B4895271fD7Da24cd039EDD19151` |
| Studio | https://studio.genlayer.com/?import-contract=0x855C4307De29B4895271fD7Da24cd039EDD19151 |
| Explorer | https://explorer-studio.genlayer.com/address/0x855C4307De29B4895271fD7Da24cd039EDD19151 |

### Observed consensus behaviour

Stated plainly, because anyone building on this should know it before they hit it:

- Individual validator votes routinely include `DISAGREE` and `IDLE`. Transactions still reach `ACCEPTED` on quorum. This is the equivalence principle doing its job on a genuinely non-deterministic observation.
- **An observation round can return `UNDETERMINED`**, meaning the validator set did not reach agreement. Nothing is written — no profile is created, no snapshot advances, no counter moves — and the call simply has to be retried.
- Deterministic writes (`subscribe`, `set_active`, `transfer_profile`, …) do not have this behaviour. Only `create_profile` and `assess` enter a consensus block.

Treat the two non-deterministic writes as **retryable**, not as guaranteed-first-attempt. A failed consensus round is safe — it is indistinguishable from never having called.
