# NeoPay demo bank

Kaveri Bank and its NeoPay digital banking platform are fictional. They exist to demonstrate ClauseIQ's **System assessment**, which compares a bank's design documents with the obligations extracted from ingested circulars.

| File | What it is | How ClauseIQ reads it |
| --- | --- | --- |
| [neopay-sre.pdf](../clauseiq-frontend/public/demo-bank/neopay-sre.pdf) | System Requirements and Engineering (SRE) document | Text extraction, clause chunking |
| [neopay-architecture.png](../clauseiq-frontend/public/demo-bank/neopay-architecture.png) | Architecture diagram | Vision model, read into factual statements |
| [neopay-er-diagram.png](../clauseiq-frontend/public/demo-bank/neopay-er-diagram.png) | ER diagram of the core database | Vision model, read into factual statements |

The files are served by the frontend, so **Use demo bank files** on the RegDesk System assessment page uploads all three. To change them, edit `generate_artifacts.py` and run it from the repository root:

```sh
python demo-bank/generate_artifacts.py
```

It needs `reportlab` and `Pillow`, which `circular-ingestion/requirements-dev.txt` installs.

## Answer key

The documents are written to fail and pass specific obligations that ClauseIQ has extracted from circulars. Which findings appear depends on the circulars you have ingested.

| Area | NeoPay design | Expected result | Relevant circulars |
| --- | --- | --- | --- |
| Children's data | Customers aged 10–17 consent with their own checkbox. No guardian consent column. | Gap | DPDP: verifiable consent of a parent or guardian |
| Data audit | No independent data auditor. Reviews are internal. | Gap | DPDP: independent data audit for significant data fiduciaries |
| Sanctions | Internal watchlist refreshed quarterly. UNSC and UAPA lists not integrated. De-listing requests decided internally. | Gap or conflict | RBI: UAPA procedure, forwarding de-listing requests to MHA |
| Debit holds | Account holder not told when a hold is placed or removed. No time limit on holds. | Gap or conflict | RBI: notify the account holder, remove the hold on day 31 without direction |
| Nodal officer | Head of Fraud Risk is the designated Nodal Officer. | Meets | RBI: designate Nodal Officers |
| Complaints | Resolution target of 45 days. | Conflict | RBI: resolve complaints within 30 calendar days |
| Penal charges | 2% p.a. penal interest added to the rate and capitalised monthly. Not in the KFS or reminders. | Conflict | RBI: no penal interest or capitalisation; disclose in KFS and reminders |
| Interest rate changes | Applied prospectively. | Meets | RBI: changes effected only prospectively |
| Aadhaar | Stored in full and shown unmasked to operations staff. | Gap, where a masking obligation has been ingested | |
| Third parties and hosting | Analytics vendor in the USA receives personal data without an agreement. DR replica in Singapore. | Gap, where such an obligation has been ingested | |
| Logs | Audit logs kept for 90 days. | Gap, where a log retention obligation has been ingested | |
