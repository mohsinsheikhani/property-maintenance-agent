# Fix vs Eval, Round 2

For each category in `failure_taxonomy.md`, the same four questions from the error-analysis skill:

1. Can we just fix it, and where.
2. Will the failure still happen after the fix.
3. Is an evaluator worth the effort (frequency, impact, will we actually rerun it).
4. Decision.

Ordered by prevalence. Ties broken by blast radius.

---

## 1. `description_subject_drop`

**Prevalence:** 3 / 20

**Fix site:** `agent/graph/prompts/extract.md`, the `description` field rule.

**Rule to add:** the description must name the object that is broken, not just the symptom. "humming noise" is not enough, "garbage disposal humming but not running" is.

**Persists after fix?** Unlikely for the obvious cases. Edge cases may remain when the email itself never names the object, but those are extract-time `insufficient_info` calls, not the same failure.

**Eval worth it?**
- Frequency: highest in this round, 3 of 10 fails.
- Impact: medium. A vendor reading the work order can't tell what is actually broken, so the dispatch is wasted.
- Iterate: yes. Every prompt edit to `extract.md` can regress this, and it is cheap to grade.

**Decision:** fix plus judge. The judge reads the email and the extracted `description` and decides whether the description names the broken object. A code grader would need a maintained list of expected nouns per email, which does not generalize.

---

## 2. `slot_misbound_to_unrelated_referent`

**Prevalence:** 2 / 20 (3 slot instances)

**Fix site:** `agent/graph/prompts/extract.md`, the slot definitions for `duration_mentioned` and `location_in_unit`.

**Rule to add:** slot values must refer to the current problem, not other nouns or events in the email. "90 minutes" is the roast time, not how long the oven has been off. "bathtub" is where the drip lands, not where the shower head is.

**Persists after fix?** Possible. This is a referent disambiguation problem and prompts only get you so far. Keep an eye on it across model swaps.

**Eval worth it?**
- Frequency: 2 of 10 fails, with multiple slot hits inside.
- Impact: high when it fires, because a wrong slot leads to a wrong clarify, a wrong work order, or a wrong vendor pick.
- Iterate: yes.

**Decision:** fix plus judge. The check is "is this slot value bound to the failing thing in the email or to something else." Hard to write as code because the source spans the whole body. Validate the judge on a held-out set before trusting it.

---

## 3. `silent_field_invention`

**Prevalence:** 2 / 20

**Fix site:** `agent/graph/prompts/extract.md`, plus the structured output guard.

**Rule to add:** never fill a slot from outside the email body. If the value is not literally present or directly implied, leave it null and add the field to `missing_fields`. Sign-off tokens like "thanks" are not framing.

**Persists after fix?** Should drop close to zero for the unit number case because it is checkable. The framing case may need an explicit short list of allowed `tenant_framing` values.

**Eval worth it?**
- Frequency: 2 of 10.
- Impact: high. A made-up unit number can route the work order to the wrong tenant.
- Iterate: yes for `unit_number`, this is the kind of regression that hides until someone notices.

**Decision:** fix plus code grader. `unit_number` either appears as a substring in the body or it does not. `tenant_framing` gets locked to an enum the same way sentiment already is.

---

## 4. `thin_request_marked_non_maintenance`

**Prevalence:** 2 / 20

**Fix site:** `agent/graph/prompts/classify.md`, the rule for `not_a_maintenance_request`.

**Rule to add:** a vague but plausibly maintenance email is still a maintenance request. If the body mentions a broken item, an issue, or a location in a unit, do not set `not_a_maintenance_request=true` just because details are thin. Thinness is a clarify trigger downstream, not a non-maintenance signal.

**Persists after fix?** Some borderline cases will remain. The clarify path is the safe default, so a small overreach toward clarify is fine.

**Eval worth it?**
- Frequency: 2 of 10.
- Impact: medium. The failure is silent, the email lands in `pm_queue=review` and waits.
- Iterate: yes, classify is a hot prompt.

**Decision:** fix plus code grader on `not_a_maintenance_request` and `pm_queue` against expected.

---

## 5. `inapplicable_slot_demanded_as_missing`

