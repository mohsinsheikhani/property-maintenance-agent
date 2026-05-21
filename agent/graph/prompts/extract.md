Extract structured fields from a property maintenance email thread.
Return null for any field not clearly stated.

The user message contains the full thread: the original tenant email, plus any clarification asks the agent sent and the tenant's replies. Read all of it together — a reply that says "Unit 4B" is the unit_number for the original report.

Fields:
- unit_number: the tenant's unit or apartment number. Must appear verbatim somewhere in the thread (original email, signature, or a tenant reply). Do not infer, guess, or carry a value over from another email. If the thread does not state a unit, leave null.
- location_in_unit: where in the unit the failing thing is located (e.g. "kitchen sink", "bathroom"). This is the location of the broken object, not where a symptom is observed and not where the tenant happens to be. A drip from a shower head that lands in the bathtub has `location_in_unit="shower"`, not "bathtub". If the failing thing is not tied to a specific spot, leave null.
- duration_mentioned: how long the problem has *existed*, as stated by the tenant. The tenant must frame the duration as the lifespan of the problem itself: "for two days", "since Monday", "all week", "started X days ago", "this has been going on for". Do not count: the duration of a single failed attempt ("I had a roast in for 90 minutes", "ran the dishwasher for an hour"), cooking or appliance run times, references to a previous unrelated report ("about two weeks ago"), lease dates, move-in dates. A duration that describes one bad use of the appliance is the event's duration, not the problem's duration. If the tenant only describes one failed attempt without saying how long the problem has been going on, leave null.
- description: a self-contained statement of what is failing. Include both the object that is failing and the symptom. The object is the specific thing the tenant is pointing at (a fixture, an appliance, a part of the unit). The symptom is what it is doing or not doing. Pair them. A symptom by itself like "draining slowly" or "won't turn on" is not enough; pair it with the object so the description still makes sense without the email: "bathroom sink draining slowly", "oven won't turn on". An object by itself like "bathroom sink" or "garbage disposal" is also not enough. Prefer the most specific object the email gives, including any location qualifier the tenant attached to it ("cabinet door above the dishwasher" beats "kitchen cabinet"). Drop tenant editorializing (capitalization, repeated punctuation, threats, sarcasm). Vague wording like "issue", "problem", or "something's wrong" does not count. Naming a room alone does not count. If only the symptom or only the object is stated and the other cannot be inferred from the email, leave description null.
- related_unit: a second unit involved (e.g. a leak coming from upstairs)
- diy_attempted: anything the tenant already tried before emailing
- callback_phone: a phone number, only if the tenant gave one
- tenant_framing: how the tenant framed urgency in their own words, e.g. "no rush", "ASAP", "as soon as possible", "whenever you can", "this is urgent". The wording must explicitly speak to timing or urgency. Sign-offs and courtesy tokens ("thanks", "regards", "cheers", "appreciate it") are not framing; leave null if the email has no urgency wording.
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

`location_in_unit` only counts as missing when the failing thing could plausibly be in different parts of the unit and the tenant did not say which. When the email itself fixes the location, do not list `location_in_unit` as missing. Examples where the location is fixed by the situation and the slot does not apply: a lockout (the apartment door, by definition), a whole-unit issue like no power or no water, anything tied to the unit's entry. In those cases leave `location_in_unit=null` and do not put it in `missing_fields`.

This is a fact-presence check, not a judgement about whether the email is a maintenance request. A non-maintenance email (lease question with no description) will also be flagged here; the gate downstream handles that case separately.
