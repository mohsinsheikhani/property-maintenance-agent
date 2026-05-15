# Step 5: Fix vs Eval, per failure mode

This file is the companion to `failure_taxonomy.md`. For each of the five categories, I answer four questions:

1. **Can I just fix it?** The fix is usually a prompt edit, a code bug, a missing tool, or a new node.
2. **If I fix it, is a grader still worth building** as a regression guard?
3. **If I build a grader, is it code or judge?** Code wins by default. I only reach for a judge when the criterion is genuinely subjective, and the judge has to clear TPR and TNR over 90 percent on a held-out set before I trust it.
4. **Priority comes from Frequency multiplied by Feasibility.** Feasibility runs on a 0.0 to 1.0 scale: 0.9 to 1.0 is trivial, 0.7 to 0.8 is hours of work, 0.5 to 0.6 is days, 0.3 to 0.4 is uncertain, 0.0 to 0.2 is unknown cause.

One rule of thumb from the plan: I do not build a judge for a failure that disappears with a one-line prompt fix. The job of a grader is to keep an unfixable failure from coming back. It is not there to police something the prompt change already killed.

---

## Summary table

| # | Category | Frequency | Fix? (what) | Grader after fix? | Code or Judge? | Feasibility | Priority |
|---|---|---|---|---|---|---|---|
| 1 | `urgency_from_tone_not_facts` | 7/20 (35%) | Classify prompt: separate physical facts from tone (rule plus examples on both sides) | Yes. High stakes, prompt-fragile, bidirectional harm. | Both. Code primary. Judge deferred until the labelled set reaches at least 100 traces. | About 0.65 bundled | **0.23** |
| 2 | `clarify_gate_missing` | 3/20 (15%) | New clarify node, interrupt seam, retry and escalation logic, and a pre-filter prompt tweak | Yes. Brand-new code path. Real harm if it regresses. | Code only. Judge deferred. | About 0.35 | **0.05** |
| 3 | `classify_reflex_tagging` | 5/20 (25%) | Classify prompt: per-flag definitions and maintenance-vs-not definitions | Yes. Fragile prompt, and missing real flags is high-stakes. | Code only. Both checks are deterministic. | About 0.85 | **0.21** |
| 4 | `tenant_affect_dropped` | About 13/20 (65%) | Extract prompt (when to populate) and a code change so the work order and PM payload carry the fields | Yes. High prevalence, plus a permanent downstream consumer once shipped. | Both. Code on null-leak, judge on label accuracy. | About 0.7 bundled | **0.28** (latent-discounted; raw is 0.45, because the harm does not materialize until the work order and PM payload ships) |
| 5 | `default_tier_drift` | 1/20 (5%) | One-line classify rule: when there are no signals, set urgency to `low`, not `medium` | Yes. Free, rides on Cat 1's grader. | Code only. | 0.95 | **0.05** |

---

## Per-mode decisions

### Category 1: `urgency_from_tone_not_facts`

**1. Can I just fix it?**
> Yes, a prompt edit could make this failure stop happening. The rule has two halves:
> - **What to ignore.** The tenant's emotional register, no matter how it is expressed, does not affect the tier. Examples (not the full list): CAPS, "!!!", "urgent" in the subject, repeated complaints.
> - **What to look for.** Concrete physical signals about what is broken. Anything I could point at in the building. Examples (not the full list): active leaks, smoke or burning smell, no heat in winter, lock failures.
>
> It is important to lead with the rule, not the examples. If I just list "ignore CAPS, !!!, recurrence", the model learns to ignore exactly those and still falls for the next tone signal a tenant invents (emoji spam, "ASAP", and so on). The examples are there to ground the rule, not replace it. The same point applies on the other side: without the general "concrete physical signals" rule, the model misses any signal I forgot to list.
>
> One more thing worth saying explicitly. If I only tell the model what to ignore, I still risk under-tiering a polite but dangerous email like E03. Both halves have to land together.

