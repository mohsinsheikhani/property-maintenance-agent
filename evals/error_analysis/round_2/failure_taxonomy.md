# Failure Taxonomy, Round 2

Axial coding of the 10 failed traces in `trace_labels.md`. This is the round that comes after Bundle A (Cat 1+3+5), Cat 4, and Cat 2 shipped and the agent was re-run.

20 traces labelled, 10 fail, 10 pass. Prevalence below is read as `failed traces / 20`.

A single trace can show up in more than one category. When the same trace carries two failures that need different fixes, they get split.

---

## 1. `description_subject_drop`

**Definition:** The extracted `description` keeps the symptom but drops the noun it attaches to, so a vendor reading the work order can't tell what is actually broken.

**Span:** extract, `description`

**Annotations:**
- T10. `"makes a humming noise but doesn't actually run"`. Lost "garbage disposal".
- T05. `"won't ignite"`. Lost "burner / stove".
- T12. `"making loud rattling noise"`. Lost "AC unit".

**Prevalence:** 3 / 20

---

## 2. `slot_misbound_to_unrelated_referent`

**Definition:** A slot value is filled from text that exists in the email but refers to something other than the current problem.

**Span:** extract, `duration_mentioned` and `location_in_unit`

**Annotations:**
- E01. `duration_mentioned="90 minutes"`. That is the roast time, not how long the oven has been malfunctioning.
- E07. `location_in_unit="bathtub"`. The bathtub is where the drip lands. The failing fixture is the shower head.
- E07. `duration_mentioned="about two weeks ago"`. That refers to the prior 4B report, not the current 7A issue.

**Prevalence:** 2 / 20 (3 slot instances across 2 traces)

---

## 3. `silent_field_invention`

**Definition:** A slot value appears that has no source in the email, or a sign-off token is reused as if it were semantic content.

**Span:** extract, `unit_number` and `tenant_framing`

**Annotations:**
- E06. `unit_number="Unit 4B"`, not present in the email. `tenant_framing="thanks"`, which is a sign-off, not framing.
- E02. `unit_number="Unit 4B"`, not present in the email.

**Prevalence:** 2 / 20

---

## 4. `thin_request_marked_non_maintenance`

**Definition:** A vague but plausible maintenance email is classified `not_a_maintenance_request=true` and routed to `pm_queue="review"`. The correct path is to trigger clarify.

**Span:** classify, `not_a_maintenance_request` and `pm_queue`

**Annotations:**
- E02. Broken item in the bathroom, no description.
- C05. "Issue in the kitchen of 8A".

**Prevalence:** 2 / 20

---

## 5. `inapplicable_slot_demanded_as_missing`

**Definition:** Extract lists a slot under `missing_fields` for a case where that slot does not apply, so clarify gets triggered to ask about something the email never needed.

**Span:** extract, `missing_fields`

**Annotations:**
- T04. Lockout at unit 22 door. `location_in_unit` added to `missing_fields`. For a lockout the problem location is the apartment door by definition. The slot is not applicable here, but extract still demanded it.

**Prevalence:** 1 / 20

---

## 6. `clarify_body_contradicts_email_context`

**Definition:** The drafted `pending_clarify_body` asks about a fact the email already settled, so the agent reads as if it never opened the message.

**Span:** clarify, `pending_clarify_body`

**Annotations:**
- T04. Asked "where in the apartment you're locked out?" for a lockout case. The question doesn't make sense — by definition the tenant is locked out at the apartment door, so there is no "where in the apartment" to ask about.

**Prevalence:** 1 / 20

---

## 7. `non_tenant_email_archived_instead_of_routed`

**Definition:** The pre-filter archives a non-tenant operational email (vendor invoice, accounting, and similar) instead of routing it to the appropriate queue.

**Span:** pre_filter, `pre_filter_decision`

**Annotations:**
- ER06. AquaCare invoice archived. Should route to accounting.

**Prevalence:** 1 / 20

---

## 8. `unsupported_risk_flag_added`

**Definition:** A `risk_flags` value is attached without a realistic evidentiary path in the email body.

**Span:** classify, `risk_flags`

**Annotations:**
- E07. `water_damage_potential` on a slow drip into a bathtub.

**Prevalence:** 1 / 20

---

## Cross-cutting notes

Extract is doing most of the failing. Categories 1, 2, 3, and 5 all sit in the extract node, and six of the ten failures touch extract at least once. If there is one prompt worth opening next, it is that one.

Three traces carry two independent failures. E02 invents a unit number and then misclassifies the request as non-maintenance. E07 misbinds two slots and adds a risk flag with no real evidence. T04 misses an extract cue and then drafts a clarify question that contradicts the email. Splitting those is what keeps the fixes targeted instead of one vague "improve extract" task.

A few categories sit at n=1 (ER06, the spurious risk flag on E07, the clarify mismatch on T04). They stay as their own categories because the stakes are high enough that even a single occurrence is worth a guard. Archiving a vendor invoice is the kind of thing that quietly destroys a thread until someone notices it is missing.

Categories 4 and 5 look similar at first read. Both are "this should have gone to clarify". They are kept separate because the fix sites are different: category 4 is a classify-prompt issue (treating thin maintenance requests as non-maintenance), category 5 is an extract-prompt issue (not picking up a cue that was right there).
