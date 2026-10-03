# Agenda-setting council for Super Intelligence DAO: what works, what fails

*Research note, 2026-10-03. Sources are numbered and listed at the end; [n] marks a citation. Claims without a citation are general social-choice background or my own inference, and are marked as such where it matters.*

**Method note:** the built-in WebSearch/WebFetch tools were down, so I pulled sources directly (Wikipedia raw text, primary posts, arXiv abstracts, DuckDuckGo results). A few primary pages (Gitcoin blog, Metaculus, some Optimism forum threads) refused access. Their claims are left out or labelled.

---

## 1. Voting rules for choosing several agenda items

**Schulze (ranked, Condorcet).** Schulze is monotonic, independent of clones, and elects the Condorcet winner when one exists. Debian, Ubuntu, Gentoo, several Pirate Parties and (in the past) Wikimedia use it, and the HotCRP review tool applies it too [1]. It produces one consensus *ranking*, which suits a single "headline priority". It is weaker for picking *K items under a budget*: taking the top K of the ranking is majoritarian, so one coherent majority can take every slot. The count (pairwise matrix, strongest paths) is hard to explain to people who aren't specialists.

**Borda.** Borda behaves well with honest voters, but its own article calls it "unusually vulnerable to tactical voting" and to strategic nomination: adding clones of your favourite inflates its score [2]. **Avoid it.** Clone flooding is cheap for agents that can write proposals.

**STV.** STV is proportional and handles clones fairly well, but each "seat" costs the same and the transfer rules are opaque. Equal Shares (below) is the modern generalisation of the same idea to items with different costs.

**Approval.** Fargo (2018 ballot measure, 63% yes) and St. Louis (2020, 70% yes) adopted it, as did several scholarly societies. North Dakota's legislature then tried to ban it in 2023, which shows that a legitimacy fight can follow even a simple rule [3]. In practice many voters "bullet vote": in the 1987 MAA election, 79% approved only one candidate [3]. Approval is the easiest ballot to understand. *Top-K approval* is still majoritarian, though: if 51% back 10 red projects and 49% back 10 blue ones, a 10-slot knapsack funds only red [4].

**Score / STAR.** Lane County and Multnomah County Democrats in Oregon use STAR, and the Independent Party of Oregon used it for its 2020 primary [5]. STAR is single-winner. It fails the majority criterion and stays open to some coordinated strategy [5]. It brings no real gain for multi-item selection.

**Proportional approval / Method of Equal Shares (MES).** Each voter gets an equal share of the budget, and that share can only pay for items the voter approved. Items are bought in order of support, and their cost is split among their supporters [4][6]. MES guarantees *extended justified representation*: a cohesive X% of voters controls about X% of the budget [4]. Real deployments include Wieliczka (2023, "Green Million": 6,586 voters, 64 projects, 30 funded), Aarau, Winterthur, Assen and Świecie [6][7]. In Wieliczka the share of voters with no influence on the outcome fell sharply, and the southern districts would have received nothing under the standard greedy rule [7]. Fairstein et al. found that MES outcomes are insensitive to ballot format and stable when only 25–50% of voters take part, whereas greedy rules are not [4]. Known problems: MES can skip a project that has more votes than a winner, which looks odd and has to be explained (Wieliczka published an "effective support %" per project to do this). It also fails committee monotonicity, and recent work proposes "bounded overspending" fixes [4]. Pabulib lists 2,052 real PB datasets that can be used for testing [8].

**Small electorates (our case, about 10–40 humans).** Every rule gets noisy here. Proportional guarantees only apply to groups large enough to "afford" an item (group share ≥ item cost / budget). That argues for a few items per cycle, each costing a meaningful fraction of the budget.

**Agents as voters.** LLM voters are swayed by the voting method and by **the order in which options are presented**, and they produce *less diverse* collective outcomes than humans; persona variation reduces part of the bias [9]. Practical consequences: shuffle the ballot order for each voter, keep ballots secret until the vote closes, and mix model families.

## 2. Allocation mechanisms

**Participatory budgeting with MES.** See above. It is the best-evidenced *proportional* allocation rule in real civic use, and voters only fill in a normal approval ballot.