**2. Is a grader still worth building after the fix?**
> Yes, and the code grader ships *before* the prompt fix, not after. Urgency is high-stakes. Under-tier on a fire or a flood is real harm, not annoyance, and the under-tier side is the worse direction. Building the grader upfront means the prompt edit gets *verified* by the grader instead of being hoped to work and re-read by hand. The standard "fix, then re-read, then grader" order would leave a window where a prompt change could silently make under-tiering worse.
>
> The prompt rule is also fragile. It sits next to many others in `classify.md` and is easy to clobber on a future edit. The grader stays as the permanent guard.
>
> **Gulf hedge.** The Specification fix may leave a residual on borderline phrasing (E03 hedges, E10-style cues). The judge, once validated, is what catches the Generalization tail. The code grader alone will not close it.
>
> **Bidirectional harm.** Over-tier wastes vendor money. Under-tier risks property and safety. The under-tier side matters more, so the grader has to flag *both* directions, not just one.

**3. Code or judge?**
> Both.
> - **Code.** Exact match of `urgency` against the expected label. Cheap, deterministic, catches the obvious misses. Ships upfront, before the prompt fix.
> - **Judge.** "Given the physical facts in this email, ignoring tone, is the tier the agent picked defensible?" The reason for the second grader is that `expected.urgency` is one human's call, and urgency is the textbook case where reasonable people disagree (medium versus high on a slow drip). When the code grader fails, I will not know if the agent is wrong or the label is. The judge answers that.
> - **Judge caveat and revisit trigger.** The judge is not trustworthy until I validate it (TPR and TNR above 90 percent on a held-out set). Today's 20 labels are not enough. **Revisit once the labelled set hits about 80 traces** (per `validate-evaluator`'s minimum). I should not let "park it" become "forget it".

**4. Feasibility (0.0 to 1.0) and reasoning:**
> It depends on which piece:
> - Prompt fix alone: **0.9**. Small edit, no system change.
> - Code grader: **0.9**. It is an `==` check.
> - Judge: **0.5 to 0.6**. Write the prompt, label about 100 traces, validate TPR and TNR, iterate.
>
> Bundled (fix plus both graders): roughly **0.6 to 0.7**.

**5. Priority (Frequency multiplied by Feasibility):**
> Frequency 0.35 multiplied by bundled feasibility of about 0.65 gives **about 0.23**. I will rank this against the other four categories once they are scored. Calling it "high" without a number does not help me sort.

---

### Category 2: `clarify_gate_missing`

**1. Can I just fix it?**
> Yes, but this is the most expensive fix on the list. It is mostly architectural (Generalization), not a prompt edit. Four pieces have to land together:
> 1. **New clarify node** in the graph. It drafts a reply asking only for the missing fields, sends it, then interrupts the workflow.
> 2. **Interrupt seam.** Pause execution, wait for tenant reply, resume with state merged from the new email.
> 3. **Retry and escalation logic.** Attempt 1 clarify, attempt 2 clarify, then either archive (if spammy) or escalate to the PM queue (if genuine but unable to provide details).
> 4. **Pre-filter prompt tweak (the Specification slice).** Archive is reserved for spam, injection, and automated mail. Vague but plausibly real emails (E16 shape) pass through so extract can flag them as `insufficient_info`.

**2. Is a grader still worth building after the fix?**
> Yes. Two reasons:
> 1. **A brand-new code path means high regression risk.** Every future change to extract or pre-filter could silently break the clarify gate, and I will not see it until someone reviews traces again. A grader catches it on the next PR.
> 2. **The harm if it regresses is real.** Two failure shapes both have a cost. A vendor truck rolls to an incomplete address (E06 or E02 style), or a real tenant gets archived and the client never hears back (E16 style). Worth a permanent guard.

**3. Code or judge?**
> **Code is enough for now.** For each trace, assert:
> - (a) If any of `unit_number`, `location_in_unit`, or `description` is missing, then no `create_work_order` or `dispatch_vendor` fired. The clarify path fired instead.
> - (b) `pre_filter.action` is `archive` only for spam, injection, or automated mail (compare against `expected.pre_filter.action`).
>
> **Judge: defer.** My instinct that the pre-filter decision is subjective at the boundary ("help" or "thx", is that junk or real?) is right. But the code grader already compares the *decision* against the expected label. A judge would only add value if I want to grade the *reasoning* (was the archive defensible given just the email?). Useful later for catching novel-but-justified decisions the label cannot anticipate. Today, the dataset is too small to validate a judge (same caveat as Cat 1), so I park it.
>
> One Hamel-workflow worry to check: is this violated? No. Trace review has already happened. That is where this taxonomy came from. The rule is "no graders before trace review", not "no judges ever". I am deferring because of dataset size, not workflow order.

