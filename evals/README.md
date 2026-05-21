# Evals work for the property maintenance triage agent

This folder holds the eval work for the agent. The plan and the methodology come from Hamel Husain's writing on AI Evals. The links are at the end.

What follows is a short tour of the four steps I went through, with one example trace running through every step so the flow is easy to follow.

The example I use is `e2e-E12`. Subject: "FRIDGE EMERGENCY!!!!". Unit 8B. The body has no real diagnostic detail, just a panicked tenant.

## Open coding

Open coding is the part where I read the traces with no pre-built failure list in my head. The point is to see what the agent actually does on real inputs, not to confirm what I already think it does.

Two rules I follow when I am writing notes:

1. Write what happened, never why. A note should describe what the agent returned on a specific span. It should not explain why the model behaved that way. If I write the "why" too early, it turns into a sticky hypothesis that biases every next trace I read. Causal reasoning belongs in step 4 (axial coding) and step 5 (gulf attribution), not here.

2. Attribute the failure to the first span whose output is wrong. Errors cascade across the graph, so if I label the failure on the last visible symptom I will end up trying to fix a span that worked fine on its own. The test I use: if I feed the next span corrected input, does the failure go away? If yes, the upstream span is the real bug.

The output of this step is not really the notes. It is the distribution of where failures land. After enough traces I should be able to say something like "60% of failures start at classify, 25% at route, 15% at extract." That distribution is what tells me which component to attack first.

Notes file: [error_analysis/round_1/trace_labels.csv](./error_analysis/round_1/trace_labels.csv).

For `e2e-E12`, my note was:

> `classify.urgency='high'; expected 'medium'. Body has no temperature reading, no timeline, no spoiled-food evidence, no specific failure symptom. Body language: ALL CAPS, '!!!!!', 'PLEASE', 'EMERGENCY', 'fridge is dying', 'everything will go bad'. category='appliance' correct, unit=8B correct.`

`first_failed_span` is `classify`. Notice the note does not say "the model overweighted angry tone". It only says what is in the email and what the agent returned. The "why" comes later.

## Axial coding

Once I have read enough traces and written observations, the next step is to group similar observations into named categories. This is where the failure taxonomy comes from.

For each category I capture:

- **Name.** Describes the behavior, not the cause. `urgency_from_tone_not_facts` is fine. `tone_bias` is too cause-shaped.
- **Definition.** One observable sentence. "Agent assigns urgency that does not line up with the physical facts in the email."
- **Exemplars.** Three or more trace IDs.
- **Prevalence.** The percent of the dataset.
- **Gulf tag.** One letter (C, S, G). This is a hypothesis at this stage. It gets refined in the next step.
- **Grader tag.** Code or judge.

Rules I keep:

- Still no "why". Cause belongs in step 5.
- Split categories when the fix would be different. Deflation and inflation are two modes if the fixes are different.
- Each trace belongs to exactly one category.
- Aim for 5 to 10 categories. Less than 5 is too broad. More than 10 means I have over-split and the buckets are too small to act on.

Taxonomy file: [error_analysis/round_1/failure_taxonomy.md](./error_analysis/round_1/failure_taxonomy.md). I also keep [runs/axial_raw_material.md](./runs/axial_raw_material.md) as a scratch pad. Cross-trace patterns, hypotheses, and questions live there so the taxonomy itself stays clean.

For `e2e-E12`, the trace landed in Category 1 (`urgency_from_tone_not_facts`). The other traces in that category are E01, E07, E14, E04, E03, T12. Seven traces out of twenty, so prevalence is 35%.

## Gulf attribution

The "three gulfs" idea comes from Hamel's writing (with Shreya Shankar and David Okpare). Each failure category sits in one of three gulfs, and the gulf tells me what kind of fix the failure needs.

- **Comprehension** (me and the data). I do not know what the system actually does on real inputs. Fix: read more traces.
- **Specification** (me and the prompt). The prompt does not say what I think it says. Fix: rewrite the prompt.
- **Generalization** (the data and the pipeline). Even with a perfect prompt the model cannot do the thing reliably across the full distribution of inputs. Fix: architecture change (task decomposition, retrieval, fine-tune).

The diagnostic question I ask: if I rewrite the prompt to explicitly forbid this failure, would the model now succeed reliably across the input distribution?

- Yes: Specification.
- Helps sometimes, still fails on hard cases: Generalization.
- I do not even know what the prompt says today: Comprehension. Go read.

For `e2e-E12` I tagged the gulf as Specification, with a small Generalization tail. The reasoning:

The classify prompt does not have a rule that separates tenant tone from physical severity. If I add that rule (urgency comes from physical facts only, tone is recorded but not used) the case becomes easy. There are no physical facts in the email that justify "high", so the answer should be medium. That fits Specification.

