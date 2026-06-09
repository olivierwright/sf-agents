# Structured Finance Knowledge Base
## sf-agents · Domain Reference Document
### Version 1.0 — June 2026

---

This document is the foundational domain knowledge for the sf-agents framework and its AI agents. Every primitive, planner, and synthesis agent should treat this as authoritative background when reasoning about structured finance deals, data, and questions. It covers the mechanics, terminology, regulation, data standards, and green/ESG specifics relevant to European — and particularly Dutch — securitisation.

---

## PART 1 — SECURITISATION FUNDAMENTALS

### 1.1 What securitisation is

Securitisation converts a pool of illiquid assets (mortgages, auto loans, credit card receivables, etc.) into tradeable securities sold to capital market investors. The core mechanism:

1. An **originator** (bank, mortgage lender) originates a pool of loans.
2. The pool is sold — a true sale — to a **Special Purpose Vehicle (SPV)** or **Special Purpose Entity (SPE)**, legally bankruptcy-remote from the originator.
3. The SPV issues **notes** (bonds) to investors, backed by the cash flows from the loan pool.
4. A **servicer** (often the originator itself) continues collecting payments from borrowers and passing them through to the SPV waterfall.
5. Investors receive principal and interest according to the **priority of payments** (waterfall).

The SPV structure isolates the collateral from originator insolvency risk. Investors' returns depend solely on collateral performance, not the originator's creditworthiness.

### 1.2 Asset classes

| Class | Abbreviation | Collateral |
|---|---|---|
| Residential Mortgage-Backed Securities | RMBS | Residential mortgages |
| Commercial Mortgage-Backed Securities | CMBS | Commercial real estate loans |
| Auto ABS | Auto ABS | Car loans and leases |
| Consumer ABS | Consumer ABS | Personal loans, credit cards |
| Collateralised Loan Obligations | CLO | Corporate leveraged loans |
| Asset-Backed Commercial Paper | ABCP | Short-term receivables |
| SME ABS | SME ABS | Small and medium enterprise loans |

RMBS is the largest and most standardised asset class in Europe, and the primary focus of this framework.

### 1.3 Tranching

A single pool issues multiple classes (tranches) of notes with different risk/return profiles:

- **Senior tranche (Class A)**: paid first, lowest risk, highest credit rating (typically AAA). Credit enhanced by all subordinated tranches beneath it.
- **Mezzanine tranches (Class B, C...)**: absorb losses after the equity piece is exhausted; rated investment grade (AA down to BBB).
- **Junior / equity tranche (Class Z, residual)**: absorbs first losses; unrated; held by originator (often as risk retention).

**Credit enhancement** protects senior noteholders:
- **Subordination**: junior tranches absorb losses before senior.
- **Reserve fund**: cash reserve funded at closing; replenished from excess spread.
- **Excess spread**: difference between interest received on collateral and interest paid to noteholders + fees.
- **Overcollateralisation**: collateral pool value exceeds the note principal.
- **Guarantees**: external (e.g. NHG in the Netherlands) or internal credit wraps.

**Attachment and detachment points** define where a tranche starts absorbing losses (attachment) and is completely wiped out (detachment). ESMA Annex 2 data allows computing these from outstanding balances.

---

## PART 2 — RMBS SPECIFICS

### 2.1 RMBS structure roles