**4. Feasibility (0.0 to 1.0) and reasoning:**
> 0.3 to 0.4. The cause is known (no clarify node, no interrupt seam), so it is not "uncertain". But the work is multi-day. LangGraph interrupts add real complexity: state merging on resume, retry counters, and the spam-vs-genuine call after attempt 2. Bounded scope, but not a one-sitting fix.
>
> **Known unknown.** The spam-vs-genuine call after attempt 2 is itself an unspecified LLM decision. It likely needs its own judge eventually (when does archiving a confused tenant become "fair" versus "silent dismissal"?). Not in scope for the initial build, but I am flagging it so it does not surprise me when the clarify node ships and the next failure mode is "agent archived someone who was just slow to reply".

**5. Priority (Frequency multiplied by Feasibility):**
> Frequency 0.15 multiplied by feasibility of about 0.35 gives **about 0.05**. Lowest of the five so far, which confirms Cat 2 sorts last. The math also makes the call defensible: not "low" because I feel it is hard, but because the score reflects both the smaller blast radius (15 percent) and the heavier lift (about 0.35).

---

### Category 3: `classify_reflex_tagging`

**1. Can I just fix it?**
> Yes, a prompt edit is enough. But the fix actually has two halves, not one. The shape is the same as Cat 1 (rule first, examples second), applied twice:
>
> - **Risk flags.** Every flag must point to a specific physical signal in the email body. Flags must not be attached from the category shape alone (for example, attaching `water_damage_potential` because the category is plumbing, or attaching `security_risk` because the category is locksmith). Plus per-flag definitions so the model knows what counts. For example: `water_damage_potential` means water escaping containment, so a drip into the bathtub does not qualify. `security_risk` means unauthorized access or break-in, so a lockout does not qualify.
> - **`not_a_maintenance_request` boolean.** Explicit definitions of what *is* maintenance (something the landlord or PM is responsible for fixing in the building) and what *is not* (lease questions, vendor invoices, inter-tenant noise disputes, parking, billing).
>
> I should lead with the rule and use the bathtub-drip and lockout cases as grounding examples, not as the rule itself. Otherwise the model learns those exact edge cases and falls for the next one.

**2. Is a grader still worth building after the fix?**
> Yes, and the regression risk has two shapes:
> - **Wrong maintenance boolean.** The one I flagged first. A non-maintenance email still hits `create_work_order`. Or a real maintenance email gets routed to the PM queue and ignored.
> - **Wrong risk flags.** Flags do not reroute to PM; the maintenance boolean does that. But a wrong flag still hurts:
>   - It inflates the urgency tier downstream (a habitability flag forces the tier to high by definition).
>   - It puts a wrong signal on the work order itself. The PM acts on `habitability_violation: true` on their dashboard. Wasted attention, not wasted dispatch.
>   - **Missing a real flag is the worse direction.** A `fire_hazard` that should fire and does not lets a real emergency get tiered as routine. Same under-tier asymmetry as Cat 1.
>
> The same fragility argument applies. This rule sits in the classify prompt next to many others and is easy to clobber on a future edit.

**3. Code or judge?**
> Code only. Both checks are deterministic. Same high-stakes argument as Cat 1: **the risk-flag grader ships before the prompt fix**, because a missing `fire_hazard` is exactly the kind of regression I cannot catch by re-reading.
>
> - **Maintenance boolean.** Compare `classify.not_a_maintenance_request` against `expected.not_a_maintenance_request`. If it is `true` but `create_work_order` still fired, that is a fail.
> - **Risk flags: split into two graders, not one.**
>   - **Recall (under-flagging).** Every flag in `expected_flags` is also in `actual_flags`. Catches the dangerous miss, like `fire_hazard` expected but absent.
>   - **Precision (over-flagging).** Every flag in `actual_flags` is also in `expected_flags`. Catches reflex-tagging, like `habitability_violation` attached to a slow drain.
>   - The cost is the same as a set-equality check, but the CI gate can treat recall regressions as stop-the-line and precision regressions as investigate-and-fix. Set-equality treats both directions identically and loses that signal.
>
> No judge needed. Risk flags either match the spec or they do not. There is no "defensible-but-different" gray zone like urgency has.