The hedge: traces E10 and T05 show the model can already calibrate from facts when the language is vivid enough (E10 had a burning smell, T05 had a calm tenant with a minor problem). So the model has the capability. A pure Specification fix should land most of the failures, but borderline phrasing like E03's "small sparking" with hedges will probably still slip through. That tail is Generalization, and a judge is what catches it later.

## Fix vs evals

This is the highest leverage step. For each category I decide one of four things:

1. **Just fix the prompt.** If the gulf is Specification, rewrite the prompt. Many categories die here.
2. **Just fix the code.** Sometimes the "LLM failure" is a normal code bug (a wrong SQL filter, a bad schema, a None slipping through).
3. **Add a grader.** Only if the failure will come back or the stakes are high. Code grader first. Judge only for subjective things (urgency justified by facts, tone, faithfulness).
4. **Out of scope.** Name it and park it. Saying out-of-scope is a real decision. Silently ignoring is not.

One ordering rule I follow: for high-stakes categories, the code grader ships before the prompt fix. That way the fix is verified by the grader instead of being hoped to work. For lower-stakes categories I fix first and add a grader only for the part that did not go away.

Across categories I prioritize by `Frequency × Feasibility`. Feasibility is a rough number from 0.0 to 1.0 (0.9 to 1.0 is trivial, 0.7 to 0.8 is hours of work, 0.5 to 0.6 is days, 0.3 to 0.4 is uncertain, 0.0 to 0.2 is unknown cause).

File: [error_analysis/round_1/fix_vs_eval.md](./error_analysis/round_1/fix_vs_eval.md).

For `e2e-E12` (and the other Category 1 traces), the plan came out to:

- **Fix.** Edit the classify prompt with two rules together. First, the model must score urgency from physical facts only (active leak, smoke, smell, no heat or water, lock failure, and so on). Second, tenant tone is recorded in `tenant_sentiment` but never used to decide the tier. Lead with the rule, then give a few grounded examples. If I list only example tokens (CAPS, "!!!", "urgent"), the model will learn to ignore exactly those and still fall for the next tone signal a tenant invents.
- **Grader (ships first, before the prompt edit).** Code grader that compares `classify.urgency` against the expected label. Cheap and deterministic. It ships before the prompt change because under-tier on fire or flood is high-stakes. Building the grader upfront means the prompt edit is verified by the grader, not by re-reading traces and hoping.
- **Judge (deferred).** "Given the physical facts in this email, ignoring tone, is the tier the agent picked defensible?" Useful for the borderline cases where medium and high are both arguable. I cannot trust the judge until I validate it with TPR and TNR on a held-out set, and 20 labels is not enough. Revisit once the labelled set passes about 80 traces.

## Validating the urgency judge

The judge from the last step is only worth running if it agrees with me. So before I trust its Pass/Fail in any gate, I check how often it matches a human read. That human is me, labelling each case by hand.

The thing being graded is a pair: an email, and the urgency the agent picked for it. The judge looks at that pair and says whether the pick is defensible. My label answers the same question. Note this is not "did the pick match the expected tier". That comparison is what the exact match code grader already does. The judge exists for the cases where the pick is not equal to the expected tier but is still defensible, so the label has to be my defensibility call, not a string compare.

The labelled corpus is 100 records, split the way the validate-evaluator skill lays out: a small training slice for few shot examples, a dev split to iterate against, and a test split held back for one final measurement. `dev.jsonl` is the 45 record dev split, so that is what I validate against here.

I did not invent the picks. For the first 20 records I pulled them from the round 1 run, before any of the prompt fixes landed. That run over escalated a lot, so it handed me real Fail cases without my having to fabricate wrong tiers. For the rest of the dev split I ran the current classify node and used what it actually produced, which after the fixes is mostly defensible, so those records are mostly Pass. Across the whole dev split, 9 records have no urgency to rate (prompt injection, non maintenance mail, one word bodies). That leaves 36 pairs, 22 Pass and 14 Fail.

Labels: [validation/urgency_judge_labels.csv](./validation/urgency_judge_labels.csv). Harness: [validation/validate_urgency_judge.py](./validation/validate_urgency_judge.py).

The first run on the full set came out at **TPR 90%, TNR 53%**. The TPR was fine, the TNR was bad: the judge was missing most of the over and under tiering I had flagged. Reading the disagreements I almost convinced myself the judge was the consistent one and my labels were the mess. Then I went back to `classify.md`, the actual urgency rules the agent runs on, and checked every disagreement against it. That flipped the story.

My labels were mostly anchored in the prompt's own examples. The judge was the one off-spec. The judge prompt only knew how to fail a tone-driven tier (high because of ALL CAPS and "emergency"). It had no rule for a tier that is just plain wrong on the facts. So when classify says "a noisy appliance that still works" is low and the agent picked medium for a rattling AC, the judge had nothing to fail it with and passed it. Same for a slow drip into a cabinet (the rules call that forward-only medium, the judge let low slide) and for a vague no-fact email (the rules say low, do not default to medium, the judge passed medium). Only one of my own labels actually moved in this pass: I had allowed `high` for no hot water with cold still running, but that is not in the prompt's high list, so it became a Fail.

