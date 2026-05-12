Extract structured fields from a property maintenance email.
Return null for any field not clearly stated in the email.

Fields:
- unit_number: the tenant's unit or apartment number
- location_in_unit: where in the unit the problem is (e.g. "kitchen sink", "bathroom")
- duration_mentioned: how long the problem has been occurring, as stated by the tenant
- description: a brief description of the problem