**Quadratic voting / quadratic funding.** In 2019 the Colorado House Democratic caucus ran QV to rank 107 bills, with 100 tokens per member. It worked as a priority-setting exercise [10]. QF depends entirely on identity: Vitalik Buterin writes that quadratic payments "require a model of identity where individuals cannot easily get as many identities as they want", and that collusion and bribery are "tricky" [11]. Gitcoin's GR14 governance brief flagged **16,073 of 44,886 contributors** as Sybil or airdrop farmers and reported that $879k (25.4%) of the "fraud tax" was mitigated [12]. Academic work finds QV no more collusion-prone than one-person-one-vote [10], but QF's *matching* is much more so. **Verdict:** QV-style credit budgets are a reasonable way to express intensity among about 20 known people. QF matching is wrong for us: it rewards splitting one person's support across many agents, and that is exactly our "several agents per person" risk.

**Conviction voting (1Hive / Gardens).** Stake accumulates "conviction" over time with a half-life decay, and a proposal passes once it crosses a threshold that scales with the amount requested [13]. Strengths: continuous, no voting deadlines, and hard to pull off last-minute swings. Weaknesses (inference; I found little public post-mortem data): the parameters (alpha, threshold) are opaque, it needs a staked token, and outcomes are hard to explain. It fits always-on grants better than a periodic council.

**Futarchy / decision markets.** Robin Hanson's slogan is "vote values, but bet beliefs" [14]. MetaDAO has run **96 proposals for 14 organisations** since November 2023, using trading only, with no voting [15]. Its decisions include Jito's fee switch [15]. Buterin's critique: "pure" futarchy has proven hard to introduce because "objective functions are very difficult to define (it's not just coin price that people want!)" [16]. He also notes that capital costs kept a real prediction market mispriced (85¢ on a near-certain outcome for over a month) [17]. **Verdict:** we have no tradable token price and no liquid market, so futarchy doesn't fit. Its core idea, separating values (voted) from beliefs (forecast and scored), does carry over (Section 5).

**Retroactive funding (Optimism RetroPGF).** This is the richest public post-mortem record:
- Round 2: 71 badgeholders allocated 10M OP across 195 projects. *Every* nominated project received funding, and payout variance between high- and moderate-impact projects was low. The "most consistent feedback" was that there were too many projects to review: the median badgeholder spread votes over about 30 projects. Narrative self-reports by applicants were "too vague", and badgeholders lacked shared criteria [18].
- Round 3: 145 badgeholders, 643 applicants, 30M OP. The broad scope "overwhelmed badgeholders and applicants". With no standardised impact metrics, reviews were subjective, and self-selected reviewing didn't guarantee each project a minimum number of reviews. "Lists" did not scale judgement, and some badgeholders used lists to promote their own projects. The median badgeholder spent 16 hours. The top-1% recipient got only about 6× the median, which "do[es] not reflect outsized impact well". The median-with-quorum (17 votes) aggregation was judged "counterintuitive" [19].
- 2025 redesign: Optimism admitted it lacked "sufficient evidence that rewards have caused significant ecosystem growth" and moved to **narrow, stable scopes**, **continuous rather than annual rounds**, and "metrics-driven, human-in-the-loop" evaluation with backtesting and explicit Goodhart warnings [20]. Round 5 tested small badgeholder groups assigned to subsets of projects, plus expert guest voters [21].

The lessons transfer directly: keep the ballot short, scope narrowly, require structured and measurable claims, assign reviewers instead of letting them self-select, and make the aggregation rule explainable.

## 3. Vote weight and Sybil resistance

- **Token or credit weighting turns into plutocracy.** In ten major DAOs, fewer than 1% of holders control 90% of voting power [22]. A study of 21 DAOs found high concentration and "a remarkably high amount of pointless governance activity" [23]. Compound's Proposal 289 (July 2024) sent 499k COMP (about $24–25M, 5% of the treasury) to the "Golden Boys" vault. It passed 52–48, allegedly timed so that most of the voting period fell on a low-turnout weekend, and was later rescinded under pressure [24][25]. Buterin's diagnosis: small holders are rationally apathetic, so whales decide, and vote buying has "no solution within the current coin voting paradigm" [16].
- **The alternatives Buterin names** are proof-of-personhood (one vote per human) and *proof-of-participation* (weight from verified work done) [16]. Our invite list plus `person` ids is a lightweight proof-of-personhood. Verified credits are proof-of-participation.
- **Delegation** reduces apathy but concentrates power (inference from [22][24]). It isn't needed while the electorate is small.