**4. Feasibility (0.0 to 1.0) and reasoning:**
> Prompt edit is **0.9** (small, no system change). Both code graders are **0.9** each (`==` checks on a label and a set). Bundled is about **0.85 to 0.9**, higher than Cat 1 because there is no judge piece dragging the average down.

**5. Priority (Frequency multiplied by Feasibility):**
> Frequency 0.25 multiplied by feasibility of about 0.85 gives **about 0.21**. Roughly tied with Cat 1's 0.23, and that matches reality, because Cat 1 and Cat 3 both live in the classify prompt and should ship in the same PR.

---

### Category 4: `tenant_affect_dropped`

**1. Can I just fix it?**
> Yes, it is a two-part fix:
> - **Extract prompt change.** Populate `tenant_framing` whenever the tenant uses any framing language (hedges, minimizers, complaints, politeness markers). Populate `tenant_sentiment` from the overall register. Use null *only* when the email carries no affect at all (E08 shape, "As subject. Thanks."). Without that "when to populate" rule, the model only fills on vivid cues ("burning smell") and drops soft ones ("no rush" twice).
> - **Code change downstream.** Include `tenant_sentiment` and `tenant_framing` on every work order and every `assign_to_pm_queue` call. Without this, the fields stay decorative. They are populated correctly but never consumed.

**2. Is a grader still worth building after the fix?**
> Yes, and I was underselling this when I said "not high stake".
> - **Today the harm is latent** because nothing consumes the fields. Easy to dismiss.
> - **After the fix, the harm becomes real.** Once sentiment rides on the work order, PM uses it to triage. "Hostile and minor" gets a follow-up call. "Anxious and dangerous" gets prioritized. If the field regresses to null, PM triages blind.
> - **High prevalence (about 65 percent)** plus a permanent downstream consumer means the grader is warranted, not optional. Without one, the fix silently regresses over time and nobody sees it until PMs start complaining.

**3. Code or judge?**
> Both. They catch different failure shapes.
>
> First, one prompt-design choice (not a grader, but it makes graders easier): make `tenant_sentiment` a pre-defined enum (calm, anxious, hostile, polite, panicked) in the extract output schema. Locked vocabulary means code-checkable.
>
> - **Code grader (lexicon-based floor).** If the email body contains any affect cue from a fixed lexicon (`thanks`, `sorry`, `no rush`, `urgent`, `please`, `unacceptable`, and so on), assert both fields are non-null. Catches the easy "left null when it should not be" failure, but only the easy ones.
> - **Judge (closes the gap).** "Given this email, is the picked sentiment label a fair read of the tenant's tone?" This closes two gaps the lexicon cannot:
>   1. **Register-only affect.** A tenant writing "I would prefer this be resolved at your earliest convenience" carries clear politeness with no lexicon hit. The lexicon misses it; the judge catches it.
>   2. **Wrong value when populated.** The field is non-null but mislabeled (`polite` on a clearly hostile email). The lexicon cannot even ask this question.
>
> Framing: the lexicon is a *floor*, not a ceiling. It catches the bulk-shape failures cheaply. The judge is what makes the grader complete.
>
> **Judge deferral and revisit trigger.** Same as Cat 1. Validate (TPR and TNR above 90 percent) on a held-out set before trusting. **Revisit once the labelled set hits about 80 traces.** Until then, ship the code grader as the floor and read traces manually for the wrong-value cases.

**4. Feasibility (0.0 to 1.0) and reasoning:**
> - Extract prompt edit: **0.9** (small).
> - Work order and PM payload code change: **0.7 to 0.8** (hours of work, but it touches multiple call sites and needs care).
> - Code grader (lexicon plus null check): **0.8** (slightly more than `==` because I have to define the lexicon).
> - Judge: **0.5 to 0.6** (same as Cat 1: write the prompt, label, validate TPR and TNR).
> - Bundled: about **0.65 to 0.75**.

**5. Priority (Frequency multiplied by Feasibility):**
> Frequency 0.65 multiplied by feasibility of about 0.7 gives **about 0.45**. This sorts *above* Cat 1 and Cat 3 on the math, which is interesting and worth a sanity check. 65 percent is real, but the harm is latent until the downstream consumer ships. I discount it to about 0.4 prevalence-effective for now (giving **about 0.28**), and I will revisit it after the work order and PM payload change lands. With or without the discount, this is one of the top items.

