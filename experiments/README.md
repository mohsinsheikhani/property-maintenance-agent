# Experiments

This folder is where I try things that might not work. It is kept separate from `agent/` and `evals/` on purpose, so a dead end here never touches the real pipeline.

So far there is one experiment: testing whether DSPy is a good fit for this project.

## Why I looked at DSPy

The agent runs on hand written prompts. The `extract` prompt alone is about 1,300 tokens of rules. DSPy's pitch is that you write a short signature instead of a long prompt, hand it a labelled dataset, and let an optimizer discover the wording for you. If that worked, it would replace a lot of prompt tuning with measurement.

I wanted to know if that pitch holds on this project, so I ran it on two nodes.

## extract: not testable

I started on the `extract` node and stopped before running an optimizer.

The problem is grading. DSPy's optimizer is only as good as the metric it optimizes against, and the fields that matter in extract cannot be graded by code. `location` can be "kitchen" or "under the sink" or "garbage disposal" and all three are right. `description` can be half a line or two lines depending on the email, and both are fine. There is no single correct string to compare against.

To grade those fields I would need a validated LLM judge, which is real work, and the fields that *can* be graded by code (unit number, phone, the missing-fields gate) the model already gets nearly right. So there was nothing for an optimizer to win. I wrote up the scaffolding in `dspy_extract/` and left it there as a record, but it never ran an optimization.

## classify: testable, and DSPy did not help

`classify` was the better candidate. Every field is a closed set: category is one of seven labels, urgency is one of three, risk flags come from a fixed four, and not-a-maintenance is a yes or no. All of that can be graded with plain code, no judge needed. So this was a fair test.

The work is in `dspy_classify/`. The flow followed the same rule as the rest of the project: run, look, then grade. I ran the lean signature, read every miss by hand, and only trusted the numbers after that.

Reading the misses turned up something more useful than any optimizer result. Of the 21 urgency misses, about half were not model errors at all. They were wrong labels in the dataset. A dripping tap labelled low when the rules make it medium, a no-hot-water email labelled medium when the rules make it high, and so on. The risk-flag misses had two bad labels too. I fixed 13 labels in `dev.jsonl` and re-ran.

After the labels were clean, the baseline was 84.78% on the 46 record validation split. Then I tried the two DSPy levers:

- MIPROv2 on light search moved it to 85.6%. On 46 examples one record is worth about 2.2%, so a 0.8 point gain is less than a single example. That is noise, not improvement.
- Switching the signature to ChainOfThought made it worse, 84.78% down to 81.52%. The reasoning made the model talk itself out of the right answer on what is really a lookup against clear rules.

So neither lever beat the plain lean prompt.

## What I take from this

DSPy's optimizer earns its keep when there is a real gap between a weak prompt and the signal in the data. On this project there is not much gap. The prompts are already well built and the rules are explicit, so there is little for an optimizer to recover.

The thing that actually moved the needle both times was reading traces, which is the project's existing method, not DSPy. On extract it told me the fields were not gradable. On classify it caught 13 bad labels. The optimizer told me nothing I could act on.

The honest conclusion is that DSPy is not a good fit here. It would shine on a node where the right answer is hard to write by hand but easy to grade. Neither node in this pipeline is that.

## Files

- `dspy_extract/` scaffolding only, never optimized. Kept as a record of why extract is not gradable.
- `dspy_classify/` the full experiment: `signature.py`, `dataset.py`, `metric.py`, `baseline.py`, and `analyze.py`.
