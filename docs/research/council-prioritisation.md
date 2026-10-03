# Agenda-setting for Super Intelligence DAO: deciding what research is worth the tokens, and checking afterwards

*Research note, 2026-10-03. Sources were fetched directly with curl because WebSearch/WebFetch were down. Where the fetch failed (e.g. Smith & Winkler 2006), the citation is a standard bibliographic reference.*

## 0. The problem in one paragraph

Today the server makes a task whenever an artifact has no claims. Its priority is the track weight times a staleness bonus. That rule has no idea whether a task family **applies** to an artifact: a protocol has no benchmark scores to extract. It also cannot tell whether the output would **change anything**, or whether past tasks of that kind **produced verified, used claims**. The rest of this note looks at how other organisations handle the same three questions (is it valuable, does it fit, did it work) and turns what they do into a template, a set of metrics, an allocation rule and a review loop.

---

## 1. Findings

### 1.1 Prioritisation frameworks

**Importance / tractability / neglectedness (ITN).** 80,000 Hours splits "good done per extra unit of resources" into three factors: Scale, Solvability and Neglectedness. Their product gives back marginal cost-effectiveness. Each factor is scored on a **logarithmic** scale so the scores can be added instead of multiplied. They justify neglectedness with **diminishing returns**: "people take the best opportunities for impact first." They also warn that defining a problem broadly or narrowly can move its score a lot ([80,000 Hours, "A framework for comparing global problems"](https://80000hours.org/articles/problem-framework/)). *Takeaway for SIDAO:* score per **track × task family**, not per track. A family like "benchmark extraction" has near-zero solvability on protocol artifacts no matter how important the protocol track is. Neglectedness maps directly onto coverage: how many verified claims already exist for that cell.

**Expected value of information (EVI).** In decision theory, information is worth only the expected improvement in the decision it informs. Information that cannot change any decision is worth nothing ([Wikipedia, "Value of information"](https://en.wikipedia.org/wiki/Value_of_information)). LMArena applies this to measurement. Instead of showing random model pairs, it "actively chooses which model pairs to show" so the rankings converge faster with fewer votes ([Chiang et al., Chatbot Arena, arXiv:2403.04132](https://arxiv.org/html/2403.04132v1)). Folding@home does the same with compute. Its adaptive sampling restarts simulations from newly found states, so compute goes where uncertainty is highest, and it gives bonus points for work units with "greater scientific priority" ([Wikipedia, Folding@home](https://en.wikipedia.org/wiki/Folding@home)). *Takeaway:* a claim is worth more when the map has a real question it answers, for example "is open model X ahead of Y on agentic coding?". It is worth little when it only fills an empty cell.

**Cost-effectiveness estimates and the optimizer's curse.** If you pick the option with the highest *estimated* value, its realised value will on average fall short of the estimate, even when every estimate was unbiased. That is the optimizer's curse. The fix is Bayesian shrinkage: pull noisy estimates toward a prior ([Smith & Winkler, "The Optimizer's Curse", *Management Science* 52(3), 2006, doi:10.1287/mnsc.1050.0451](https://doi.org/10.1287/mnsc.1050.0451); summary at [LessWrong](https://www.lesswrong.com/posts/5gQLrJr2yhPzMCcni/the-optimizer-s-curse-and-how-to-beat-it)). GiveWell argues that explicit expected-value formulas "with significant room for error" should not be taken literally unless Bayesian adjustments are applied ([GiveWell blog, 2011](https://blog.givewell.org/2011/08/18/why-we-cant-take-expected-value-estimates-literally-even-when-theyre-unbiased/)). Open Philanthropy, now Coefficient Giving, says it suspects "our models and intuitions are more often optimistic than pessimistic" ([Hits-Based Giving](https://www.openphilanthropy.org/research/hits-based-giving/)). *Takeaway:* the most enthusiastic proposal each cycle is probably overestimated. Shrink proposers' yield forecasts toward the track's historical base rate, and require a pilot before scaling.

**Portfolio and diversification.** Coefficient Giving practises "worldview diversification" for three reasons: diminishing returns within any one area, **option value** ("better positioned to redirect resources quickly"), and protection against blind spots ([Worldview Diversification](https://www.openphilanthropy.org/research/worldview-diversification/)). Its hits-based giving accepts many failures in exchange for a few large wins ([Hits-Based Giving](https://www.openphilanthropy.org/research/hits-based-giving/)).

**Explore/exploit: multi-armed bandits and Thompson sampling.** Thompson sampling handles the trade-off between "exploiting what is known to maximize immediate performance" and "investing to accumulate new information." For each arm it samples from the posterior and plays the arm whose sample is best ([Russo et al., "A Tutorial on Thompson Sampling", arXiv:1707.02038](https://arxiv.org/abs/1707.02038); [Wikipedia, Thompson sampling](https://en.wikipedia.org/wiki/Thompson_sampling); [Wikipedia, Multi-armed bandit](https://en.wikipedia.org/wiki/Multi-armed_bandit)). The fit here is close: task families are arms, a token batch is a pull, and verified-value-per-token is the reward. Two things differ from the textbook case. Rewards are **non-stationary**, because a family's yield falls as its cells fill up. And rewards are **delayed**, because verification and downstream use lag. So use a discounted or sliding-window posterior, and score on verification-time reward instead of submission-time reward.

### 1.2 How research funders and open-source projects set agendas

**The ARPA model.** Azoulay et al. name the key elements as "organizational flexibility" and "significant authority given to program directors to design programs, select projects and actively manage projects." They place it in "mission-oriented research on nascent S-curves" ([NBER w24674, 2018](https://www.nber.org/papers/w24674)). DARPA's **Heilmeier Catechism** is the standard proposal test. It asks: What are you trying to do, with no jargon? How is it done today, and what are the limits? What is new? Who cares? What are the risks? How much will it cost? How long will it take? What are the mid-term and final "exams"? ([DARPA](https://www.darpa.mil/about/heilmeier-catechism)). *Takeaway:* give each track a named **steward** with real authority over it, the way a program manager has, and require a Heilmeier-style proposal to open or expand one.

**Convergent FROs and Astera.** FROs are "time-bound", pursue "pre-specified, quantifiable technical milestones" with "external reviews", and build public goods such as "tools, datasets, and scientific infrastructure" ([Convergent Research, About FROs](https://www.convergentresearch.org/about-fros)). Astera picks a few focus areas it expects to "be important in most potential futures" and runs them in-house ([astera.org](https://astera.org/)). *Takeaway:* tracks should be time-boxed, with milestones and sunset dates set in advance, not open-ended.

**Open-source proposal processes.**
- **Kubernetes KEPs** have these sections: Summary, Motivation, **Goals, Non-Goals**, Proposal, Risks and Mitigations, Test Plan, **Graduation Criteria** (alpha → beta → GA), Production Readiness and **Monitoring Requirements**, Drawbacks, **Alternatives**, and Implementation History ([KEP template](https://github.com/kubernetes/enhancements/blob/master/keps/NNNN-kep-template/README.md)).
- **Rust RFCs** have Summary, Motivation, explanations at guide level and reference level, Drawbacks, **Rationale and alternatives**, **Prior art**, Unresolved questions and Future possibilities. The README warns that RFCs that are "disingenuous about the drawbacks or alternatives tend to be poorly-received" ([template](https://github.com/rust-lang/rfcs/blob/master/0000-template.md), [README](https://github.com/rust-lang/rfcs/blob/master/README.md)).
- **Python PEPs** add **Rejected Ideas**, recorded "to prevent people from bringing up the same rejected idea again" ([PEP 1](https://peps.python.org/pep-0001/)).

*Takeaway:* "Non-goals", "graduation criteria" and "rejected ideas" are the fields that would have stopped the protocol-benchmark tasks.

**Wikipedia WikiProjects.** Each project rates articles on two independent axes: **quality** (Stub → FA) and **importance** (Top/High/Mid/Low, plus "NA" for pages where assessment does not apply). Importance is set by each project, "ideally" using a bespoke scale with **exemplars**. The WP 1.0 bot then tabulates the importance × quality matrix ([Assessment](https://en.wikipedia.org/wiki/Wikipedia:Version_1.0_Editorial_Team/Assessment); [WikiProject Medicine/Assessment](https://en.wikipedia.org/wiki/Wikipedia:WikiProject_Medicine/Assessment)). Release selection used rules over that grid, for example "B-Class articles of high importance or higher" ([Release Version Criteria](https://en.wikipedia.org/wiki/Wikipedia:Version_1.0_Editorial_Team/Release_Version_Criteria)). *Takeaway:* this is very close to the right data model for the map. The **NA importance class** is exactly the "this family doesn't apply to this artifact" flag that is missing today.

**HOT Tasking Manager and Zooniverse.** The HOT/OSM Tasking Manager splits a mapping job into small tasks and "shows which areas need to be mapped and which areas need the mapping validated." Admins set a project priority and **priority areas**, and every description must say "why the project exists, who will use the data" ([OSM Wiki](https://wiki.openstreetmap.org/wiki/Tasking_Manager); [LearnOSM admin guide](https://learnosm.org/en/coordination/tasking-manager3-project-admin/)). Zooniverse makes projects pass a beta review. Teams must confirm their "retirement limit" (how many classifications retire a subject) and check that beta results "are of sufficient quality for your research" before launch ([Zooniverse policies](https://help.zooniverse.org/getting-started/lab-policies/)). *Takeaway:* name the data consumer, and run a pilot with a quality gate before a family gets full volume.

**Benchmark organisations deciding what to measure.** METR chose a metric, task-completion time horizon, because it supports **forecasts**: it found that horizon "doubled approximately every 7 months for 6 years" ([METR](https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/)). Epoch AI runs a benchmarking hub and a composite Capabilities Index ([Epoch AI](https://epoch.ai/benchmarks)). There are known risks. The "benchmark lottery" paper finds construct-validity problems when a few benchmarks stand in for general progress ([arXiv:2111.15366](https://arxiv.org/abs/2111.15366)). A meta-review of about 100 studies lists contamination, poor documentation and "failures to distinguish signal from noise" ([Eriksson et al., arXiv:2502.06559](https://arxiv.org/abs/2502.06559)). *Takeaway:* decide what to measure based on what it lets someone predict or decide, and weight claims by the quality of the benchmark they cite.

### 1.3 Metrics and Goodhart

Campbell's law: "The more any quantitative social indicator is used for social decision-making, the more subject it will be to corruption pressures" ([Wikipedia](https://en.wikipedia.org/wiki/Campbell%27s_law)). Manheim & Garrabrant describe four ways that over-optimising a metric fails: regressional, extremal, causal and adversarial ([arXiv:1803.04585](https://arxiv.org/abs/1803.04585)). All four apply here:
- **Regressional:** the optimizer's curse on yield forecasts.
- **Extremal:** families that look great at small scale and fall apart at large scale.
- **Causal:** page views driven by promotion instead of usefulness.
- **Adversarial:** agents splitting one claim into five, or farming easy cells.

The KEP template's "Monitoring Requirements" and Zooniverse's quality gate both show that an organisation needs **leading** indicators (acceptance rate, cost per verified claim) that it can act on within a cycle. Those must be checked against **lagging** indicators (reuse, citations, replication) that are harder to game.

### 1.4 Making decisions legible

Nygard's ADRs are short records with five fields: Title, **Context** ("forces at play… value-neutral"), **Decision** ("We will…"), **Status** (proposed / accepted / deprecated / superseded), and **Consequences**. He keeps them small because "large documents are never kept up to date" and because the hardest thing to recover later is "the motivation behind certain decisions" ([Nygard 2011](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions); [adr.github.io](https://adr.github.io/)). The WP 1.0 bot's public matrix and the Tasking Manager's progress maps show the value of a dashboard **everyone sees the same way**.

---

## 2. Recommendations

### (a) Track/task-family proposal template

One markdown file per proposal, stored in the repo. When accepted it is linked from an ADR. Required fields are marked R.

| Field | Content | Source of idea |
|---|---|---|
| R **Title, ID, steward** | One named owner with authority over the track | ARPA PM |
| R **Question (no jargon)** | What question in the map does this answer? Who is asking it? | Heilmeier; HOT "who will use the data" |
| R **Consumer** | The named reader, page or API, or the downstream decision that will use the output | HOT, METR |
| R **Applicability rule** | Which artifact types or layers the family applies to, as a machine-checkable predicate. Everything else is **NA** | WikiProject NA class |
| R **Non-goals** | What is explicitly out of scope, e.g. "no benchmark extraction for protocols/specs" | KEP |
| R **Unit of output & verification** | What one accepted output looks like, how it is verified (re-fetch, second agent, replication), and the dispute window | Zooniverse retirement limit |
| R **Scale / gap / tractability** | Number of in-scope artifacts by importance tier; current coverage (matrix cells empty / stub / verified); expected acceptance rate | ITN, log scales |
| R **Forecast** | Predicted tokens per verified claim, acceptance rate, and claims per cycle, given as an 80% interval | Pre-registration, for calibration |
| R **Pilot budget & graduation criteria** | Pilot cap (e.g. ≤2% of the cycle). Thresholds to go pilot → scaled → maintenance → retired | KEP graduation, Zooniverse beta |
| R **Kill criteria / sunset date** | The conditions that stop the family, and when it ends by default | FRO time-boxing |
| R **Alternatives & rejected ideas** | Including "do nothing" and "fold into an existing family" | Rust RFC, PEP |
| Risks / Goodhart vectors | How agents could game it, and the counter-measure | Manheim & Garrabrant |
| Prior art | Existing datasets (Epoch, LMArena, papers) this duplicates or links to | Rust RFC |

### (b) Evidence and yield metrics the server should compute each cycle

Compute these per **track × task family** and show them on a single council dashboard, with the previous cycle and the forecast next to each value.

**Leading indicators (act on these this cycle)**
1. **Tokens spent** and **share of the cycle budget**.
2. **Acceptance rate** = verified / submitted. Also **rejection rate**, **dispute rate** (accepted and later challenged), and **overturn rate** (dispute upheld).
3. **Tokens per verified claim**. Also **value-weighted yield** = Σ claim value / tokens. Claim value = importance tier weight of the artifact × gap weight (1.0 for a previously empty cell, 0.3 for a corroborating source, 0 for a duplicate) × source-quality weight (primary paper or model card > leaderboard > blog).
4. **Applicability miss rate**: the share of tasks closed as "not applicable / no such data". This is the alarm that would have caught the protocol problem in the first cycle.
5. **Matrix coverage delta**: movement on the importance × coverage grid, with the WP 1.0 table as the model. Example: "Top-importance artifacts with ≥1 verified claim: 41% → 58%."
6. **Remaining in-scope supply**: the number of cells still open. This is the neglectedness term, and it shows when a family is running dry.

**Lagging indicators (judge these 1–3 cycles later)**
7. **Reads**: map page views and API reads of the claims a family produced, with bots excluded and normalised per claim.
8. **External use**: inbound links and citations of the map, and claims reused as inputs by later harness or eval tasks.
9. **Durability**: the share of claims still standing after N cycles, i.e. not superseded as wrong.
10. **Spot-audit precision**: a steward or independent agent re-verifies a **random** 5% sample of accepted claims. This is the main anti-Goodhart check, because it does not depend on the submitter's own verification path.

**Council calibration**
11. For each accepted proposal, compare forecast against actual tokens per claim and acceptance rate, and keep a **Brier or interval-coverage score** for each proposer and steward. Over time this shows whose forecasts deserve trust.

### (c) Combining council votes with an explore/exploit split

Split the cycle's token budget into three parts:

- **~70% directed (council).** The council votes on track weights, using approval or score voting on the proposal set. The council's weight is then **multiplied by shrunk evidence**, not used alone:
  `alloc_i ∝ council_weight_i × E[value-weighted yield_i | posterior]`
  The posterior combines the family's observed yield (discounted, e.g. half-life of 2 cycles) with a prior equal to the median yield across all families. That shrinkage is the optimizer's-curse correction. Cap any one family at ~30% of the directed budget for diversification and option value, and floor every accepted track at a maintenance level so freshness work keeps going.
- **~20% adaptive (Thompson sampling).** At each task-batch dispatch, draw a value-per-token sample from each eligible family's posterior and send the batch to the highest draw. Model it as Beta(accepts, rejects) × a value distribution, discounted for non-stationarity. This moves tokens toward families that are actually yielding *within* a cycle, without waiting for the next vote. Counts are reward only **after verification** to handle the delay.
- **~10% exploration (pilots).** This share funds new proposals at pilot scale (≤2% each) under their graduation criteria, plus a little random sampling of NA-flagged cells to check the applicability rules. Any member can file a proposal; the steward triages it, as Rust sub-teams do. A pilot graduates only if it meets its *pre-registered* criteria.

Start with roughly 60/20/20 while the map is young and priors are weak. Move toward 75/15/10 as yield data builds up. Write each split into that cycle's ADR.

### (d) Judging outcomes next cycle

1. **Pre-register.** Each accepted proposal's forecast and graduation and kill criteria are frozen in its ADR before tokens flow.
2. **Retro at cycle close.** The server writes up each family's forecast vs actual on metrics 2–6. The steward adds a short **Consequences** note to the ADR (what happened, and what it changes). Status then becomes *continue / scale / revise / retire*.
3. **Judge the decision as well as the outcome.** A pilot that failed with an honest forecast and cheap kill criteria counts as a good decision, in hits-based terms. Repeated over-forecasting by the same proposer lowers the prior on their future proposals through metric 11.
4. **Look back at lagging metrics.** One and three cycles later, check reads, reuse, durability and audit precision for each family. A family with high leading yield and near-zero reads or reuse is a Goodhart signal. Demote it even if its acceptance rate looks good.
5. **Rotate the headline metric.** No single number decides allocation. Show the council the full panel, keep the spot-audit sample secret until it closes, and change the source-quality and gap weights through ADRs, never silently.
6. **Publish everything.** The proposal files, ADRs, the dashboard and the importance × coverage matrix are public pages on the map site, so donors can see what their tokens bought and why.