---

### Category 5: `default_tier_drift`

**1. Can I just fix it?**
> Yes, a trivial prompt rule. Add one line to the classify prompt: "if the email contains no safety signal, no habitability signal, and no concrete physical fact, set urgency to `low`. Do not default to `medium`." This ships in the same PR as Cat 1's classify edit (same file).

**2. Is a grader still worth building after the fix?**
> Borderline. Two reasons it is still worth a code grader:
> - The Cat 1 code grader (exact match of `urgency` against `expected.urgency`) already covers it for free. Same check, no extra work. The cost is zero.
> - Today's signal is thin (1/20). If more no-signal emails show up in the next dataset expansion and they all drift back to `medium`, the rule is regressing. The grader catches that without me having to remember to look.
>
> If it cost real effort I would skip it. Since it is covered by Cat 1's grader, it is a free regression guard.

**3. Code or judge?**
> Code. Exact match of `urgency` against `expected.urgency`. Identical to Cat 1's primary grader. The categories differ in the *fix*, not the *check*.

**4. Feasibility (0.0 to 1.0) and reasoning:**
> **0.95**. A single-line prompt addition, no new grader needed (it rides on Cat 1's). The cheapest fix in the taxonomy.

**5. Priority (Frequency multiplied by Feasibility):**
> Frequency 0.05 multiplied by feasibility 0.95 gives **about 0.05**. Same score as Cat 2, but the meaning is opposite. Cat 2 scores low because it is expensive. Cat 5 scores low because the failure is rare. Since the fix is trivial and bundles with Cat 1, I will ship it. I will not sort it.

---

## Final ordered work list

> **Two sorting problems, not one.** The priority math in the table above sorts *categories*. That is a step-5 ranking based on Frequency multiplied by Feasibility. The work below sorts *PRs*, which is a downstream decision bundled by file-cohesion and shared-fate risk. The order is not always the same, and pretending it is would force one of them to misrepresent the other.

**PR ordering rationale.** Cat 1, Cat 3, and Cat 5 all rewrite rules in `agent/graph/prompts/classify.md`. They are not three independent fixes that happen to be in the same area. They share the same prompt file and the same risk of breaking each other on future edits. Shipping them as three PRs means three rounds of "did the previous classify edit break the failure mode I fixed last week". Bundling them avoids that, and the combined prevalence (about 13/20 traces, overlap accounted for) is real.

Cat 4 ranks above Cat 1, Cat 3, and Cat 5 on the per-category math (0.28 discounted versus 0.21 to 0.23). But its harm is latent until the work order and PM payload change ships and PM starts consuming the fields, so it can wait one PR cycle without shipping wrong answers to tenants today. Cat 1's under-tier on fire and flood facts cannot wait the same way. It is shipping wrong answers right now.

So:

1. **Bundle A: classify prompt PR (Cat 1 plus Cat 3 plus Cat 5).** All three live in `classify.md`. **Code graders for Cat 1 and Cat 3 ship *before* the prompt edits**, because under-tier on urgency and missing safety flags are both high-stakes. The graders verify the fix instead of being added after it. Cat 5's grader is free, since it rides on Cat 1's exact-match. One PR, three prompt rules, three code graders.

2. **Cat 4: `tenant_affect_dropped`.** Two-part fix. An extract prompt rule (when to populate) plus a work order and PM payload change so the fields are actually consumed. The lexicon-based code grader (the floor) ships in the same PR. The judge waits for dataset growth. This lands second because (a) it touches more files than Bundle A, and (b) its harm is latent until the payload change is live.

3. **Cat 2: `clarify_gate_missing`.** Last. Architectural work. A new clarify node, an interrupt seam, retry and escalation logic, and a pre-filter prompt tweak. Multi-day. I will track this as a separate initiative; other PRs ship while this gets designed.

**Judges are deferred across the board.** Cat 1's urgency judge and Cat 4's sentiment judge both need TPR and TNR validation on a held-out set before they are trusted in CI. **Revisit when the labelled set passes about 80 traces** (per `validate-evaluator`'s minimum). I can iterate the judge prompts now if it is useful, but I will not merge them into CI until they validate.
