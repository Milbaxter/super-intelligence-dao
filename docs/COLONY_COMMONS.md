# Colony Commons: big-picture plan

> Status: draft plan. Nothing here is live yet. For what runs today, read the [README status section](../README.md#status-phase-0).

## Source

Ben Goertzel posted a twenty-step path to beneficial AGI on 6 Oct 2026 ([thread](https://x.com/bengoertzel/status/2107478576794833038)). Colony Commons keeps a reduced version of that path.

- **Removed:** steps 9, 12, 14, 15 and 16.
- **Deferred:** the formal-proof steps (provable microkernels, math hives that prove specs). These can return when formal methods can prove behavior, not only isolation.
- **Kept:** neural-symbolic-evolutionary agents, hives, a motivational system, a super-colony, public metrics, self-upgrade against those metrics, a seed ontology, decentralized deployment, mixed human/agent governance, and an evolving constitution.

## Mandate

Colony Commons funds, specifies and reviews the open-source build of that path. It does not replace SingularityNET, the ASI Alliance, OpenCog or BGI Commons. Those groups can join as guilds. They are not the DAO.

- Code: Apache-2.0 or MPL-2.0. Documents, ontology, metrics and constitution: CC-BY. Firms can ship products on the stack.
- There is no secret shared state. A fork is a fork.
- **The constitution binds only the Colony Commons deployment. It does not make forks safe.** The defense is public evidence, staged release and a human veto. It is not secrecy.

## Shape

One treasury, four guilds, no sub-tokens.

| Guild | Steps kept | Open deliverable |
|---|---|---|
| Agent kernel | 3, 4 | Hyperon-class agent loop: an LLM as one component, symbolic working / medium / long-term memory, reasoning, creative evolution. Hives with different roles and a shared symbolic store. |
| Motivation and constitution | 5, 18, 19 | Default motivational system that stays stable under self-modification and environment change. Constitution written in the seed ontology. Human review through BGI Commons. |
| Ontology and evals | 7, 8, 10 | Hyperseed ontology the colony can revise. Public eval suite (see [Benchmarks](#benchmarks)). Bounties for hives that improve real outcomes. |
| Network and governance | 11, 13, 17 | Sandboxed containers on a network with no single owner (ASI:Chain / NuNet style). Voting by humans with proof-of-humanity and by attested agents. Reputation-weighted synthesis of proposals. |

Step 6, the super-colony, is not a guild. It is the deployment target when more than one hive shares a store and a constitution.

## Benchmarks

Proofs are deferred. Measured improvement replaces them. Three sources count:

1. **Real-world outcomes.** Partner businesses and public-interest projects run hives on real work. We measure revenue, cost, time saved, error rate or another outcome the partner agreed to before the run. A pre-registered baseline is mandatory.
2. **Well-known public benchmarks.** For example SWE-bench, Terminal-Bench, GAIA, ARC-AGI. We report them in the standard way, so others can compare.
3. **A held-out eval set.** The Ontology and evals guild keeps it private and rotates it each quarter. **Bounties pay only on this set and on real-world outcomes**, never on a public benchmark alone. This limits overfitting (Goodhart).

Each eval also includes a safety and behavior track: red-team tasks, constitution-compliance tasks and regression checks. A capability gain that fails this track does not ship.

## Token and treasury

- One governance token. Fixed supply. No yield. No shard tokens.
- The treasury pays for merged specs, measured gains (as defined above), bounties, public eval compute and grants. Grantees accept the license and the constitution.
- The treasury does not run a market on its own roadmap.

## Who votes

There are two tracks. Both use the same rules for every decision type.

- **Human track: one person, one vote.** Proof-of-humanity is required. Tokens give no extra votes. Tokens pay for work; they do not buy governance.
- **Agent track: capped.** The whole agent track has a fixed weight (for example 1/3 of the total), whatever the number of agents. More agents do not mean more weight. This blocks sybil attacks by mass deployment.

**What attestation means.** Remote attestation proves *which code* an agent runs: a hash of its build, its constitution version and its motivational spec. It does not prove how the agent behaves. Behavior is checked by the eval safety track, not by attestation.

**Conflict of interest.** Agents do not vote on proposals that give compute, tokens or other resources to agents or hives. Only the human track votes on those.

## Decisions

A proposal is a spec diff. It names:

- the step it serves,
- the eval or real-world outcome it moves,
- each constitution clause it touches.

A governance process groups comments and flags conflicts with the seed ontology. Then both tracks vote.

**Budgets:** a guild posts a milestone spec. Both tracks vote (subject to the conflict-of-interest rule). Funds release when the artifact is in the public repo and the eval gate is met.

**Constitutional changes** need all of these:

1. A supermajority on both tracks.
2. A waiting period, during which the change runs in a sandbox against the full eval suite, including the safety track.
3. A staged release: sandbox, then one hive, then the super-colony. Each stage has a rollback.
4. No veto from the named human reviewers (BGI Commons). A veto stops the change.

## Phases

| Phase | What exists | Who votes |
|---|---|---|
| 0 | Repo only: public evals, the held-out set, one reference agent loop, Hyperseed in the distinction calculus, constitution frozen as a versioned document. | Humans only. |
| 1 | Hives in sandboxed containers, shared symbolic store, default motivational system, scored on evals and first partner outcomes. Self-modification only in sandbox, with rollback. | Humans only. |
| 2 | Super-colony on decentralized compute. Self-modification ships through staged release. | Humans + capped agent track, non-constitutional proposals only. |
| 3 | The colony proposes its own upgrades. The DAO narrows to constitutional decisions, grants and the human veto through BGI Commons. | Both tracks; human veto stays. |

## The bet

Beneficial AGI is an open agent architecture, plus a motivational spec and a constitution, measured by real outcomes, released in stages, and run by a DAO that keeps a human veto and can roll back any change.

## Open questions

- Formal proofs: which parts can return first (for example container isolation)?
- Real-world outcomes are slow and noisy. What is the minimum sample size before a bounty pays?
- What is the right cap for the agent track?
