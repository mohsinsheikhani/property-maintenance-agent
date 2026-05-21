# Failure Taxonomy

Run: 20260513T144022Z
Reviewed: 20 traces (8 pass, 12 fail)

Five categories below. They're derived from the notes in `trace_labels.csv` (and the cross-trace material in `../../runs/axial_raw_material.md`). The taxonomy is small enough to hold in your head, which is the point — five is enough to act on, and each one has at least two exemplars except Cat 5, which I've flagged explicitly as thin signal.

Causal claims, fix prescriptions, and priority ordering are deliberately not here. Those belong to step 5 (gulf attribution + fix-vs-eval); the original draft is preserved in `runs/`.

One overlap to be aware of: traces E07 and E04 sit in both Cat 1 and Cat 3 — the same trace has two independent failures, one in urgency, one in risk flags. So the per-category counts don't sum cleanly.

## Summary

| # | Category | Prevalence | Gulf | Grader |
|---|---|---|---|---|
| 1 | `urgency_from_tone_not_facts` | 7/20 (35%) | Specification | Code + Judge |
| 2 | `clarify_gate_missing` | 3/20 (15%) | Generalization (primary) + Specification (pre-filter slice) | Code |
| 3 | `classify_reflex_tagging` | 5/20 (25%) | Specification | Code |
| 4 | `tenant_affect_dropped` | ~13/20 (65%, approximate — judgment call on "clearly present") | Specification | Code + Judge |
| 5 | `default_tier_drift` | 1/20 (5%) | Specification | Code |

---

## Category 1: `urgency_from_tone_not_facts`

Agent assigns an urgency tier that doesn't line up with the physical facts in the email.

**Traces:**
- e2e-E01 (urgency=high, expected medium)
- e2e-E07 (urgency=high, expected low)
- e2e-E12 (urgency=high, expected medium)
- e2e-E14 (urgency=high, expected medium)
- e2e-E04 (urgency=high, expected low)
- e2e-E03 (urgency=medium, expected high — under-tier)
- e2e-T12 (urgency=medium, expected low)

**Count:** 7 of 13 fails. **Prevalence:** 35%.

**Gulf:** Specification (tentative — E10 and T05 show the model can calibrate from facts when wording is vivid enough, which hints at a Generalization tail on borderline phrasing. Confirm in step 5.)

**Grader:** Code (exact-match against `expected.urgency`) plus a judge for the borderline medium-vs-high cases (sub-question: is the picked tier defensible *given the facts alone*).

---

## Category 2: `clarify_gate_missing`

When the email is missing key operational info (unit number, item, description), the agent either dispatches a vendor with empty or guessed fields, or archives the email.

**Traces:**
- e2e-E06 (no unit; create_work_order + dispatch_vendor fired anyway)
- e2e-E02 ("the thing in the bathroom"; category guessed, vendor dispatched)
- e2e-E16 (subject "help" / body "thx"; pre_filter archived)

**Count:** 3 of 13 fails. **Prevalence:** 15%.

**Gulf:** Generalization for the main shape — there's no clarify node in the graph today, so no prompt edit alone can produce the right behaviour. A smaller Specification slice on the pre-filter side (the rule treats vague-but-real emails as junk).

**Grader:** Code. Two assertions per trace: (a) if any of `unit_number`, `location_in_unit`, `description` is missing, no `create_work_order` or `dispatch_vendor` calls fired; (b) `pre_filter.action` matches `expected.pre_filter.action`.

---

## Category 3: `classify_reflex_tagging`

`classify.risk_flags` or `classify.not_a_maintenance_request` doesn't match the specific facts of the email — the flag or the boolean is set in cases where the corresponding signal isn't actually in the body.

**Traces:**
- e2e-E07 (`water_damage_potential` on a drip contained in the bathtub)
- e2e-E06 (`water_damage_potential` on "toilet won't flush" — water isn't moving)
- e2e-E04 (`habitability_violation` on a slow-draining sink)
- e2e-T04 (`security_risk` on a tenant locked out of their own unit)
- e2e-ER04 (`not_a_maintenance_request=false` on a noise dispute between two tenants)

**Count:** 5 of 13 fails (E07 and E04 also live in Cat 1; same traces, independent failures). **Prevalence:** 25%.

**Gulf:** Specification.

**Grader:** Code. Set-compare `classify.risk_flags` against `expected.risk_flags`; exact-match `classify.not_a_maintenance_request`.

---

## Category 4: `tenant_affect_dropped`

Extract leaves `tenant_sentiment` and `tenant_framing` null on emails that contain clear affect or framing language.

**Traces (representative — not exhaustive):**
- e2e-E03 ("no rush" verbatim, twice → `tenant_framing` null)
- e2e-E04 ("ABSOLUTELY UNACCEPTABLE" plus rent-withhold threat → `tenant_framing` null)
- e2e-T13 ("Dear Property Management" / "I would appreciate" → both null)
- e2e-T12 (calm diagnostic register → both null)
- e2e-T14 (polite request, "Thanks, Ravi" → both null)

Plus around eight more traces with null fields where affect was clearly in the body.

**Count:** Pervasive — roughly 13 of 20 traces, but the "clearly present" judgment is mine, not deterministic. The number is approximate until we lock down a cue lexicon and count it from code.

**Prevalence:** ~65%.

**Gulf:** Specification.

**Grader:** Code (assert non-null `tenant_framing` / `tenant_sentiment` when the body contains a fixed list of affect cue words) plus a judge for whether a populated sentiment label is a fair read.

---

## Category 5: `default_tier_drift`

On emails with no severity signal at all (terse subject, no facts, no tone), the agent assigns `classify.urgency='medium'`.

**Traces:**
- e2e-E08 (subject-only "Light fitting broken unit 3C" / body "As subject. Thanks." → urgency=medium, expected low)

**Count:** 1 of 13 fails. **Prevalence:** 5%.

This is thin signal — one trace. Keeping it as its own category for now because the failure shape is distinct from Cat 1 (no tone to react to, no facts to over- or under-weight — just a no-signal email that drifted to the safe-feeling middle tier). If the next dataset expansion doesn't surface more like it, fold it back into Cat 1.

**Gulf:** Specification.

**Grader:** Code. Same exact-match check as Cat 1.

---

## Side findings (not categories — kept here so they're not lost)

- **Calibration matrix from Cat 1 evidence:** when tone and facts agree, the agent calibrates correctly (T05, T14, T13, E10). When they disagree, affect tends to win (E01, E07, E12, E14, E04, E03). This is the diagonal that makes the gulf tag uncertain — pure Specification would predict the diagonal failures too.
- **Affect-leak isn't always a failure.** E08's null `tenant_sentiment`/`tenant_framing` is correct — "As subject. Thanks." carries no affect. The same null output can be right or wrong depending on the body, which is why output-only inspection misses it.
- **The `not_a_maintenance_request` boolean may not be load-bearing.** On ER04 the boolean was wrong (false) and route still picked the right queue by re-reading the body. On ER06 the boolean was right (true) and route consumed it. Open question for step 5: does route ever use the boolean, or does it always re-decide from the body?
