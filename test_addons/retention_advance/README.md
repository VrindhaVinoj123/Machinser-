# Retention & Advance Recovery on Invoices (`retention_advance`)

Odoo 19 Enterprise module for contracting companies. It handles retention and advance recovery on
customer progress invoices, keeps the retention in its own account with its own due date, lets the
accountant release it later, and reports balances per customer and project.

> **Status:** written without access to an Odoo 19 instance. Python and XML were syntax-checked only.
> The unit tests in `tests/` have **not been run**. See section 9 for what to verify first.

---

## 1. Installation

1. Put the `retention_advance` folder in an addons path.
2. Update the apps list and install **Retention & Advance Recovery on Invoices**. Dependencies: `account`, `sale`.
3. Python dependency: `xlsxwriter` (already bundled with Odoo).

## 2. Configuration (Accounting > Configuration > Settings > Retention & Advance)

Per company, so it works in multi-company databases.

| Setting | Meaning |
|---|---|
| Retention Receivable Account | Reconcilable account that holds the retention. Required to post an invoice with retention. |
| Default Retention % | Pre-filled on new customer invoices. `0` disables the default. |
| Retention Journal | Optional. Miscellaneous journal for the helper entries. Defaults to the first miscellaneous journal. |

Recommended: create the Retention Receivable account as type *Current Assets* with *Allow Reconciliation* ticked.
Then it stays out of the standard Aged Receivable. A *Receivable*-type account also works, but the retention
will then appear in Aged Receivable as "not yet due" (its due date is the handover date).

## 3. User guide

### 3.1 Record the advance
Register a customer payment (Customers > Payments) with no invoice. Tick **Advance Payment**
and optionally set the **Project (Sales Order)**. If the project is empty it is filled in the first time the advance is recovered.

### 3.2 Create a progress invoice
On the customer invoice open the tab **Retention & Advance**:

* **Retention %**: amount = untaxed work done x %. Set an **Expected Handover Date** (the retention due date; falls back to the invoice due date).
* **Advance Payment**: pick the payment. Only the same customer's posted payments with an open balance are offered.
* **Recovery Method**: % of work done, or a fixed amount.
* The tab shows: Invoice total, less retention, less advance recovery, **Amount to pay now**.

You cannot save or post a recovery larger than what is left on the advance.

Example (work 100,000, VAT 15%, retention 10%, recovery 20%, advance 200,000):

| | |
|---|---|
| Work done | 100,000 |
| VAT 15% | 15,000 |
| Invoice total | 115,000 |
| Less retention | 10,000 |
| Less advance recovery | 20,000 |
| **Amount to pay now** | **85,000** |

After posting, the invoice residual and Aged Receivable show 85,000. Retention account: 10,000. Advance left: 180,000.

### 3.3 Release retention
Customer form > **Release Retention** button (or Accounting > Customers > Release Retention).
Choose the customer and the release date. The grid lists every retention item still held, per invoice and project.
Type the amount to release per line (partial or full), or click **Fill Full Amounts**, then **Release**.
Each line creates its own entry and the amount becomes an ordinary receivable, due on the release date.

### 3.4 Credit notes
Use the normal *Credit Note* / *Reverse* action on the invoice. When the credit note is posted, retention and
advance come back in the same proportion as the credited work (see 4.4).

### 3.5 Reset to draft
Allowed as usual. The module reverses its entries (never deletes them); re-posting creates them once.
It is blocked if retention was already released or a credit note exists. Reverse those first.

### 3.6 Report
Accounting > Reporting > Retention & Advance. Choose **As at** date (and optionally customers), click **Show Report**,
then **Export to Excel**. Columns: Total invoiced, Retention held / released / balance, Advance received / recovered / balance.
Amounts are in company currency.

### 3.7 Printed invoice
The invoice PDF shows invoice total, less retention (%), less advance recovery, and **Amount to pay now** when the invoice has either deduction.

## 4. Accounting design

The invoice itself is a normal Odoo invoice with the full receivable (115,000). The module does **not** change how Odoo
builds the receivable lines. It adds separate, posted, linked miscellaneous entries and reconciles them against the invoice.
The invoice residual, payment state, aged receivable and partner ledger therefore stay correct with standard Odoo logic.

### 4.1 Entries created when the invoice is posted (numbers from the example)

| Entry | Dr | Cr | Reconciliation |
|---|---|---|---|
| Invoice (standard) | Receivable 115,000 | Revenue 100,000; VAT 15,000 | |
| **Retention** | Retention Receivable 10,000 (due = handover date) | Receivable 10,000 | Cr line vs the invoice receivable |
| **Advance recovery** | Receivable 20,000 | Receivable 20,000 | Dr line vs the advance payment's open credit; Cr line vs the invoice |

Result: invoice residual 85,000; Retention Receivable 10,000; advance open credit 180,000.
Both entries are dated the invoice date.

### 4.2 Release (on the release date)
Dr Receivable *x* (due on the release date) / Cr Retention Receivable *x*. The Cr line is reconciled with the retention item.

### 4.3 Reset to draft
Odoo unreconciles the invoice. The module then unreconciles its own entries and posts a reversal of each one dated the same day
(`_reverse_moves(cancel=True)`), so the advance is free again. Reversals carry the same type and opposite sign. Re-posting creates one fresh set.

