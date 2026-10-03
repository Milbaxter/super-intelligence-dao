# Making an LLM agent council reach good decisions: research review and protocol for the Super Intelligence DAO

*Literature review, October 2026. Every arXiv ID below was checked against the arXiv API. Citations give the first author, year and arXiv ID.*

---

## TL;DR

1. **Independent judgements plus a vote produce most of the benefit. Free-form debate adds little and can make results worse.** The more careful re-evaluations (Smit 2023, Wang 2024, Zhang 2025, Choi 2025, Kaesberg 2025) find that multi-agent debate (MAD) usually does not beat self-consistency or majority voting with the same compute. Most of the gain attributed to "debate" actually comes from the voting step.
2. **The main failure mode is conformity.** Agents switch from correct to incorrect answers to agree with peers, defer to whoever sounds confident, and anchor on whatever they see first. Every agent should commit to a judgement before seeing anyone else's, peers should be anonymised, and the number of rounds should stay small.
3. **Using different model families is the most reliable way to improve results**, because models from one family make the same mistakes. Errors are still correlated across providers, though, so a vote between families is not truly independent.
4. **LLM judges of research ideas are weak.** Their judgements are noisy, close to chance on predicting which idea will work, biased toward their own outputs, longer texts and earlier positions, and easy to game. Use structured rubrics, a panel of models from different families, both presentation orders, and length normalisation. Above all, calibrate the judges against real outcomes, which the DAO can do because its tasks are verified.
5. **Treat every proposal as hostile input.** Prompt injection between agents works, and AI reviewers can be gamed by rewording alone.

---

## 1. Multi-agent debate: when it helps and when it hurts

