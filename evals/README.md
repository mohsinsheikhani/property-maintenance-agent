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

Notes file: [labels.csv](./labels.csv).

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

Taxonomy file: [failure_taxonomy.md](./failure_taxonomy.md). I also keep [axial_raw_material.md](./axial_raw_material.md) as a scratch pad. Cross-trace patterns, hypotheses, and questions live there so the taxonomy itself stays clean.

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

File: [fix_vs_eval.md](./fix_vs_eval.md).

For `e2e-E12` (and the other Category 1 traces), the plan came out to:

- **Fix.** Edit the classify prompt with two rules together. First, the model must score urgency from physical facts only (active leak, smoke, smell, no heat or water, lock failure, and so on). Second, tenant tone is recorded in `tenant_sentiment` but never used to decide the tier. Lead with the rule, then give a few grounded examples. If I list only example tokens (CAPS, "!!!", "urgent"), the model will learn to ignore exactly those and still fall for the next tone signal a tenant invents.
- **Grader (ships first, before the prompt edit).** Code grader that compares `classify.urgency` against the expected label. Cheap and deterministic. It ships before the prompt change because under-tier on fire or flood is high-stakes. Building the grader upfront means the prompt edit is verified by the grader, not by re-reading traces and hoping.
- **Judge (deferred).** "Given the physical facts in this email, ignoring tone, is the tier the agent picked defensible?" Useful for the borderline cases where medium and high are both arguable. I cannot trust the judge until I validate it with TPR and TNR on a held-out set, and 20 labels is not enough. Revisit once the labelled set passes about 80 traces.

## Credits

The four step flow (open coding, axial coding, gulf attribution, fix vs evals) and the methodology behind it come from Hamel Husain's writing on AI Evals. The related work on the Three Gulfs (Shreya Shankar, David Okpare) builds on the same framing.

- Hamel: [Your AI Product Needs Evals](https://hamel.dev/blog/posts/evals/)
- Hamel: [LLM Evals FAQ](https://hamel.dev/blog/posts/evals-faq/)
- David Okpare: [A Primer to Evals](https://www.davidokpare.com/blog/a-primer-to-evals)