| Role | Function |
|---|---|
| **Originator / Seller** | Originates and sells the mortgage loans to the SPV |
| **Issuer / SPV** | Holds the collateral, issues notes, manages the waterfall |
| **Servicer** | Collects borrower payments, manages arrears, enforces |
| **Trustee** | Acts on behalf of noteholders; enforces against SPV if needed |
| **Paying agent** | Distributes cash to noteholders on each IPD |
| **Calculation agent** | Computes interest, principal, and available distribution amounts |
| **Swap counterparty** | Hedges interest rate basis risk (e.g. fixed mortgage rate vs floating EURIBOR) |
| **Account bank** | Holds transaction accounts |
| **Rating agencies** | Assign and monitor ratings (S&P, Moody's, DBRS Morningstar, Fitch) |

### 2.2 The waterfall (priority of payments)

The waterfall defines the order in which available funds are distributed on each **Interest Payment Date (IPD)** or **Note Payment Date (NPD)**. A typical Dutch RMBS interest waterfall runs:

1. Senior fees and expenses (trustee, servicer, paying agent, swap counterparty)
2. Interest on Class A notes (senior tranche)
3. Class A Principal Deficiency Ledger (PDL) replenishment
4. Reserve fund replenishment to target level
5. Interest on Class B notes
6. Class B PDL replenishment
7. Interest on Class C notes (and so on down the stack)
8. Deferred purchase price to seller
9. Residual to equity holders

**Principal waterfall** (sequential or pro-rata depending on triggers):
- During revolving period: reinvest in new loans
- After revolving: pay down notes sequentially (Class A first) or pro-rata if performance tests pass

**Principal Deficiency Ledger (PDL)**: tracks losses allocated to each tranche. A tranche with a PDL debit may be blocked from interest distributions. PDL amounts are critical signals in investor reports.

**Available Distribution Amount (ADA)**: the total cash available on an IPD from collections, swap receipts, reserve fund draws. Computed as: scheduled interest + scheduled principal + unscheduled principal (prepayments) + recoveries − defaults.

### 2.3 Key performance metrics

**Credit metrics:**

| Metric | Definition |
|---|---|
| **CPR** (Constant Prepayment Rate) | Annualised rate at which loans prepay voluntarily. CPR = 1 − (1 − SMM)^12 where SMM is the single-month mortality rate. |
| **CDR** (Constant Default Rate) | Annualised rate of loans defaulting. Defaults = loans where the servicer has determined loss is inevitable. |
| **SMM** (Single Monthly Mortality) | Monthly prepayment rate: prepayments / (beginning balance − scheduled principal). |
| **PD** (Probability of Default) | Expected share of the pool that will ultimately default. Used in rating models. |
| **LGD** (Loss Given Default) | Expected loss as % of outstanding balance after recoveries. LGD = 1 − Recovery Rate. |
| **EL** (Expected Loss) | PD × LGD × Exposure. Drives credit enhancement sizing. |
| **WA LTV** (Weighted Average Loan-to-Value) | Pool-level average LTV weighted by balance. Key collateral quality metric. |
| **WA Rate** (Weighted Average Interest Rate) | Pool-level weighted interest rate. Determines interest income to the SPV. |
| **WA Seasoning** | Weighted average loan age in months. Older pools typically have lower default risk. |
| **WA Remaining Term** | Weighted average months to maturity. Affects prepayment and extension risk. |

**Arrears definitions (vary by deal — always check the prospectus):**

Arrears in European RMBS are typically defined as missed scheduled payments. Common thresholds:
- **30+ days past due**: earliest watchlist; loan is "in arrears"
- **60+ days past due**: active collection procedures typically begin
- **90+ days past due**: often the EBA/ESMA default trigger for regulatory purposes
- **180+ days past due**: often formal default declaration in Dutch deals

**Cure**: a loan that was in arrears returns to performing status after sufficient consecutive on-schedule payments. Cure periods vary by deal (typically 3–6 consecutive payments).

**Forbearance**: the servicer grants relief to a struggling borrower (e.g. payment holiday, term extension). Forbearance flags in the tape (`forbearance_flag`) require careful interpretation — a forborne loan may show as "performing" even though it has received concessions.

**Restructuring**: material modification of loan terms. Must be reported separately. A restructured loan that later performs should not be reclassified as "cured" without disclosure.

**Recovery**: cash received on a defaulted loan after enforcement (property sale, guarantee claim). Recovery rates on Dutch RMBS are historically high (85-95%+) due to the NHG guarantee and strong house prices.

### 2.4 Dutch RMBS specifics

The Netherlands has one of the most active RMBS markets in Europe, with over €700 billion in outstanding mortgages. Key features:

**Loan types:**
- **Annuity (annuïteitenhypotheek)**: fixed monthly payment; proportion of interest vs principal shifts over time. Most common post-2013.
- **Linear (lineaire hypotheek)**: fixed principal repayment each month; decreasing interest. Less common.
- **Interest-only (aflossingsvrij)**: no scheduled principal repayment. Widespread pre-2013; restricted for new origination but significant portion of outstanding pools.
- **Savings/investment mortgages (spaar/beleggingshypotheek)**: principal accumulated in parallel savings/investment vehicle; rare in new origination.

**NHG (Nationale Hypotheek Garantie):**
- Government-backed guarantee on qualifying residential mortgages.
- As of 2025, covers loans up to €435,000 (indexed annually).
- On default, WEW (Waarborgfonds Eigen Woningen) covers loss after servicer enforcement, subject to underwriting compliance check.
- NHG-backed loans carry significantly lower LGD assumptions in rating models; capital requirements are also reduced.
- NHG guarantee reduces over time on an annuity basis, regardless of actual repayment type.

**Province and NUTS3 concentration:** Dutch mortgage pools have geographic concentration risk; Noord-Holland, Zuid-Holland, and Utrecht typically command higher house prices and lower LTV ratios than peripheral provinces.

**Interest rate environment (2025):** ECB rates stabilised after 2024 hiking cycle. Dutch mortgage rates are predominantly fixed-rate, creating basis risk between pool yield and EURIBOR-linked note coupons — managed via interest rate swap at deal level. Prepayment rates tend to spike when refinancing offers savings of 50+ bps.

**Arrears:** Dutch RMBS historically show very low arrears (typically <0.5% 90+ days past due). Social safety nets (unemployment benefits, NHG) and cultural aversion to mortgage default keep CDR extremely low by international standards.

---

## PART 3 — REGULATORY FRAMEWORK

### 3.1 EU Securitisation Regulation (2017/2402)

The primary regulatory framework for European securitisation since 1 January 2019. Key requirements:

**Due diligence**: Institutional investors must verify compliance before investing. They must check risk retention, disclosure, and STS status where claimed.

**Risk retention (Article 6)**: The originator, sponsor, or original lender must retain a material net economic interest of at least 5% of the nominal value. Forms: vertical slice (5% of each tranche), seller's interest, first-loss tranche, random sample. Purpose: "skin in the game" aligns originator incentives with investor outcomes.

**Disclosure (Article 7)**: Requires provision of:
- Prospectus / offering document
- Loan-level data (via ESMA templates, to a securitisation repository)
- Investor reports (at minimum quarterly, often monthly for RMBS)
- Significant event / inside information notices

**STS designation**: "Simple, Transparent and Standardised" securitisations receive preferential capital treatment under CRR. Criteria include: true sale, no re-securitisation, no active portfolio management, standardised collateral eligibility, comprehensive disclosure, independent verification agent.

**Reform (June 2025 proposals)**: The European Commission proposed targeted amendments to streamline due diligence, simplify disclosure templates, and reduce reporting burden — particularly for highly granular pools. The RMBS loan-level data requirement is expected to remain mandatory.

### 3.2 ESMA Annex 2 — Residential Real Estate Template

**Mandatory since 1 October 2024** (ESMA templates replaced ECB templates for all ABS seeking Eurosystem collateral eligibility).

The Annex 2 template covers Residential Real Estate exposures and contains fields across these categories:

**Loan identification**: unique loan identifier, SPV identifier, originator identifier, reporting date, ESMA transaction identifier.

**Loan characteristics**: origination date, maturity date, original balance, current balance, currency, repayment type (annuity/linear/bullet/IO), interest rate type (fixed/floating/mixed), current interest rate, remaining fixed period, original term, remaining term, loan purpose.

**Collateral**: property type, property location (country, region/NUTS3), construction year, occupancy status, property valuation, valuation date, valuation method, LTV at origination (OLTOMV), current LTV (CLTOMV), indexed LTV (CLTIMV).

**Borrower**: employment status, income, loan-to-income, number of borrowers, guarantees (e.g. NHG).

**Performance**: current status (performing/arrears/default/restructured/foreclosure), days past due, arrears amount, arrears bucket, default flag, forbearance flag, restructuring flag, foreclosure flag.

**Green fields (Annex 2 includes)**: EPC label, EPC issue year, primary energy demand (kWh/m²/year). These fields enable green verification — whether pool composition matches green eligibility claims.

**"No Data" (ND) options**: ESMA allows ND codes (ND1–ND5) where data is genuinely unavailable. ND1 = collected but not loaded; ND2 = collected but on separate system; ND3 = not collected; ND4 = not applicable; ND5 = no consent. High ND rates on critical fields are a governance red flag.

### 3.3 Investor reports

Monthly (or quarterly) reports published to the ESMA securitisation repository and investor portals. Standard content:

- Portfolio statistics (pool balance, loan count, WA rate, WA seasoning, WA LTV)
- Performance data (CPR, CDR, arrears buckets, defaults, recoveries)
- Cashflow summary (collections, prepayments, scheduled principal, interest, defaults)
- Waterfall execution (distributions to each tranche, reserve fund balance)
- Trigger status (whether performance triggers are breached)
- Principal Deficiency Ledger balances
- Note balances and credit enhancement levels

Dutch RMBS investor reports follow DSA (Dutch Securitisation Association) standards, which align with the EU Securitisation Regulation and ESMA requirements. Report Version 2.1 is the current DSA standard as of 2025.

### 3.4 3-Lines of Defence (3LoD) in securitisation AI context

The 3-Lines of Defence model applied to AI-assisted structured finance analysis:

- **1st Line (Credit)**: The analytical function. Owns the question, the model, and the output. Responsible for the answer and its grounding.
- **2nd Line (Risk)**: Independent challenge. Reviews model assumptions, data quality, and output reliability. Can override or escalate.
- **3rd Line (Audit)**: Independent assurance. Verifies that the 1st and 2nd lines operated correctly; checks citation trail and governance evidence.

In sf-agents, the `lod.credit`, `lod.risk`, and `lod.audit` primitives implement this structure. Their outputs must ultimately be traceable to source documents and tape data to be trusted by regulators.

---

## PART 4 — GREEN / SUSTAINABLE RMBS

### 4.1 What makes an RMBS "green"

A Green RMBS uses note proceeds to finance or refinance mortgages on energy-efficient properties. The Dutch market has been the dominant European producer of Green RMBS since 2016 — over half of European green securitisations have been issued by Dutch institutions.

The eligibility criteria are set in the issuer's **Green Bond Framework** and validated by a **Second Party Opinion (SPO)** from an independent sustainability ratings provider (most commonly ISS Corporate, Sustainalytics, or CICERO Shades of Green).

### 4.2 Green eligibility criteria (Dutch RMBS)

The Dutch Sustainable Finance Framework for RMBS (DSA, updated regularly) sets the following typical criteria:

**EPC label (Energy Performance Certificate)**:
- Properties must have a minimum EPC label, typically A or A+ for new Green RMBS.
- EPC labels (Netherlands, scale A++++ to G) reflect energy efficiency under the NTA 8800 standard (from 2021).
- Older labels (EP Online system pre-2021) are based on different methodology; cross-comparability requires care.
- EPC issue year matters: certificates expire after 10 years.

**Primary Energy Demand (PED):**
- Measured in kWh/m²/year under the NTA 8800 standard (Netherlands, BENG 2 indicator).
- Typical thresholds in Dutch Green RMBS frameworks:
  - Houses (eengezinswoningen): ≤ 50 kWh/m²/year (some frameworks 25–30 for top label)
  - Apartments (meergezinswoningen): ≤ 70 kWh/m²/year
  - ISS SPO frameworks sometimes set stricter thresholds: 27 kWh/m² for houses, 45 for apartments.
- **Critical note**: PED thresholds in the prospectus vs the SPO may differ. Always compare the tape's actual PED distribution against the specific threshold cited in the document being checked.

**Construction deposit (bouwdepot):**
- A feature for new-build or renovation mortgages. Loan proceeds not yet disbursed are held in a deposit; released as construction milestones are met.
- Presence of construction_deposit_flag indicates loans used for construction or energy upgrade purposes.
- Relevant to green eligibility for renovation-focused green frameworks.

**EU Taxonomy alignment:**
- Taxonomy Regulation (EU) 2020/852 + Climate Delegated Act (EU) 2021/2139 define "substantial contribution to climate change mitigation" for mortgages.
- Primary energy performance ≤ 10% of national building stock, or top 15% EPC performance in the country.
- Full EU Taxonomy alignment requires additional DNSH (Do No Significant Harm) screening.

**ICMA Green Bond Principles (GBP, 2025 edition):**
Four core components:
1. **Use of Proceeds**: clearly defined green project categories
2. **Process for Project Evaluation and Selection**: documented eligibility criteria and governance
3. **Management of Proceeds**: tracking allocation, ring-fencing
4. **Reporting**: annual allocation report + impact report

An **SPO** provides independent assessment of framework alignment with GBP. The SPO does not verify that individual loans meet criteria — it verifies the framework's design. **Actual loan-level compliance must be verified from the tape.**

**EU Green Bond Standard (December 2024):**
A voluntary regulatory alternative to ICMA GBP. Stricter requirements on EU Taxonomy alignment and allocation reporting. Growing adoption in the Netherlands.

**CFP (Climate Finance Partnership / Carbon Footprint) impact reports:**
Many Dutch issuers publish annual impact reports alongside the SPO. These report:
- Portfolio energy consumption (PED distribution)
- Carbon emissions avoided vs baseline
- Green share of portfolio
- Construction deposit utilisation

These reports contain specific figures (e.g. "average PED 72 kWh/m²") that can be checked against the loan tape for consistency.

### 4.3 Common green claims verification checks

When checking whether a deal's green claims hold up:

1. **EPC label claim vs tape**: Compare stated minimum EPC label in prospectus/SPO with actual `epc_label` distribution in tape. Flag if % below minimum threshold exceeds stated tolerance.

2. **PED claim vs tape**: Compare stated PED ceiling (e.g. "max 45 kWh/m²") with actual `primary_energy_demand_kwh_m2` distribution. Flag if mean or max exceeds ceiling.

3. **Cross-document consistency**: Does the prospectus state the same threshold as the SPO? Does the CFP report's claimed average PED match the tape's actual average?

4. **EPC currency**: Are the EPC certificates still valid (issue year + 10 years > reporting date)?

5. **Green share claim**: Prospectus may claim "X% of pool meets green criteria". Verify by applying the eligibility criteria deterministically to the tape.

6. **Construction deposit**: If a green renovation element is claimed, verify construction_deposit_flag prevalence matches stated coverage.

---

## PART 5 — DEAL DOCUMENTS

### 5.1 Prospectus

The main legal and commercial disclosure document. For Dutch RMBS, a prospectus typically contains:

- **Transaction overview and parties**: roles, responsibilities, legal structure
- **Risk factors**: comprehensive listing of deal-specific risks
- **Asset overview**: collateral eligibility criteria, pool characteristics at closing
- **Waterfall description**: full priority of payments for interest and principal
- **Defined terms**: formal definitions of all key terms (arrears, default, cure, available distribution amount, etc.)
- **Cashflow mechanics**: how interest and principal flow through the structure
- **Credit enhancement**: description of each form (subordination, reserve fund, excess spread, guarantees)
- **Trigger events**: performance triggers that modify payment priority or restrict distributions
- **Swap structure**: interest rate hedge description
- **Green bond framework**: if applicable, eligibility criteria, use of proceeds, reporting commitments
- **Regulation S / Rule 144A**: selling restrictions

**Critical for sf-agents**: when extracting definitions or deal terms from a prospectus, always note the page number and cite the exact language. Definition sections are typically in the back third of the prospectus (definitions annex). Waterfall is typically in a dedicated "Priority of Payments" or "Cashflows" chapter.

### 5.2 ISS Second Party Opinion (SPO)

An ISS SPO is a document produced by ISS Corporate (formerly ISS ESG), an independent sustainability ratings agency, assessing the issuer's Green Bond / Green Securitisation Framework against:
- ICMA Green Bond Principles
- EU Taxonomy alignment
- DSA Dutch Sustainable Finance Framework

Structure of an ISS SPO:
- **Executive summary**: overall opinion (Dark Green, Medium Green, Light Green, Yellow)
- **Framework assessment**: coverage of four ICMA GBP components
- **Eligibility criteria evaluation**: specific thresholds reviewed
- **Governance and reporting**: quality of monitoring and transparency commitments
- **Controversies**: any negative ESG flags on the issuer

**Key for verification**: the SPO states the eligibility criteria as the issuer defined them in the framework. These are the criteria to compare against the tape. The SPO does NOT independently verify whether individual loans meet criteria.

### 5.3 CFP (Climate Finance Partnership) Impact Report

A separate annual report (often 8–15 pages) disclosing:
- Total green pool balance
- PED distribution (typically average and percentile breakdowns)
- EPC label distribution
- Carbon emissions / avoidance estimates
- Alignment with EU Taxonomy or relevant standard
- Changes vs prior year

### 5.4 Investor Report (Monthly)

Standardised monthly servicer report. DSA Report Version 2.1 structure:
- Page 1: Cover / transaction header
- Page 2: Key dates, note balances, interest rates
- Page 3: Pool performance statistics (balance, count, CPR, CDR, arrears, prepayments, repayments)
- Pages 4-5: Arrears breakdown by bucket, foreclosure statistics
- Pages 6+: Waterfall execution, reserve fund, PDL, note balances, trigger status

**Key fields in investor reports:**
- `Repayments`: scheduled principal collected this period
- `Prepayments`: unscheduled principal collected (voluntary early repayment)
- `Net Outstanding Balance`: pool balance end of period
- `Annualized CPR`: (1 - (prepayments/opening balance))^12 expressed as %
- `Constant Default Rate`: annualised default rate
- `Weighted average current interest rate`: pool yield indicator

---

## PART 6 — LOAN TAPE FIELDS AND INTERPRETATION

### 6.1 Key field groups for analysis

**Identity fields**: loan_id (unique key), transaction_name, esma_transaction_identifier, reporting_date, closing_date, originator_name, servicer_name, currency, country.

**Loan terms**: original_balance, current_balance, repayment_type, interest_only_flag, current_interest_rate_pct, rate_type, remaining_interest_fixed_period_months, seasoning_months, remaining_term_months.

**Collateral**: property_type, province, economic_region_nuts3, construction_year, occupancy, property_usage, oltomv_original (LTV at origination), cltomv_current (current LTV), cltimv_current (indexed LTV).

**Borrower**: employment_status, self_employed_flag, loan_purpose, buy_to_let_flag, nhg_flag, loan_to_income, payment_due_to_income_pct, borrower_annual_income.

**Performance**: performing_status, arrears_bucket, arrears_amount, days_past_due, default_crr_flag, forbearance_flag, restructuring_flag, foreclosure_flag.

**Green**: epc_label, epc_issue_year, primary_energy_demand_kwh_m2, construction_deposit_flag, construction_deposit_pct, construction_deposit_amount.

### 6.2 Common analytical calculations

**Pool balance**: `sum(current_balance)` — headline pool size.

**WA LTV (current)**: `sum(current_balance × cltomv_current) / sum(current_balance)` — weighted by balance.

**WA rate**: `sum(current_balance × current_interest_rate_pct) / sum(current_balance)`.

**Interest-only share**: `sum(current_balance where interest_only_flag='Y') / sum(current_balance)`.

**NHG share**: `sum(current_balance where nhg_flag='Y') / sum(current_balance)`.

**Green share (EPC)**: `sum(current_balance where epc_label in ['A++++','A+++','A++','A+','A']) / sum(current_balance)`.

**Arrears rate (90+)**: `sum(current_balance where arrears_bucket='90-180d' or '>180d') / sum(current_balance)`.

**CPR calculation from tape**: requires two periods. `SMM = unscheduled_prepayments / (opening_balance - scheduled_principal)`. `CPR = 1 - (1 - SMM)^12`.

**PED compliance check**: `count(rows where primary_energy_demand_kwh_m2 <= threshold) / count(rows)` — but only for rows where epc_label is not null.

### 6.3 Period-over-period comparison

When comparing three tape vintages (Jan, Feb, Mar in the Green Lion case):
- Pool shrinks month-on-month from prepayments, defaults, and amortisation
- Performance metrics (arrears %, CPR) should be calculated on the same basis each period
- `reporting_date` identifies which tape is which; cross-check with investor reports for consistency
- Balance drift between tape and investor report is a data quality signal

### 6.4 Data quality flags

| Signal | Interpretation |
|---|---|
| High ND rate on required field | Possible ESMA compliance issue; limits analysis |
| `days_past_due` inconsistent with `arrears_bucket` | Cross-validation failure; data quality concern |
| `epc_issue_year` < reporting_date - 10 | EPC certificate expired; green eligibility questionable |
| `primary_energy_demand_kwh_m2` = 0 or null | Missing green data; cannot verify PED claim |
| `cltomv_current` > 1.0 | LTV > 100%; negative equity; elevated loss severity |
| `current_balance` > `original_balance` | Possible capitalised arrears; requires investigation |
| Large gap between pool balance and sum of tape balances | Tape may not cover full pool; completeness issue |

---

## PART 7 — QUESTIONS AN AGENT SHOULD BE ABLE TO ANSWER

The following are illustrative questions this framework should handle, with notes on what data and reasoning each requires.

### Credit and performance questions
- "What is the current WA LTV and how has it trended over the three periods?" → compute from tape, period-over-period
- "Are arrears rising or falling?" → arrears_bucket distribution across periods
- "What explains the prepayment rate this period?" → CPR from tape, cross-check with investor report, link to rate environment
- "Are the cashflows in the investor report consistent with what the loan tape predicts?" → modelled expected cashflows vs reported; explain gaps
- "Is the CDR consistent with the arrears bucket progression?" → arrears roll rates should feed into defaults with a lag
- "Does the NHG coverage provide meaningful credit enhancement given current house prices?" → NHG share × expected recovery rate vs credit enhancement structure

### Green / ESG questions
- "Do the green claims in the prospectus hold up against the tape?" → extract eligibility criteria, apply to tape, report % meeting each criterion
- "Does the ISS SPO's stated PED threshold match the actual tape?" → extract SPO threshold, compute tape PED distribution, flag discrepancies
- "Is the EPC labelling current (certificates not expired)?" → check epc_issue_year against reporting_date
- "What % of the pool is EU Taxonomy aligned?" → apply taxonomy PED threshold to tape
- "Is the CFP impact report's claimed average PED consistent with the tape?" → compare stated average to computed mean from tape

### Structural / waterfall questions
- "What is the priority of payments for interest distributions?" → extract from prospectus waterfall chapter
- "Is the reserve fund at its target level?" → read from investor report
- "Are any PDL triggers breached?" → investor report; compare to prospectus triggers
- "What happens to senior note principal repayment if CDR exceeds X%?" → prospectus trigger analysis

### Definition and consistency questions
- "How does this deal define 'arrears'?" → extract from prospectus definitions section
- "Does the servicer's arrears definition match ESMA's?" → compare prospectus definition to ESMA Annex 2 field definitions
- "Are the definitions consistent across the prospectus and the investor report?" → cross-document comparison

---

## PART 8 — COMMON MISCONCEPTIONS AND GOTCHAS

**"All citations verified" on a 3LoD run does not mean the analysis is grounded.** If the agents produce zero citations, verification passes trivially. Agents must cite specific pages and tape rows/columns for their claims to be meaningful.

**ESMA Annex 2 fields are mandatory but NDs are permitted.** A field with 100% ND rates is technically compliant but analytically useless. Do not treat ND as a zero value.

**EPC label grade scales differ before and after 2021 (Netherlands).** Pre-NTA 8800 labels (A to G) and post-NTA 8800 labels (A to A++++, G) are not directly comparable. An A label pre-2021 is not the same as an A label post-2021.

**CPR in the investor report is often 1-month annualised, not 12-month average.** Confirm the calculation basis before comparing to historical benchmarks.

**The "green share" depends on exactly which criterion you apply.** A deal may claim 92% green by EPC label ≥ A, but only 60% green if you apply the SPO's stricter PED threshold. Always state which criterion you are measuring.

**LTV at origination ≠ current LTV.** Dutch house prices rose significantly in 2020–2022 and have moderated since; using origination LTV for loss severity overestimates risk for seasoned pools.

**Forbearance masks arrears.** A forborne loan may show 0 days past due if the servicer granted a payment holiday, but it is still under stress. The `forbearance_flag` should be checked alongside `arrears_bucket`.

**The prospectus definition of "default" is deal-specific.** Common triggers: 90+ days past due, formal insolvency, servicer determination of loss likelihood. The ESMA Annex 2 `default_crr_flag` uses CRR Article 178 definition, which may differ from the deal-level default for waterfall purposes.

**Cure definitions vary significantly between deals.** Some require 3 consecutive payments; others require 6; others require a minimum period of performing status. Never assume cure = 3 payments without checking the prospectus.

---

## PART 9 — ABBREVIATIONS REFERENCE

| Abbreviation | Full form |
|---|---|
| ABS | Asset-Backed Securities |
| ADA | Available Distribution Amount |
| BENG | Bijna Energie Neutrale Gebouwen (Nearly Zero-Energy Buildings, NL standard) |
| CDR | Constant Default Rate |
| CE | Credit Enhancement |
| CFP | Climate Finance Partnership (or Carbon Footprint report) |
| CLO | Collateralised Loan Obligation |
| CPR | Constant Prepayment Rate |
| CRR | Capital Requirements Regulation (EU) |
| DSA | Dutch Securitisation Association |
| EL | Expected Loss |
| EPC | Energy Performance Certificate |
| ESMA | European Securities and Markets Authority |
| EU GBS | EU Green Bond Standard |
| GBP | Green Bond Principles (ICMA) |
| ICMA | International Capital Markets Association |
| IO | Interest Only |
| IPD | Interest Payment Date |
| ISS | ISS Corporate (formerly ISS ESG); provider of SPOs |
| LGD | Loss Given Default |
| LTV | Loan-to-Value |
| ND | No Data (ESMA reporting code) |
| NHG | Nationale Hypotheek Garantie |
| NPD | Note Payment Date |
| NUTS3 | EU regional classification (Nomenclature of Territorial Units for Statistics, level 3) |
| PD | Probability of Default |
| PDL | Principal Deficiency Ledger |
| PED | Primary Energy Demand (kWh/m²/year) |
| RMBS | Residential Mortgage-Backed Securities |
| SMM | Single Monthly Mortality |
| SPO | Second Party Opinion |
| SPV | Special Purpose Vehicle |
| STS | Simple, Transparent and Standardised |
| WA | Weighted Average |
| WEW | Waarborgfonds Eigen Woningen (NHG guarantee fund) |

---

*Document prepared June 2026. Grounded in EU Securitisation Regulation 2017/2402, ESMA Annex 2 (v1, November 2025), DSA Dutch Sustainable Finance Framework (2024), ICMA Green Bond Principles (June 2025), EU Green Bond Standard (December 2024), DNB statistics, and Dutch RMBS market practice as of mid-2026.*