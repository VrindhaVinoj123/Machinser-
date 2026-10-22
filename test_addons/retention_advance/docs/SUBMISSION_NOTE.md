# Submission note: Retention & Advance (Odoo 19)

**Approach.** The invoice stays a normal invoice (full receivable 115,000). The module posts separate linked entries and
reconciles them, so Odoo's residual, payment state and aged receivable remain correct.

**Entries (example: work 100,000, VAT 15%, retention 10%, recovery 20%)**

1. Retention, on posting, invoice date: Dr Retention Receivable 10,000 (due = handover date) / Cr Receivable 10,000, reconciled with the invoice.
2. Advance recovery, on posting: Dr Receivable 20,000 (reconciled with the advance payment) / Cr Receivable 20,000 (reconciled with the invoice). Invoice residual = 85,000, advance left = 180,000.
3. Release, on the release date: Dr Receivable *x* (due on the release date) / Cr Retention Receivable *x*, reconciled with the retention item.
4. Credit note, ratio r: Dr Receivable / Cr Retention Receivable (r x 10,000), and Dr/Cr Receivable (r x 20,000) which re-creates an open advance credit.
5. Reset to draft: each module entry is unreconciled and reversed (same date, opposite sign). Re-posting creates one new set.

**Assumptions.** Work done = untaxed amount. Project = first sales order on the invoice lines. One advance per invoice. Credit notes
return retention and advance in proportion to the credited untaxed amount. The returned advance is an open customer credit.
Reset to draft is blocked once retention is released or a credit note exists. An unreleased advance takes its project from the first invoice that recovers it.

**Not finished.** Not executed on Odoo 19, so the tests and the screen recording are missing. The report is a wizard with Excel export, not the
Enterprise `account.report` engine. Locked-period, multi-company and multi-term tests are not written. See README section 9 for the list of anchors to verify.