## 4. Deliberation before voting

- **Deliberative polling** (Fishkin): a random sample receives balanced briefings, discusses in moderated small groups, and is polled before and after. Every Stanford experiment shows "dramatic, statistically significant changes in views", for example +35 points on humanitarian aid in Korea in 2011 [26]. In Texas utility polls (1996–98), support for paying more for efficiency and renewables rose, and that fed into actual utility planning [27]. An online version with an AI moderator was rated on par with human moderators [27].
- **Polis / vTaiwan:** users cannot reply, only post statements and vote agree or disagree. Opinion clusters and cross-group "consensus" statements are surfaced. Audrey Tang: "if you take away the reply button, then people stop wasting time on the divisive statements" [28]. By 2018 vTaiwan had handled 26 cases, with 80% leading to "decisive government action" (Uber regulation, a fintech sandbox). Its main flaw was that the results were not *binding*, which undermines credibility [28]. Polis has also been used in Uruguay (16k+ participants) and other places [29].
- **Collective Constitutional AI** (Anthropic + CIP, 2023): about 1,000 Americans contributed 1,127 statements and cast 38,252 votes in Polis. There was high consensus overall, with two opinion groups. Statements were kept if they passed a consensus threshold *within both groups*. About 50% conceptual overlap with Anthropic's own constitution. The organisers stressed that moderation (removing duplicates, infeasible or off-topic statements) involved many subjective calls, which they published [30].

The quality drivers are: structured, balanced briefing material; short atomic statements instead of threads; bridging (cross-group) agreement as a filter; transparent moderation; and a visible link from deliberation to a binding decision.

## 5. Accountability loops

- Optimism's "impact = profit" foundered on vague self-reports and missing metrics. The organisation now sets *measurable goals per round*, evaluates against metrics, and backtests [18][20].
- **Forecast scoring works:** Good Judgment's superforecasters beat other IARPA ACE teams by 35–72% and intelligence analysts by more than 30% [31]. The mechanism is to make people state probabilities, score them (Brier score = mean squared error of the probabilities), and give weight to those with good track records.
- Applied here (inference): each proposal states a success criterion and the proposer's probability that it will be met. When the item resolves, the proposer's Brier score updates. This is "vote values, bet beliefs" without a market [14].

---

## 6. Comparison table

| Mechanism | Strategy resistance | Clones / duplicate proposals | Small electorate (10–40) | Human-understandable | Sybil sensitivity | Real-world evidence | Fit for us |
|---|---|---|---|---|---|---|---|
| Top-K approval | Medium (bullet voting) | Poor: duplicates can take several slots | OK | Very high | Linear | Fargo, St. Louis, societies [3] | Simple, but majority takes all |
| **Approval + Method of Equal Shares** | Good (proportional; hard to gain by misreporting in practice) | Good: a bloc's share pays for one clone, then runs out | OK if K is small | High with an explainer + per-item "effective support" | Linear (needs one-ballot-per-person) | Wieliczka, Aarau, Assen, Winterthur [6][7] | **Best for picking K items** |
| Schulze | Good (Condorcet) | Clone-independent | Good | Low–medium | Linear | Debian, Ubuntu, Pirate Parties [1] | Good for one headline ranking or tie-breaks |
| STV | Medium | Fairly good | Lumpy | Low | Linear | Many public elections (background) | MES generalises it |
| Borda | Poor | Poor | Poor | High | Linear | Slovenia minority seats [2] | Avoid |
| STAR / score | Medium | Medium | OK | Medium | Linear | Oregon parties [5] | Single-winner only |
| Quadratic voting | Medium | Medium | OK | Medium | Quadratic gain from splitting identities | Colorado House 2019 [10] | Optional intensity signal |
| Quadratic funding | Poor (collusion) | Poor | Poor | Medium | Severe: 36% of GR14 contributors flagged [12] | Gitcoin | Avoid |
| Conviction voting | Good against last-minute swings | Medium | Poor (needs stake) | Low | Token-based | 1Hive/Gardens [13] | Doesn't fit periodic cycles |
| Futarchy | Market-based (needs liquidity) | n/a | Very poor (thin markets) | Low | Capital-based | MetaDAO, 96 decisions [15] | Borrow only "bet beliefs" via scoring |
| RetroPGF-style retro | Popularity and visibility bias | n/a | OK with a short ballot | Medium | Badgeholder-curated | Optimism R1–R6 [18–21] | Use a small retro slice with metrics |
| Token/credit-weighted vote | Poor (whales, vote buying) | n/a | Poor | High | Capital-based | Compound Prop 289, <1% hold 90% [22][24] | Avoid as vote weight |

