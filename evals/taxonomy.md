# Failure Taxonomy — LLM-assisted draft

Run: 20260513T144022Z
Reviewed: 20 traces (8 pass / 12 fail)

> Based on 20 reviewed traces. The error-analysis playbook recommends 30–50 before locking categories. Re-run this exercise after the dataset grows (next batch from `dev.jsonl`) and revise as needed.

## Summary table

| # | Category | Prevalence | Gulf | Grader |
|---|---|---|---|---|
| 1 | `urgency_from_tone_not_facts` | 7/20 (35%) | Specification | Code + Judge |
| 2 | `clarify_gate_missing` | 3/20 (15%) | Specification | Code |
| 3 | `classify_reflex_tagging` | 5/20 (25%) | Specification | Code |
| 4 | `tenant_affect_dropped` | ~13/20 (65%) | Specification | Code + Judge |
| 5 | `default_tier_drift` | 1/20 (5%) | Specification | Code |

> **Note on overlap:** Cat 1 and Cat 3 both claim E07 and E04 (same trace, two root causes — tone-driven urgency *and* reflex flag tagging). Prevalence numbers in this table are per-category, not disjoint — don't sum them.

All five categories sit in the Specification gulf — the model is not failing because it can't understand the task (Comprehension) or because the distribution is too wide for one prompt (Generalization). It's failing because the prompts and graph don't say what we mean.

Code graders cover the exact-match checks (urgency=expected, flag set comparison, tool-call assertions, field population on affect cues). Two judges layered on top for the fuzzy parts: **urgency reasonableness** (is the tier defensible given the facts, even if not the dataset's exact pick?) and **sentiment accuracy** (is the sentiment label a fair read of the tenant's tone?). Each judge needs TPR/TNR validation against your `labeled.csv` before it's trusted.

---

## Category 1: `urgency_from_tone_not_facts`

**Definition (one sentence):**
> Agent sets urgency tier from tenant affect (panic, hostility, hedges, recurrence) or invents forward-risk from neutral diagnostic words, instead of from the physical facts of what is broken.