### 4.4 Credit notes (ratio = credited untaxed / original untaxed, capped by what was not credited before)

| Entry | Dr | Cr | Reconciliation |
|---|---|---|---|
| Retention returned | Receivable r x 10,000 | Retention Receivable r x 10,000 | Cr vs retention item; Dr vs the credit note |
| Advance returned | Receivable r x 20,000 | Receivable r x 20,000 | Dr vs the credit note. The Cr stays open as the advance credit given back |

Retention already released is not returned (the credit note then simply reduces the receivable).

### 4.5 Foreign currency
All amounts are computed in the invoice currency. The company-currency balance of each entry is the invoice's own
balance x (amount / invoice total), i.e. the invoice's rate, so no exchange difference arises from the split. Standard reconciliation
handles any later difference. The advance balance is converted to the invoice currency for the limit check.

### 4.6 Multi-company
Settings live on `res.company`. The new fields sit on standard models that already carry company record rules. The wizards work in the current company.
No persistent model is added.

## 5. Technical reference

| Model | Additions |
|---|---|
| `res.company` | `ra_retention_account_id`, `ra_default_retention_pct`, `ra_journal_id` |
| `account.move` | Invoice: `ra_retention_pct`, `ra_retention_amount`, `ra_handover_date`, `ra_advance_payment_id`, `ra_recovery_type/pct/fixed/amount`, `ra_amount_to_pay`, `ra_project_id`. Helper entries: `ra_kind`, `ra_invoice_id`, `ra_source_move_id`, `ra_amount`, `ra_cn_ratio` |
| `account.payment` | `ra_is_advance`, `ra_sale_order_id` |
| `res.partner` | `action_ra_release_retention()` |
| `ra.release.wizard(+line)`, `ra.report.wizard`, `ra.report.line` | Transient models |

Overridden methods: `account.move._post` (validation before, entries after) and `account.move.button_draft`.
`ra_kind` values: `retention`, `release`, `recovery`, `return_retention`, `return_advance`.

Rules enforced: retention + recovery <= untaxed work done; recovery <= open advance (checked on save and again on post, with a row lock on the advance line);
retention account must differ from the receivable account; posted entries are only reversed, never edited or deleted;
lock dates are not bypassed (entries use the invoice date or the release date, and Odoo's own check raises if the period is locked).

## 6. Report definitions (company currency, as at date)

* **Total invoiced**: untaxed amount of posted invoices that carry retention or advance recovery, minus their credit notes, with date <= as-at date.
* **Retention held**: retention entries minus returns via credit notes. **Released**: release entries. **Balance** = held - released.
* **Advance received**: payments flagged *Advance Payment* (receivable credit). **Recovered**: recovery entries minus returns. **Balance** = received - recovered.
* Grouping: customer and project (sales order). Entries without a sales order go under the customer ("no project").

## 7. Assumptions

1. "Work done" = invoice untaxed amount. Retention and recovery % apply to it, never to VAT.
2. Project = the sales order of the invoice lines. If several orders are present, the lowest-id order is used.
3. Retention % and recovery are per invoice; one advance payment per invoice.
4. A credit note's share of retention and advance is proportional to its untaxed amount. The returned advance is a plain open customer credit (not re-selectable as an "advance payment").
5. An advance with no sales order takes the project of the first invoice that recovers it.
6. The release date is both the accounting date and the due date of the released receivable.
7. Billing-level users post invoices, so the helper entries are created with the posting user's rights.

## 8. Not finished / limitations

* Not run on Odoo 19. No screen recording is included.
* The report is a wizard with Excel export. It does not use the Enterprise `account.report` framework.
* One advance per invoice. Releasing allows no automatic oldest-first allocation of a single total.
* The credit-note proportion ignores a credit note that credits only VAT or only some lines differently from the average retention rate.
* No payment-term split of retention (one handover date per invoice).
* Reset to draft is blocked after a release or credit note instead of unwinding them.

## 9. Verify first on Odoo 19 (things I could not check)

* XML anchors: `//app[@name='account']` (settings), `//notebook` in the invoice form, `//field[@name='partner_id']` in the payment form,
  `//div[@name='button_box']` in the partner form, `//div[hasclass('page')]` in `account.report_invoice_document`,
  and the menu parents `account.menu_finance_receivables` and `account.menu_finance_reports`.
* Field names: `account.account.reconcile`, `account.payment.is_reconciled`, `account.move.company_currency_id`, `reversal_move_ids`.
* `AccountMove._reverse_moves(default_values_list, cancel=True)` signature, and that `button_draft` unreconciles the invoice lines.
* Group names `account.group_account_user` for the ACLs.
* The test fixtures (`default_tax_sale`, `currency_data`, account creation with `company_ids`).

## 10. Running the tests

```
odoo-bin -d <db> -i retention_advance --test-tags /retention_advance --stop-after-init
```
Covered: the task example, over-recovery, partial release, partial credit note, reset and repost, release blocking the reset, a foreign-currency invoice.
Still to add: locked period, multi-company, multi-term invoices.
