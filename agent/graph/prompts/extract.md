Extract structured fields from a property maintenance email thread.
Return null for any field not clearly stated.

The user message contains the full thread: the original tenant email, plus any clarification asks the agent sent and the tenant's replies. Read all of it together — a reply that says "Unit 4B" is the unit_number for the original report.

Fields:
- unit_number: the tenant's unit or apartment number
- location_in_unit: where in the unit the problem is (e.g. "kitchen sink", "bathroom")
- duration_mentioned: how long the problem has been occurring, as stated by the tenant
- description: a brief description of the problem
- related_unit: a second unit involved (e.g. a leak coming from upstairs)
- diy_attempted: anything the tenant already tried before emailing
- callback_phone: a phone number, only if the tenant gave one
- tenant_framing: how the tenant framed urgency in their own words, e.g. "no rush", "ASAP", "as soon as possible", "whenever you can"
- tenant_sentiment: how the tenant is writing. Judge the writing, not the situation. Pick exactly one of these six labels, or null when the email is too short to carry any tone at all (subject-only, "As above. Thanks.").
  - **neutral.** Plain message, no emotion in the writing. Default for "X is broken, please fix" emails.
  - **calm.** The tenant is composed about something that could plausibly cause panic. They are holding it together. If there is nothing to hold it together about, use neutral.
  - **anxious.** Worry or hedging that shows concern about the situation. "I'm a bit worried", "is this going to be okay?". Worry about what is happening, not anger at the landlord.
  - **hostile.** Anger or blame aimed at the landlord or PM. "This is unacceptable", "I'll be contacting the city", "you keep ignoring me", sarcasm at staff.
  - **polite.** Clearly courteous wording beyond a routine sign-off: thanks, apologies for bothering, "whenever convenient", "no rush".
  - **panicked.** The tenant has stopped writing calmly. ALL CAPS, repeated punctuation, frantic phrasing, "PLEASE HELP".
- lease_question_present: true if the email also asks a lease or tenancy question on the side

## Insufficient info

A maintenance work order needs three facts: `unit_number`, `location_in_unit`, and `description`. If any of these is missing or not clearly stated across the whole thread, set `insufficient_info=true` and list the missing names in `missing_fields` (subset of `["unit_number", "location_in_unit", "description"]`). Otherwise `insufficient_info=false` and `missing_fields=[]`.

This is a fact-presence check, not a judgement about whether the email is a maintenance request. A non-maintenance email (lease question with no description) will also be flagged here; the gate downstream handles that case separately.