The fix was not more relabelling. It was making the judge grade against the same rubric as classify. I pulled the specific low examples (noisy-but-works, dead bulb), the immediate-vs-forward-only split, the no-concrete-fact rule, and the habitability examples into the judge prompt, and I broadened the Fail definition to cover a calm severity misread, not just a tone-driven one. I added three fresh few shot examples for the boundaries the judge kept missing, authored from scratch so they do not overlap the dev records and leak. I also pinned the model to `gpt-4o-2024-08-06`, because mid-iteration the judge was flip-flopping its verdict on the same input between runs even at temperature 0.

After that, the dev split came out at **TPR 95%, TNR 93%**, both over the 90% bar.

One thing I am being honest about: these are dev-split numbers, which the skill warns are optimistic because the judge was tuned against them. The clean move would be one final run on a held-out test split. I have not carved that split out here, so 95 and 93 are a dev result, not a calibrated final number. This repo is a high level portfolio piece on how I approach evals. The fuller version of this work, with a proper train, dev and test split run against a customer supplied dataset, was done on the actual customer project. For this portfolio version I am treating the dev result as good enough to trust the judge in the component eval, and the validation run stays checked in so the number can be re-measured whenever the judge prompt or model changes.

## Regression gate

Once a grader exists, the next failure it should catch is my own next change. That is what the regression gate is for: it runs the graders on every pull request and blocks the merge if a code grader drops more than I allow.

The gate runs the component evals, not the full graph. The nodes are pure functions of state, so classify, extract and pre_filter run with nothing but an OpenAI key. The wired graph needs the MCP server, Neon and the checkpointer, and it writes only to Langfuse, so there is no scoreboard for CI to diff. I run that one by hand. The honest tradeoff is that this gate proves each node still behaves, not that the assembled pipeline does. The e2e sweep stays a manual job.

The shape follows the Agent Factory regression model: one pass-rate per grader (the per-criterion view), plus an overall code-grader rate. A change is a regression if any single code grader drops more than 10%, or the overall code rate drops more than 5%. Those two thresholds are the whole gate. Code graders block. The two judges are report-only: their pass-rate is a biased, slightly noisy number, so I show its delta in the PR output but never let it fail a build. That matches the validate-evaluator skill, which treats a raw judge rate on unlabeled data as something to correct, not to trust as-is.

The baseline is a scoreboard checked into the repo at [baseline.json](./baseline.json), regenerated on `main` with `uv run python -m evals.run_evals --update-baseline`. A PR diffs against it. To stop a branch from quietly moving its own goalposts, the CI job reads the baseline from `main` (`git show origin/main:evals/baseline.json`) rather than the copy on the branch, so the reference line is always `main` HEAD. The gate has real teeth only once it lives on `main`; until then it runs and reports but there is no merged baseline behind it.

The first baseline, run on the 48 record dev split, came out like this. These are a snapshot from when I built the gate; the live numbers are always in [baseline.json](./baseline.json), this table is just so the result is readable here.

| Grader | Type | Pass rate |
| --- | --- | --- |
| `pre_filter.decision.exact_match` | code | 98% (47/48) |
| `classify.risk_flags.precision` | code | 95% (39/41) |
| `classify.not_a_maintenance_request.exact_match` | code | 92% (44/48) |
| `classify.risk_flags.recall` | code | 80% (33/41) |
| `classify.urgency.exact_match` | code | 67% (24/36) |
| `classify.urgency.judge_defensible` | judge (report-only) | 78% (28/36) |
| `extract.tenant_sentiment.judge_defensible` | judge (report-only) | 100% (1/1) |
| **overall code rate** | | **87%** |

The one I am not hiding is urgency exact match at 67%. That is the hardest call in the pipeline and the lowest grader, which is the point: the gate protects me from regressing below 67%, and the number itself is the honest next thing to improve. A suite sitting at 100% green would mean the cases are too easy, not that the agent is perfect.

Runner: [run_evals.py](./run_evals.py). Workflow: [../.github/workflows/evals.yml](../.github/workflows/evals.yml).

## Credits

The four step flow (open coding, axial coding, gulf attribution, fix vs evals) and the methodology behind it come from Hamel Husain's writing on AI Evals. The related work on the Three Gulfs (Shreya Shankar, David Okpare) builds on the same framing.

- Hamel: [Your AI Product Needs Evals](https://hamel.dev/blog/posts/evals/)
- Hamel: [LLM Evals FAQ](https://hamel.dev/blog/posts/evals-faq/)
- David Okpare: [A Primer to Evals](https://www.davidokpare.com/blog/a-primer-to-evals)