**Root cause (what's actually broken):**
> Classify prompt does not separate "physical severity" from "tenant affect." Tone signals (CAPS, "!!!!", "no rush", "third time", "rattling") are being treated as severity evidence. When tone and facts agree, calibration is correct (T05, T14, T13, E10); when they disagree, tone wins.

**Traces in this category:**
- e2e-E01 (panic+inconvenience → over-tier)
- e2e-E07 (containment ignored → over-tier)
- e2e-E12 (CAPS/!!!! → over-tier)
- e2e-E14 (recurrence → over-tier)
- e2e-E04 (hostile+minor → over-tier)
- e2e-E03 (hedges+dangerous → under-tier)
- e2e-T12 (neutral diagnostic words → over-tier)

**Count:** 7 / 13 fails

**Prevalence:** 7 / 20 traces = **35%**

**Gulf:** Specification — prompt doesn't separate physical severity from tenant affect.

**Grader (code or judge):** Code + Judge.
> - **Code (primary):** compare `classify.urgency` against `expected.urgency` in the dataset. Deterministic exact-match.
> - **Judge (secondary — urgency reasonableness):** "Given the physical facts in this email (ignoring tenant tone), is the urgency tier the agent picked defensible?" Useful for borderline cases where medium-vs-high is genuinely arguable. Validate against `labeled.csv` with TPR/TNR > 90% before trusting.

**Fix direction (prompt / code / new node / spec):**
> Prompt change in `classify`: explicit rule "urgency is set from physical facts only; tenant tone is recorded in `tenant_sentiment` but not used. Forward risk requires a concrete physical signal (smoke, smell, leak, no heat/water, lock failure). Recurrence sets priority within a tier, not the tier itself."
> **Note:** E08 (default-medium drift on a no-signal email) was previously in this category but split out as Category 5 — different root cause, different fix.

---

## Category 2: `clarify_gate_missing`

**Definition (one sentence):**
> When key operational info is missing, the agent picks a bad escape hatch — either proceeds with the field empty (or filled by a category guess) and dispatches a vendor anyway, or archives the email — instead of pausing to ask the tenant.

**Root cause (what's actually broken):**
> No clarify node exists in the graph (Step 8, out-of-scope per CLAUDE.md). With no "stop and ask" path, the agent falls into one of two shapes depending on how much info is in the email:
> - **invent-and-dispatch** (some info present, key fields missing): proceeds without unit / with a guessed category and dispatches anyway → vendor truck rolls to incomplete address with partly-guessed work.
> - **archive-instead-of-clarify** (almost no info): treats the email as junk → real tenant silently ignored.

**Traces in this category:**
- e2e-E06 (no unit → dispatched with unit empty) — invent-and-dispatch
- e2e-E02 ("the thing in the bathroom" → guessed plumbing, dispatched) — invent-and-dispatch
- e2e-E16 ("help"/"thx" → archived) — archive-instead-of-clarify

**Count:** 3 / 13 fails

**Prevalence:** 3 / 20 traces = **15%**

**Gulf:** Specification — no clarify node defined in the graph; pre-filter routing rule for "vague but plausibly real" emails is missing.

**Grader (code or judge):** Code — for each trace, assert: (a) if any of `unit_number`, `location_in_unit`, `description` is missing, then no `create_work_order` or `dispatch_vendor` tool calls fired; (b) `pre_filter.action` is `archive` only for spam/injection/automated mail (compare against `expected.pre_filter.action`).

**Fix direction (prompt / code / new node / spec):**
> Plan (Path 1 — automated clarify; chosen for now):
> 1. **Extract** sets `insufficient_info=true` when any of these required fields is missing: `unit_number`, `location_in_unit`, `description`.
> 2. **Conditional edge** after extract: `insufficient_info=true` → clarify node; otherwise → classify (as today).
> 3. **Clarify node** drafts a reply asking only for the missing fields, sends it, then interrupts the workflow.
> 4. **On tenant reply**, the new email comes back through pre-filter → extract; state is merged with the original; pipeline resumes.
> 5. **Pre-filter prompt** also updated: archive is reserved for spam / prompt-injection / automated mail. Vague-but-plausibly-real emails (E16-shaped) pass through so extract can flag them as insufficient_info instead of silently dropping them.
>
> **Retry / escalation rules:**
> - **Attempt 1:** send clarify email asking for missing fields.
> - **Attempt 2:** if reply still incomplete, send a second clarify email.
> - **After Attempt 2 still incomplete:** classify whether the tenant is (a) spamming / playing or (b) genuinely seeking help with a real problem.
>   - Spam / playing → archive.
>   - Genuine but unable to provide details → escalate to PM queue for human follow-up.
>
> Open: how to make the spam-vs-genuine call after attempt 2 (LLM judge on the reply thread, or a simple heuristic on reply length / coherence?). Decide when implementing.

---

## Category 3: `classify_reflex_tagging`

**Definition (one sentence):**
> Classify attaches labels (risk flags, `not_a_maintenance_request`) from category-shape reflex instead of explicit definitions — flags get attached without checking specific physical signals, and the maintenance-vs-not boolean gets flipped wrong on edge cases (noise disputes, lease questions) that surface-match a "tenant complaint."

**Root cause (what's actually broken):**
> Classify prompt lacks explicit definitions for either risk flags or what counts as a maintenance request. Without them, the model leans on surface patterns:
> - **Risk flags:** plumbing → `water_damage_potential` or `habitability_violation` (E06, E07, E04); locksmith → `security_risk` (T04). Flag attached from category, not from the specific signal in the body.
> - **`not_a_maintenance_request`:** loud surface signals decide it (vendor domain + invoice format → true on ER06; tenant + body mentions unit → false on ER04 even though noise dispute is not maintenance).

**Traces in this category:**
- e2e-E07 (`water_damage_potential` — drip contained in bathtub)
- e2e-E06 (`water_damage_potential` — water not moving)
- e2e-E04 (`habitability_violation` — slow drain is annoyance, not habitability)
- e2e-T04 (`security_risk` — lockout is not unauthorized access)
- e2e-ER04 (`not_a_maintenance_request=false` — noise dispute between tenants is not maintenance)

**Count:** 5 / 13 fails (overlaps with Category 1 on E07, E04)

**Prevalence:** 5 / 20 traces = **25%**

**Gulf:** Specification — classify prompt has no explicit definitions for risk flags or "what counts as a maintenance request."

**Grader (code or judge):** Code — set-compare `classify.risk_flags` against `expected.risk_flags`; compare `classify.not_a_maintenance_request` against `expected.not_a_maintenance_request`. Both deterministic.

**Fix direction (prompt / code / new node / spec):**
> Two-part prompt change in `classify` — **facts + rules** — applied to both risk flags and the maintenance boolean:
>
> **Risk flags:**
> 1. **Facts:** every flag must point to a specific physical signal in the email body. Model lists the signal next to each flag (e.g. `water_damage_potential` ← "water pooling on floor"). No signal → no flag.
> 2. **Rules:** explicit per-flag definitions in the prompt:
>    - `habitability_violation` = no working toilet, no water, no heat in winter, no power, unsafe structural condition.
>    - `water_damage_potential` = water escaping containment (leak onto floor/wall/ceiling), not water that's contained (drip into bathtub, sink that drains slowly).
>    - `fire_hazard` = smoke, burning smell, sparking, scorched surfaces.
>    - `security_risk` = unauthorized access, break-in, broken external lock or window. Lockouts (tenant locked themselves out) do not qualify.
>
> **`not_a_maintenance_request` boolean:**
> - **IS maintenance:** something needs fixing in the building, equipment, or fixtures the landlord/PM is responsible for.
> - **NOT maintenance:** vendor invoices, lease/tenancy questions, parking complaints, inter-tenant disputes, noise complaints about neighbors, account/billing questions, automated mail.
>
> **Overlap with Category 1:** E07 and E04 also live in Category 1. Keep them in both for now — same-fix test says Category 1's "facts not tone" rule won't, on its own, stop the model from attaching default flags.

---

## Category 4: `tenant_affect_dropped`

**Definition (one sentence):**
> Extract leaves `tenant_sentiment` and `tenant_framing` null even when the tenant clearly shows emotion or uses framing language, and these fields are not surfaced on the work order — so PM loses context they should have had when triaging.

**Root cause (what's actually broken):**
> Two-part problem:
> 1. **Extract spec gap:** the prompt doesn't tell extract *when* to fill these fields. Model fills them only when affect words are vivid (E10 "burning smell", ER04 "exhausted") and drops them on soft cues (E03 "no rush" twice, E04 hostile language, T13 polite request).
> 2. **No downstream consumer:** even when fields are populated, they don't ride along to the work order or PM queue, so PM can't use them to triage hostile / anxious tenants differently from routine ones.

**Traces in this category:**
- e2e-E03 ("no rush" said verbatim twice → `tenant_framing` null)
- e2e-E04 (hostile tone, rent-withhold threat → `tenant_framing` null)
- e2e-T13 (polite request → both fields null)
- e2e-T12 (calm/diagnostic tenant → both fields null)
- e2e-T14 (polite/patient tenant → both fields null)
- Plus ~8 more traces with null fields where affect was clearly present.

**Count:** Pervasive — ~13 / 20 traces (counts as failures only once PM consumes the fields; today the harm is latent).

**Prevalence:** ~13 / 20 traces = **65%** (field population rate on traces with clear affect cues).

**Gulf:** Specification — extract prompt doesn't tell the model *when* to fill affect fields; WO/PM payload schema doesn't carry them downstream.

**Grader (code or judge):** Code + Judge.
> - **Code (primary — field population):** assert `tenant_framing` and `tenant_sentiment` are non-null whenever the email body contains affect cue words from a fixed lexicon (`thanks`, `sorry`, `no rush`, `urgent`, `please`, `unacceptable`, etc.). Deterministic, catches the leak.
> - **Judge (secondary — sentiment accuracy):** "Given this email, is the `tenant_sentiment` label a reasonable read of the tenant's tone?" Catches cases where the field is populated but with the wrong value (e.g. model writes "angry" when the dataset expects "hostile"). Validate against `labeled.csv` with TPR/TNR > 90% before trusting.

**Fix direction (prompt / code / new node / spec):**
> Two-part fix:
> 1. **Extract prompt:** explicit rule — "populate `tenant_framing` whenever the tenant uses any framing language, including hedges, minimizers, complaints, and politeness markers. Populate `tenant_sentiment` from the overall register (calm / anxious / hostile / polite / panicked). Use null only when the email carries no affect at all (e.g. terse subject-only emails like E08)."
> 2. **Work order / PM queue payload:** include `tenant_sentiment` and `tenant_framing` on every WO and every `assign_to_pm_queue` call. PM uses them to triage — hostile + minor still gets routed for follow-up; anxious + dangerous gets prioritized.
>
> Grader: code-based — count traces where the email body contains affect cue words (`thanks`, `sorry`, `no rush`, `urgent`, `please`, `complaint`, `unacceptable`, etc.) AND `tenant_framing` or `tenant_sentiment` is null. Track over time.

---

## Category 5: `default_tier_drift`

**Definition (one sentence):**
> When the email carries no severity signal at all (terse, no facts, no tone), the agent defaults to `medium` instead of `low` — because the classify prompt has no rule for the "silent" case.

**Root cause (what's actually broken):**
> Classify prompt does not specify a default tier for emails with no severity evidence. With no rule, the model picks the safe middle (`medium`), which is wrong: a no-signal email is by definition not safety, not habitability, not urgent.

**Traces in this category:**
- e2e-E08 (`"As subject. Thanks."` — no facts, no tone → tier `medium`, expected `low`)

**Count:** 1 / 13 fails

**Prevalence:** 1 / 20 traces = **5%**

**Gulf:** Specification — classify prompt has no default-tier rule for the no-signal case.

**Grader (code or judge):** Code — exact-match `classify.urgency` against `expected.urgency`. Same grader as Cat 1; the distinction is in the fix, not the check.

**Fix direction (prompt / code / new node / spec):**
> Prompt change in `classify`: add an explicit default-tier rule — "if the email contains no safety signal, no habitability signal, and no concrete physical fact, set urgency to `low`. Do not default to `medium`."
>
> **Why a separate category from Cat 1:** Cat 1's fix is "ignore tone, use facts." That fix doesn't help E08, which has neither tone nor facts. The two need distinct prompt rules: one says *what to ignore*, the other says *what to do when there's nothing to read*.
>
> **Watch on next dataset expansion:** with only 1 trace today, this is thin. If more no-signal emails surface in the 60–100 expansion and they all drift to `medium`, the category is real. If E08 stays the only one, fold the default-tier rule into Cat 1's prompt change and retire this category.

---

## Notes / side-findings

> - **Calibration matrix (Category 1 evidence):** tone+facts agree → correct (T05, T14, T13, E10); tone+facts disagree → affect wins (E01, E07, E12, E14, E04, E03).
> - **T04 reclassified as fail (per user):** location_in_unit=None, over-tagged `security_risk` (lockout ≠ break-in), tenant phone never surfaced into structured field or work_order args. Placed in Category 3 (security_risk reflex) + the extract affect-leak note above (location, phone).
> - **T10 reclassified as pass (per user):** location "garbage disposal" vs "kitchen / garbage disposal" is narrower but not wrong; no real fail.
> - **Affect-leak is pervasive but not always a fail.** E08 has null sentiment/framing *correctly* ("As subject. Thanks." carries no affect). Same null output can be right or wrong — invisible from outputs alone.
> - **Defensive guard worth adding (not a failure category):** add a graph-level rule — if `classify.not_a_maintenance_request=true`, skip `create_work_order` and `dispatch_vendor`. No trace in the current 20 violates this contract, so it doesn't belong in the taxonomy, but it's cheap engineering insurance against future regressions.

---

## Priority order (fix first → last)

> Ordered by count × fixability × business impact, with build effort accounted for (Cat 2 last because it's the only one needing a new node + interrupt seam).

1. **Category 1 (`urgency_from_tone_not_facts`)** — 7/13 fails; prompt-only fix; highest-frequency and most consequential (wrong-tier dispatches affect every category).
2. **Category 3 (`classify_reflex_tagging`)** — 5/13 fails; prompt-only fix; partly overlaps with #1.
3. **Category 4 (`tenant_affect_dropped`)** — pervasive (~13/20) but harm is latent until PM consumes the fields; ship the extract prompt + WO payload changes together so the field stops being decorative.
4. **Category 5 (`default_tier_drift`)** — 1/13 fail; thin signal but trivial prompt rule. Ship alongside Cat 1's classify prompt edit (same file, same PR).
5. **Category 2 (`clarify_gate_missing`)** — 3/13 fails but worst-case outcomes (vendor sent to wrong/unknown unit, real tenant ignored). Last in order because it's the heaviest lift: new clarify node + interrupt seam + retry/escalation logic + pre-filter prompt change. Park as a tracked initiative; the other four can ship as prompt PRs in the meantime.