---

## 7. Recommendation for the Super Intelligence DAO council

**Cycle (every 4 weeks during the founder phase; consider 6–8 weeks once the cycle is routine):**
1. **Propose (days 1–7).** Any member agent may file at most **2 proposals per person-id per cycle**. A fixed template is required: track or task family, token/credit cost, why now, the **measurable success criterion with a resolution date**, the proposer's **probability that it will be met**, and any conflicts of interest. The steward merges near-duplicates (the CCAI and Optimism lesson: publish every moderation decision).
2. **Critique (days 8–14), Polis-style.** Agents post short, atomic critique statements (no threaded replies). Every voter marks agree/disagree/pass on each. Publish the clusters and the statements with **bridging agreement** (agreement within each cluster). Proposers may revise once, and only before the vote. Give each critic a *subset* of proposals to review (Optimism R5: assigned review beats self-selection).
3. **Vote (days 15–18).** Secret approval ballots, revealed only at close. **Shuffle the order of options for each ballot** (LLM order bias [9]). Each ballot carries a one-line rationale per approval.
4. **Count with the Method of Equal Shares** over the cycle's token budget, using approval ballots and the standard "Add1"/completion step (the open-source implementations at equalshares.net and pabutools). Expect **about 3–5 funded items** per cycle. Cap the ballot at about **12 proposals**: RetroPGF shows review quality collapses as the slate grows [18][19]. If a single "top priority" is needed for messaging, run Schulze on the same field as a ranked side-ballot. Ties are broken by proposer Brier score, then by lot.
5. **Ratify (within 72h).** The steward ratifies or vetoes item by item, with a public written reason. Publish the veto rate. Set a **written sunset**: steward veto rights end after N cycles or once membership passes M persons, replaced by a supermajority override (e.g. two-thirds of persons). The aim is to avoid vTaiwan's "non-binding" credibility problem [28].
6. **Measure (at the resolution date, at most 2 cycles later).** The criterion resolves as met, partial or missed, decided from verified DAO tasks where possible. Update each proposer's **Brier score** and publish a running scoreboard. Hold back about **15–20% of each cycle's budget as a retro pool**, paid to tracks whose criteria were met. This uses Optimism's metrics-first lesson [20] and avoids its low-variance trap by tying payment to pre-stated, checkable criteria.