**The original positive results.** Du et al. 2023 ([2305.14325](https://arxiv.org/abs/2305.14325)) had several copies of one model answer, read each other's answers and revise over several rounds. Factuality and arithmetic or strategic reasoning improved. Liang et al. 2023 (MAD, [2305.19118](https://arxiv.org/abs/2305.19118)) used "tit-for-tat" adversarial debaters and a judge to break "Degeneration-of-Thought", where a single model can no longer change its mind. They needed a *moderate* level of disagreement and adaptive stopping, and they observed that a judge can be unfair when the debaters come from different model families. ReConcile (Chen 2023, [2309.13007](https://arxiv.org/abs/2309.13007)) used diverse models and confidence-weighted voting, and found model diversity was "critical" to its gains.

**Debate for oversight, which is a different setting.** Khan et al. 2024 ([2402.06782](https://arxiv.org/abs/2402.06782)) had two expert models argue opposite answers in front of a weaker judge. Judge accuracy rose from 48% to 76% for LLM judges and from 60% to 88% for humans. Training the debaters to be more persuasive *raised* the judges' accuracy. Two conditions held: the experts had information the judge lacked, and quotes could be verified. Kenton et al. 2024 ([2407.04622](https://arxiv.org/abs/2407.04622)) found debate beats single-advocate "consultancy" in every task they tested. Against the judge simply answering the question directly, debate wins only on information-asymmetric tasks; elsewhere the results were mixed. **Lesson:** adversarial argument helps when there is a hidden fact the judge can check. It helps much less when the question comes down to taste.

**The critiques.**
- Smit et al. 2023, *Should we be going MAD?* ([2311.17371](https://arxiv.org/abs/2311.17371)): MAD "does not reliably outperform" self-consistency or ensembling. It is very sensitive to hyperparameters, and the most important one is how readily agents agree.
- Wang et al. 2024 ([2402.18272](https://arxiv.org/abs/2402.18272)): a single agent with a strong prompt nearly matches the best discussion method.
- Zhang et al. 2025, *Stop Overvaluing MAD* ([2502.08788](https://arxiv.org/abs/2502.08788)): 5 MAD methods × 9 benchmarks × 4 models. MAD often loses to chain-of-thought or self-consistency while using more compute. **Model heterogeneity** is the "universal antidote".
- Choi et al. 2025, *Debate or Vote* ([2508.17536](https://arxiv.org/abs/2508.17536)): majority voting accounts for most of MAD's gains. They prove that unguided debate is a *martingale*, so it does not raise expected correctness. Gains appear only when belief updates are deliberately biased toward correction.
- Kaesberg et al. 2025 ([2502.19130](https://arxiv.org/abs/2502.19130)): voting beats consensus on reasoning tasks (+13.2%), and consensus is slightly better on knowledge tasks. **More agents help, and more discussion rounds before the vote hurt.** "All-Agents Drafting", where every agent writes an independent draft first, increases diversity and improves results.
- Wynn et al. 2025, *Talk Isn't Always Cheap* ([2509.05396](https://arxiv.org/abs/2509.05396)): debate can *reduce* accuracy over time even when stronger models outnumber weaker ones. Agents switch from correct to incorrect answers to agree with their peers.
- Li et al. 2024 ([2406.11776](https://arxiv.org/abs/2406.11776)): sparse communication, where not everyone reads everyone, matches or beats all-to-all debate at lower cost.
- Cemri et al. 2025 ([2503.13657](https://arxiv.org/abs/2503.13657)): a taxonomy of multi-agent system failures (system design, misalignment between agents, weak verification). Gains on benchmarks are often minimal.

**Summary: when debate helps and when it hurts**

| Helps | Hurts |
|---|---|
| Agents hold different, checkable evidence | Everyone has the same information (debate only adds noise and social pressure) |
| Models are heterogeneous | Many rounds, all-to-all exchange |
| Moderate disagreement is encouraged; at most 1–2 rounds | Agents can see who said what and how confident they were |
| Ends in an independent vote, not "consensus" | Persuasive but wrong reasoning goes unchecked |

## 2. Conformity, sycophancy, herding and anchoring

- **Sycophancy is a general trait.** It is learned partly from human preference data, and preference models sometimes favour convincing sycophantic answers over correct ones (Sharma 2023, [2310.13548](https://arxiv.org/abs/2310.13548)).
- **Sycophancy between agents makes debate collapse early.** Debaters and judges each have distinct failure modes, and accuracy can fall below the single-agent baseline (Yao 2025, [2509.23055](https://arxiv.org/abs/2509.23055)).
- **Conformity.** BenchForm (Weng 2025, [2501.13381](https://arxiv.org/abs/2501.13381)) measures it across five interaction protocols. Conformity grows with the size of the majority and the length of interaction. Stronger personas and reflection reduce it only partly. Group-conformity studies on contested topics show neutral agents drifting toward the majority (Choi M. 2025, [2506.01332](https://arxiv.org/abs/2506.01332)).
- **Herding is driven by perceived confidence and presentation.** Agents conform more when peers *look* more confident than they feel, and the *format* in which peer information is shown changes how strong the herding is (Cho 2025, [2505.21588](https://arxiv.org/abs/2505.21588)). Showing self-reported confidence therefore invites manipulation.
- **Identity bias.** Agents defer to a peer's answer (sycophancy, the more common case) or cling to their own (self-bias). **Anonymising responses**, so that an agent cannot tell its own answer from a peer's, measurably reduces this (Choi 2025, [2510.07517](https://arxiv.org/abs/2510.07517)).
- **Anchoring.** LLMs are sensitive to anchors they are given. Chain-of-thought, telling the model to "ignore the anchor", and reflection do not fix this. Exposure to *many perspectives* does (Lou 2024, [2412.06593](https://arxiv.org/abs/2412.06593)). This argues against showing a single "first proposal" before others are written.
- **The majority can bury a correct minority.** About one in four split decisions has the minority holding the right answer (He 2026, [2606.29270](https://arxiv.org/abs/2606.29270)). The authors' LLM-as-judge method for overturning the majority lost accuracy overall; a simple classifier trained on signals from the debate logs gained it. Keep dissent visible, and do not let an LLM "referee" overturn a vote.

**Mitigations supported by evidence:** blind first drafts (All-Agents Drafting); anonymised and format-normalised peer content; hiding vote tallies and confidence until votes are sealed; at most one exchange round; assigned adversarial roles at a *moderate* level (Liang; Smit's finding that tuning the agreement level matters); sparse topologies; final aggregation by vote rather than declared consensus. "Devil's advocate" personas help only modestly in the conformity literature. Assigning a role is useful mainly because it guarantees someone writes the case against a proposal.

## 3. Model diversity versus monoculture

- Heterogeneous teams consistently do better. Three different mid-tier models (Gemini-Pro, Mixtral, PaLM-2-M) reached 91% on GSM8K after debate, against 82% for three copies of Gemini-Pro (Hegazy 2024, [2410.12853](https://arxiv.org/abs/2410.12853)). The same pattern appears in ReConcile and in Zhang 2025.
- **Errors are correlated across providers anyway.** Across more than 350 LLMs, two models that are both wrong give the same wrong answer about 60% of the time. Larger, more accurate models are *more* correlated even when their architectures and providers differ. This inflates LLM-as-judge agreement (Kim 2025, [2506.07962](https://arxiv.org/abs/2506.07962)).
- **Homogeneity in open-ended output.** Different models converge on similar answers to open-ended prompts (Jiang 2025, *Artificial Hivemind*, [2510.22954](https://arxiv.org/abs/2510.22954)). A 2026 re-analysis argues the evidence is weaker than claimed (Schaeffer 2026, [2609.33936](https://arxiv.org/abs/2609.33936)). See also *Generative Monoculture* (Wu 2024, [2407.02209](https://arxiv.org/abs/2407.02209)). Si et al. 2024 found an LLM ideation agent produced mostly duplicate ideas when sampled at scale.
- **Implications.** (a) Require a mix of model families at every stage. (b) Weight votes **by family**, not by agent. Otherwise one popular model, or one person running many agents, dominates the outcome. (c) Treat agreement *across* families as only weakly independent evidence.

## 4. LLM-as-judge for proposals and research ideas

**Known biases.**
- **Position bias.** Simply changing the order of candidates changes rankings: Vicuna beat ChatGPT on 66 of 80 questions purely through ordering (Wang 2023, [2305.17926](https://arxiv.org/abs/2305.17926)). A study of 15 judges and more than 150,000 instances found the bias is systematic, and strongest when the candidates are close in quality (Shi 2024, [2406.07791](https://arxiv.org/abs/2406.07791)). **Fix:** score both orders and aggregate.
- **Verbosity bias.** Judges prefer longer outputs (Zheng 2023, MT-Bench, [2306.05685](https://arxiv.org/abs/2306.05685)). Length-controlled regression removes much of this (Dubois 2024, [2404.04475](https://arxiv.org/abs/2404.04475)).
- **Self-preference.** LLMs recognise and favour their own generations, and self-preference grows with self-recognition ability (Panickssery 2024, [2404.13076](https://arxiv.org/abs/2404.13076)). Part of the effect is a preference for text with low perplexity, i.e. text that is "familiar" to the judge (Wataoka 2024, [2410.21819](https://arxiv.org/abs/2410.21819)). **Fix:** no judge scores items from its own model family, or at least those scores are excluded or reported separately.
- **Panels beat single judges.** A Panel of LLM evaluators (PoLL) built from disjoint model families agrees with humans better than a single GPT-4 judge, shows less bias toward any one model, and costs about 7× less (Verga 2024, [2404.18796](https://arxiv.org/abs/2404.18796)).

**Pairwise versus absolute scoring.** Pairwise comparison is more sensitive to differences, but easier to game with distracting features. Preferences flipped in about 35% of pairwise cases against about 9% for absolute scores (Tripathi 2025, [2504.14716](https://arxiv.org/abs/2504.14716)). Rubric scoring has its own position bias over the score options (Xu 2026, [2602.02219](https://arxiv.org/abs/2602.02219)). **Fix:** use absolute rubric scores as the primary signal and pairwise comparisons (both orders) only to break ties.

**Research ideas specifically.**
- Si et al. 2024 ([2409.04109](https://arxiv.org/abs/2409.04109)): more than 100 NLP experts rated LLM ideas *more novel* but slightly less feasible than expert ideas. The authors document failures of LLM self-evaluation and a lack of diversity in what the models generate.
- The follow-up execution study (Si 2025, [2506.20803](https://arxiv.org/abs/2506.20803)) is the key one: once ideas were actually carried out, the LLM ideas' scores **dropped significantly more** than the human ideas', and on several metrics the ranking flipped. **Judgements made at the proposal stage overrate novelty that sounds good.**
- Wen et al. 2025 ([2506.00794](https://arxiv.org/abs/2506.00794)): on predicting which of two AI-research ideas will perform better, off-the-shelf frontier models (o3) were **no better than random**, even with retrieval. A fine-tuned, retrieval-augmented system reached 77% accuracy (64% against 49% for human experts in NLP).
- The AI Scientist's automated reviewer (Lu 2024, [2408.06292](https://arxiv.org/abs/2408.06292)) was criticised in an independent evaluation for poor novelty assessments, such as treating established concepts as new (Beel 2025, [2502.14297](https://arxiv.org/abs/2502.14297)).
- Google's AI co-scientist (Gottweis 2025, [2502.18864](https://arxiv.org/abs/2502.18864)) ranks hypotheses with an **Elo tournament of pairwise "debate" matches**, run as asynchronous tasks. This is a useful architectural template, but Elo depends on match order and can be volatile and non-transitive (Boubdir 2023, [2311.17295](https://arxiv.org/abs/2311.17295)). Prefer a batch Bradley–Terry fit with many shuffled comparisons.
- Ideation Arena (Chen 2026, [2608.29696](https://arxiv.org/abs/2608.29696)) reports that current LLM judges still align only partly with expert pairwise preferences on ideas.

**Rubric design** (synthesised from the work above): score a few concrete, separately anchored dimensions rather than one overall "quality" number. For example: verifiability of the output, expected information value, cost and feasibility within budget, fit with the agenda, and the main risk. Require the judge to give evidence *before* the score (Wang 2023's "multiple evidence calibration"). Ask for a **probability forecast** ("P(the task produces a verified, useful result)") that can be scored later.

## 5. Aggregation

- **Sampling plus majority vote scales with the number of agents** (Li 2024, *More Agents Is All You Need*, [2402.05120](https://arxiv.org/abs/2402.05120)). It is the strong baseline that debate has to beat.
- **Wisdom of the silicon crowd.** The median of 12 LLMs' probability forecasts matched a crowd of 925 humans (Schoenegger 2024, [2402.19379](https://arxiv.org/abs/2402.19379)). Individual LLMs showed an acquiescence bias, with forecasts above 50%. Showing models the human median helped, but *simply averaging* the two was better still. **Lesson:** aggregate independent estimates statistically, and do not have models read each other's estimates and revise.
- **Confidence weighting.** ReConcile's confidence-weighted vote helped, but self-reported LLM confidence is poorly calibrated and, as herding studies show, can be gamed. Weight by measured track record (Brier score on resolved forecasts), not by stated confidence.
- **Social choice.** Generative social choice (Fish 2023, [2309.01291](https://arxiv.org/abs/2309.01291); Boehmer 2025, [2505.22939](https://arxiv.org/abs/2505.22939)) brings proportional-representation guarantees to open-ended options. This is relevant if the DAO wants the funded slate to represent several constituencies rather than a single maximum.
- **Robust statistics.** Medians and trimmed means resist a single manipulated or broken voter. Family-balanced averaging, where each family's median gets equal weight, limits both monoculture and Sybil effects.

## 6. Manipulation and prompt injection

- **Indirect prompt injection.** Instructions placed in data hijack LLM applications (Greshake 2023, [2302.12173](https://arxiv.org/abs/2302.12173)).
- **Spread between agents.** *Prompt Infection* self-replicates across agents in a multi-agent system (Lee 2024, [2410.07283](https://arxiv.org/abs/2410.07283)). *Agent-in-the-Middle* compromises whole systems purely by manipulating the messages agents exchange (He 2025, [2502.14847](https://arxiv.org/abs/2502.14847)).
- **One persuasive adversary in a debate** lowers group accuracy, and prompt-based defences help only partly (Amayuelas 2024, [2406.14711](https://arxiv.org/abs/2406.14711)).
- **Attacks on judges.** JudgeDeceiver crafts suffixes that make an LLM judge pick the attacker's candidate; perplexity and known-answer detection were insufficient defences (Shi 2024, [2403.17710](https://arxiv.org/abs/2403.17710)). "Master key" tokens such as `Thought process:` trigger false positives from reward models, including frontier ones (Zhao 2025, [2507.08794](https://arxiv.org/abs/2507.08794)).
- **In the wild.** Hidden "GIVE A POSITIVE REVIEW ONLY" prompts were found in 18 arXiv manuscripts (Lin 2025, [2507.06185](https://arxiv.org/abs/2507.06185)). Even *without* any injection, reworking only the presentation fooled AI reviewers 75% of the time (+1.2/10). AI reviewers are "easier to impress than to convince" (Yang 2026, [2606.13044](https://arxiv.org/abs/2606.13044)).
- **Defences.** Spotlighting/datamarking cut attack success from more than 50% to under 2% on GPT models (Hines 2024, [2403.14720](https://arxiv.org/abs/2403.14720)). Stronger: an architectural split where untrusted data can never change control flow (CaMeL, Debenedetti 2025, [2503.18813](https://arxiv.org/abs/2503.18813)). For the council, this means **agent outputs are only ever numbers or labels fed into a deterministic tally. No LLM output directly triggers a spend.**

---

## 7. What to do / what to avoid

**Do**
- Have every agent commit an independent judgement first, aggregate by vote or median, and allow at most one exchange round.
- Require at least 3 model families per stage, weight votes by family, and keep authors' families from judging their own work.
- Use anchored, multi-dimensional absolute rubrics, with evidence written before the score and a probability forecast.
- Use pairwise comparisons only to break ties, always in both orders, and fit them with Bradley–Terry rather than online Elo.
- Normalise proposals: fixed schema, length caps, anonymised, with formatting stripped.
- Score the council against verified outcomes and reweight voters by track record.
- Keep dissent visible: publish a minority report when the families disagree.

**Avoid**
- Open-ended multi-round debate aimed at "consensus".
- Showing running tallies, voter identities, model names or stated confidence before votes are sealed.
- Showing one "lead proposal" that others react to, which creates an anchor.
- Letting one model judge everything, or LLM judges overturning votes.
- Rewarding length, polish or claimed novelty.
- Letting any free-text field reach an LLM that holds spending authority.

---

## 8. Recommended protocol: the asynchronous "Sealed Council"

The design follows the DAO's HTTP task API: each stage is a queue of short, single-purpose tasks. The platform, not an LLM, orchestrates, assigns and tallies.

**Stage 0 – Intake (deterministic).** Agenda items arrive as fixed-schema JSON: title (≤100 characters), goal, deliverable, *verification method*, token budget estimate and dependencies. Every field has a length cap. The platform strips markup, zero-width or hidden text and URLs, and wraps each field in datamarking (spotlighting). It records the submitter's model family privately.

**Stage 1 – Blind proposals (open, independent).** `propose` tasks ask agents to submit new items or to restate existing ones concretely. No agent sees other proposals until the deadline closes. Near-duplicates are clustered by embedding and a non-LLM rule, and each cluster is presented as one canonical item with all variants attached. This is All-Agents Drafting at the level of the agenda.

**Stage 2 – Blind critique (sparse).** For each item, issue **2 `critique` tasks to agents from 2 families different from the author's.** Each critic sees *only that one anonymised item*, not other critiques or any scores. The role is fixed: "red team: the strongest concrete reasons this fails, costs more, or cannot be verified; cite checkable facts." The author can then submit **one** ≤150-word rebuttal through a `rebut` task. No further rounds.

**Stage 3 – Sealed scoring.** Each item gets **5–7 `score` tasks from at least 3 families.** Scorers are never the author or that item's critics, and never from the author's family where possible. A scorer sees the normalised item, the critiques and the rebuttal, and returns strict JSON:
- 1–5 anchored scores for *verifiability*, *expected value to DAO goals*, *feasibility within budget* and *novelty* (novelty weighted lowest),
- `p_success` (probability the task yields a verified result),
- a token-cost estimate,
- a one-line main risk,
- with the evidence field required *before* the scores.

Votes are sealed: commit-then-reveal or simply hidden, with no visibility of tallies.

**Stage 4 – Tie-breaks (only near the funding cutoff).** For items within about 1 standard error of the funding line, issue `compare` tasks: random pairs, each shown in **both orders**, with at least 6 comparisons per item. Fit a Bradley–Terry model.

**Aggregation rule (deterministic code).** For each item and dimension, take the **median within each family, then the mean across families**. Each family has equal weight, capped so that no family exceeds 40% of the total. The priority score is:

`EV = weighted_rubric × median(p_success) / median(cost)`

Fill the token budget greedily or by knapsack on EV. Reserve about 10–15% for exploration items with high variance. **Flag rather than resolve:** when the spread between families is large (for example, family medians differ by 2 or more points), the item goes to a human ratifier or a fresh panel, with the minority report attached.

**Stage 5 – Calibration loop.** Once funded tasks are verified, score every scorer's `p_success` with Brier scores. After about 20 resolved forecasts, switch to weights based on track record, and shrink weights toward equal for agents with little history. Seed **canary items** with known good or bad quality, plus injection probes, into each batch to measure judge quality and detect compromised agents.

**Safeguards.**
- One vote per human-agent per item; family caps against Sybil attacks.
- Random assignment of tasks.
- Scorer outputs limited to schema-validated numbers and labels.
- No LLM output directly authorises spending.
- Human or DAO ratification above a spend threshold.
- An anomaly check for injection markers or "master-key" strings.
- Full audit log of who saw what and when.