**Prevalence:** 1 / 20

**Fix site:** `agent/graph/prompts/extract.md`, the `missing_fields` rule, possibly conditioned on a coarse category read.

**Rule to add:** `location_in_unit` does not apply for lockouts. For categories where the problem location is fixed by definition, do not add the slot to `missing_fields`.

**Persists after fix?** Probably no for lockouts. Other categories may have similar applicability rules (smoke alarm, exterior issues) that will surface in later rounds.

**Eval worth it?**
- Frequency: 1 of 10.
- Impact: high per occurrence because it causes a nonsense clarify (see category 6).
- Iterate: maybe. If we keep adding categories with their own applicability rules, a grader pays off.

**Decision:** fix-only for now. Revisit if a second category shows the same shape in Round 3.

---

## 6. `clarify_body_contradicts_email_context`

**Prevalence:** 1 / 20

**Fix site:** the clarify-body drafting prompt.

**Rule to add:** the question must be consistent with facts already in the email. If the email is a lockout, do not ask "where in the apartment" because the answer is the apartment door by definition.

**Persists after fix?** Often a cascade from category 5. Fixing extract removes the trigger here. Still worth a guard at the clarify layer because other cascades can produce the same shape.

**Eval worth it?**
- Frequency: 1 of 10.
- Impact: high. This is the most visible failure to the tenant. It reads as if the agent never opened the email.
- Iterate: yes, this is exactly the kind of thing that drifts.

**Decision:** fix plus judge as a guardrail. The judge reads the email plus the drafted body and decides if the question is answerable from the email alone. Tenant-facing copy is the right place to spend a judge.

---

## 7. `non_tenant_email_archived_instead_of_routed`

**Prevalence:** 1 / 20

**Fix site:** the pre-filter prompt.

**Rule to add:** vendor invoices, accounting mail, and operational non-tenant emails route to the appropriate queue. Archive is only for true noise (newsletters, marketing, automated alerts that need no action).

**Persists after fix?** Some new operational categories may appear and need explicit handling. The default should be "do not archive if unsure, route to review."

**Eval worth it?**
- Frequency: 1 of 10.
- Impact: very high. Archiving a vendor invoice quietly destroys a thread until someone notices it is missing.
- Iterate: yes, this is a safety-shaped check.

**Decision:** fix plus code grader as a guardrail. Grade `pre_filter_decision` against expected on a stratified slice that includes invoices, accounting, vendor follow-ups, and true noise.

---

## 8. `unsupported_risk_flag_added`

**Prevalence:** 1 / 20

**Fix site:** `agent/graph/prompts/classify.md`, the `risk_flags` rule.

**Rule to add:** a risk flag requires an evidentiary path in the body. `water_damage_potential` needs a real damage cue, not a slow drip into a bathtub. If the cue is absent, do not add the flag.

**Persists after fix?** Likely yes at some rate, because risk flags are judgment-shaped.

**Eval worth it?**
- Frequency: 1 of 10.
- Impact: policy-shaped. A false positive on risk can change dispatch urgency.
- Iterate: yes, this is a prompt-and-model drift category.

**Decision:** fix plus judge. The existing `risk_flags` grader work in `../round_1/trace_labels.csv` already takes this seriously. Keep the judge, validate TPR/TNR on a held-out set.

---

## Summary table

| # | Category | Fix site | Decision |
|---|---|---|---|
| 1 | `description_subject_drop` | extract prompt | fix + judge |
| 2 | `slot_misbound_to_unrelated_referent` | extract prompt | fix + judge |
| 3 | `silent_field_invention` | extract prompt | fix + code grader |
| 4 | `thin_request_marked_non_maintenance` | classify prompt | fix + code grader |
| 5 | `inapplicable_slot_demanded_as_missing` | extract prompt | fix-only |
| 6 | `clarify_body_contradicts_email_context` | clarify prompt | fix + judge guardrail |
| 7 | `non_tenant_email_archived_instead_of_routed` | pre-filter prompt | fix + code grader guardrail |
| 8 | `unsupported_risk_flag_added` | classify prompt | fix + judge |

Four of the eight land in `extract.md`. That is the prompt to open first.