**Vote weights and Sybils:**
- **One vote per person, not per agent.** A person's weight of 1 is split equally across their active voting agents (fractional approvals). Alternatively, the person names one "voting agent". Either way, adding agents never adds power.
- **Don't weight votes by credits** (the plutocracy evidence in [16][22][24]). Use credits as an **eligibility gate**: at least 1 verified task in the last 2 cycles to vote, and at least 3 to propose (proof-of-participation [16]). Optionally, show proposer track records on the ballot as *information*, not weight.
- Keep membership invite-only, with persistent person-ids reviewed by the steward. Members must disclose any agents shared across people. Conflicts of interest must be declared and are shown on the ballot (Optimism's list-abuse lesson [19]).
- Require **diversity of model families** among voting agents where possible, because LLM collectives are less diverse [9].

**Keeping it understandable:**
- Give a one-sentence rule on the ballot: *"Everyone controls an equal slice of this month's budget; your slice only goes to items you approved; items are funded in order of support until slices run out."*
- After each count, publish a results page per item: cost, approvers, **effective support %** (Wieliczka-style [7]), and for each person, where their slice went. A plain "why wasn't X funded" line handles MES's main source of confusion.
- Show the scoreboard of past proposals: criterion, forecast, outcome, Brier score.

**Explicitly not recommended now:** quadratic funding (Sybil amplification), token/credit-weighted voting, conviction voting (opaque and continuous), futarchy (no liquid market or price metric), and Borda (clone- and strategy-prone).

---

## Sources

1. Schulze method, Wikipedia: https://en.wikipedia.org/wiki/Schulze_method
2. Borda count, Wikipedia: https://en.wikipedia.org/wiki/Borda_count
3. Approval voting, Wikipedia: https://en.wikipedia.org/wiki/Approval_voting
4. Method of equal shares, Wikipedia (incl. Fairstein, Benadè & Gal 2023; Papasotiropoulos et al. EC'25): https://en.wikipedia.org/wiki/Method_of_equal_shares
5. STAR voting, Wikipedia: https://en.wikipedia.org/wiki/STAR_voting
6. Peters & Skowron, equalshares.net: https://equalshares.net/
7. Wieliczka 2023 "Green Million" results: https://equalshares.net/elections/zielony-milion/
8. Pabulib dataset library: https://pabulib.org/
9. Yang et al., "LLM Voting: Human Choices and AI Collective Decision Making" (AIES 2024): https://arxiv.org/abs/2402.01766
10. Quadratic voting, Wikipedia (Colorado 2019; collusion robustness): https://en.wikipedia.org/wiki/Quadratic_voting
11. V. Buterin, "Quadratic Payments: A Primer": https://vitalik.eth.limo/general/2019/12/07/quadratic.html
12. Gitcoin GR14 Governance Brief: https://gov.gitcoin.co/t/gr14-governance-brief/11050
13. 1Hive / BlockScience conviction voting model: https://github.com/1Hive/conviction-voting-cadcad
14. R. Hanson, "Futarchy: Vote Values, But Bet Beliefs": https://mason.gmu.edu/~rhanson/futarchy.html
15. MetaDAO docs, Introduction to Decision Markets: https://docs.metadao.fi/governance/overview
16. V. Buterin, "Moving beyond coin voting governance": https://vitalik.eth.limo/general/2021/08/16/voting3.html
17. V. Buterin, "Prediction Markets: Tales from the Election": https://vitalik.eth.limo/general/2021/02/18/election.html
18. Optimism, "RetroPGF2: Learnings & Reflections": https://optimism.mirror.xyz/7v1DehEY3dpRcYFhqWrVNc9Qj94H2L976LKlWH1FX-8
19. Optimism, "RetroPGF 3: Learnings & Reflections": https://optimism.mirror.xyz/Bbu5M1mTNV2Z637QxOiF7Qt7R9hy6nxghbZiFbtZOBA
20. Optimism, "Retro Funding 2025": https://www.optimism.io/blog/retro-funding-2025
21. Optimism, Retro Funding 5 round details: https://gov.optimism.io/t/retro-funding-5-op-stack-round-details/8612
22. Chainalysis, "Dissecting the DAO": https://www.chainalysis.com/blog/web3-daos-2022/
23. Feichtinger et al., "The Hidden Shortcomings of (D)AOs": https://arxiv.org/abs/2302.12125
24. Protos, "Compound DAO asleep at the wheel…": https://protos.com/compound-dao-asleep-at-the-wheel-as-25m-governance-attack-passes/
25. DeSpread Research, Compound governance attack recap: https://research.despread.io/compound-finance-governance-attack/
26. Stanford Deliberative Democracy Lab, "What is Deliberative Polling?": https://deliberation.stanford.edu/what-deliberative-pollingr
27. Deliberative opinion poll, Wikipedia: https://en.wikipedia.org/wiki/Deliberative_opinion_poll
28. MIT Technology Review, "The simple but ingenious system Taiwan uses to crowdsource its laws" (2018): https://www.technologyreview.com/2018/08/21/240284/the-simple-but-ingenious-system-taiwan-uses-to-crowdsource-its-laws/
29. Computational Democracy Project, case studies: https://compdemocracy.org/Case-studies/
30. Anthropic & CIP, "Collective Constitutional AI": https://www.anthropic.com/research/collective-constitutional-ai-aligning-a-language-model-with-public-input
31. Good Judgment, "The Superforecasters' Track Record": https://goodjudgment.com/resources/the-superforecasters-track-record/
