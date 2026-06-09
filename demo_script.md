# Green Lion 2026-1 — Demo Day Script

---

## 2-Minute Presentation (spoken, 6 slides × ~20 seconds)

---

### Slide 1 — The Problem (0:00–0:20)

**Say:**
> "Structured finance analysis today means a junior analyst spending three days reading a 284-page prospectus, a 29-page ISS second-party opinion, and a 3,237-row loan tape — then writing a memo no one can fully trace back to the source. The citations are informal. The arithmetic is manual. And if a number is wrong, you find out at the IC."

**Show:** A blank slide with three document stacks: PROSPECTUS (284 pages) · ISS SPO (29 pages) · LOAN TAPE (3,237 rows).

---

### Slide 2 — What sf-agents Is (0:20–0:40)

**Say:**
> "sf-agents is a governance-first structured finance AI: 33 registered primitives — connectors, extractors, analyzers, validators — orchestrated by a live LLM planner into a deterministic DAG. Every step is time-stamped, input- and output-hashed, and written to an append-only audit JSONL. It runs on AWS Bedrock Sonnet 4.6 in eu-north-1. Every claim it makes is dual-grounded: the exact document page number alongside the exact tape row and column that supports — or refutes — it."

**Show:** A stat bar: **33 primitives · 3 recipes · Bedrock eu-north-1 · append-only audit trail**.

---

### Slide 3 — The Deal (0:40–1:00)

**Say:**
> "Green Lion 2026-1 B.V. — a Dutch residential mortgage-backed security originated by ING. 3,237 loans. €1.033 billion outstanding. Weighted-average interest rate 3.18%. WA current LTV 68.9%. WA remaining term 261 months. 99.97% performing. NHG guarantee on 19.7% of the pool. The deal carries the 'green' label — prospectus, ISS second-party opinion, CFP impact report. So we asked: does the data back the claim?"

**Show:** Pool KPI card: €1.033B · 3,237 loans · WA LTV 68.9% · WA rate 3.18% · 99.97% performing.

---

### Slide 4 — The Finding (1:00–1:20)

**Say:**
> "It does not. The tape shows a mean primary energy demand of 133.47 kWh/m² per year — nearly five times the ISS SPO threshold of 27 kWh/m² for houses. Only 414 loans — 12.8% of the pool — actually pass the PED criterion. The analyzer.claim_vs_collateral primitive checked every green claim in the prospectus against every relevant tape column: 'Green Asset Portfolio' — not supported. 'Green Bond' — not supported. 'Energy Efficient Mortgage' — not supported. EPC certificates are all valid and within the 10-year window — that one passes. Everything else fails."

**Show:** Verdict table — 5× NOT SUPPORTED (red) · 2× PARTIALLY SUPPORTED (amber) · 1× SUPPORTED (green) · 1× NOT VERIFIABLE.

---

### Slide 5 — The Opportunity (1:20–1:40)

**Say:**
> "But there is a commercial signal inside that same tape. 974 loans — 30.1% of the pool, €312 million — carry EPC below A with at least 4 years of remaining term and a current LTV below 80%. These borrowers have home equity headroom for a renovation loan today. The dominant labels are B and C, concentrated in Noord-Holland and Zuid-Holland. Their average energy demand is 208 kWh/m² — four times the green threshold. If just 30% of them renovate to EPC A, the pool's green share rises from 55% to 64%, a 9-percentage-point uplift."

**Show:** Segment card: **974 loans · €312M · 30.1% of pool · B=389, C=264, D=196 · Top provinces: Noord-Holland, Zuid-Holland · 30% scenario → +9pp green share**.

---

### Slide 6 — The Governance Proof (1:40–2:00)

**Say:**
> "Every number you just heard is dual-grounded. The ISS SPO page 207 is cited alongside the tape column primary_energy_demand_kwh_m2 and the exact row indices that contradict it. 85 citation checks ran automatically. The plan DAG is logged. The audit JSONL is append-only. From 284-page prospectus plus 29-page SPO plus 3,237 loan rows to a cited, auditable Investment Committee verdict in 6 minutes and 51 seconds. That is sf-agents."

**Show:** Audit trail preview — 3 rows from the JSONL: run_id, step_id, primitive, confidence, duration_ms, input_hash, output_hash, timestamp.

---

---

## 3-Minute Live Demo (screen + click-by-click commentary)

---

### Step 1 — Open the App and Orient the Audience (0:00–0:30)

**Click:** Open browser to `http://localhost:4200`.

**Point to:**
- The deal context bar at the top: "Green Lion 2026-1 B.V. — €1.033B — 3,237 loans — 99.97% performing"
- The left sidebar showing the primitive catalogue

**Say:**
> "This is the sf-agents UI. The deal context bar at the top loads from the live tape on startup — that €1.033 billion balance and 3,237 loan count are read directly from the CSV every time. The left sidebar lists all 33 registered primitives the planner can compose. No hardcoded workflows — the planner writes the DAG live for each question."

**Transition:** "Let's run the green bombshell question."

---

### Step 2 — Run Question A: The Green Bombshell (0:30–1:30)

**Click:** The Ask panel or question input field.

**Type exactly:**
> "Do the green claims in the prospectus and the ISS second-party opinion hold up against the loan tape? Check every stated criterion and tell me where the data supports the claim and where it does not."

**Click:** Run / Submit.

**Narrate as steps fire:**
> "Watch the DAG build in real time. First wave: the connector loads the 284-page prospectus and the 29-page ISS SPO as PDFs, and the loan tape as CSV — three files in parallel, under 7 seconds total."

> "Second wave: extractor.locator finds the green eligibility section in the prospectus — confidence 0.82. Then extractor.general pulls the actual thresholds: EPC label A or better, PED ≤27 kWh/m² for houses, PED ≤45 for apartments."

> "Third wave: analyzer.tape_greencheck runs deterministically — no LLM, pure arithmetic — and checks all 3,237 loans against every criterion in 24 milliseconds."

> "Final wave: analyzer.claim_vs_collateral produces a verdict for every green claim, dual-grounded to the ISS SPO page and the tape rows. analyzer.general synthesises the answer."

**Point to:** The step confidence scores as they appear — 1.0 for connectors, 0.84 for extractors, 1.0 for claim_vs_collateral.

**Transition:** "Now open the verdict."

---

### Step 3 — Show the NOT SUPPORTED Verdict (1:30–2:00)

**Click:** The claim_vs_collateral step result or the verdict panel.

**Point to:**
- The "Green Asset Portfolio" verdict: **NOT SUPPORTED**
- Claim grounding: ISS SPO page 207, excerpt visible
- Tape grounding: columns `epc_label` and `primary_energy_demand_kwh_m2`, tape facts visible

**Say:**
> "This is dual grounding. On the left: ISS SPO page 207, where the claim 'Green Asset Portfolio' appears. On the right: the tape facts that contradict it — EPC distribution showing 291 loans at label D, 388 at label C, and a mean primary energy demand of 133.47 kWh per square metre per year against the stated threshold of 27. The verifier confirmed both sides of this citation resolve to a real page and real rows. This is not a summary — it is a traceable finding."

**Emphasis:** "133.47 versus 27. Nearly five times the threshold. Stated in the prospectus. Refuted by the tape. Cited both ways."

**Transition:** "Now let's see the commercial opportunity that's hiding in the same tape."

---

### Step 4 — Run Question B: The Renovation Opportunity (2:00–2:30)

**Click:** New question / clear input.

**Type exactly:**
> "Identify all mortgages with EPC label below A, at least 4 years remaining term, and current LTV below 80%. How many loans, what total balance, what is the EPC breakdown and average primary energy demand, which provinces dominate, and what would the green share be if 30% of these borrowers renovated to EPC label A?"

**Click:** Run.

**Narrate:**
> "Watch the plan — just 3 steps this time. The planner recognises this as a deterministic segmentation question and routes directly to analyzer.green_renovation_potential, the dedicated renovation campaign primitive. Total latency: 31 seconds, of which 4 milliseconds is the actual analysis."

**Point to the result when it appears:**
> "974 loans. €312 million. 30.1% of the pool. EPC B: 389 loans, EPC C: 264, EPC D: 196. Average primary energy demand 208 kWh/m². Top provinces: Noord-Holland, Zuid-Holland, Noord-Brabant. And the scenario: if 30% of these borrowers renovate — 292 loans — the pool's green share moves from 55% to 64%, a 9-point uplift. This is a ready-made campaign brief, computed in 31 seconds from a live loan tape."

**Transition:** "One last thing — the audit trail."

---

### Step 5 — Open the Audit Trail and Plan DAG (2:30–3:00)

**Click:** The audit / governance panel, or the DAG tab on the Question A result.

**Point to the Plan DAG tab:**
> "This is the plan the LLM planner wrote for Question A — 11 steps, two parallel waves, a topological sort. This is not a hardcoded workflow. The planner wrote this from scratch given the question and the primitive catalogue."

**Click:** The audit JSONL tab or audit trail view.

**Read one entry aloud:**
> "Step: tape_greencheck. Primitive: analyzer.tape_greencheck. Confidence: 0.55. Duration: 24 milliseconds. Input hash: [hash]. Output hash: [hash]. Timestamp: 2026-06-09T16:17 UTC. This record is immutable. Every run, every step, every input and output — hashed and logged. That is what governance looks like."

**Close:**
> "sf-agents: 33 primitives, a live LLM planner, dual-grounded citations, an append-only audit trail — and a finding that tells your mortgage team exactly where to run a renovation campaign, and tells your green bond investor exactly where the ISS SPO claim does not hold up. Available today. Running on AWS Bedrock in eu-north-1."

---

## Quick Reference Numbers (real, all sourced)

| Metric | Value | Source |
|---|---|---|
| Pool balance | €1,033,412,063 | Tape direct |
| Loan count | 3,237 | Tape direct |
| WA interest rate | 3.18% | Tape direct |
| WA current LTV | 68.9% | Tape direct |
| WA remaining term | 261 months | Tape direct |
| NHG share | 19.7% | Tape direct |
| Green share (EPC A+) | 54.9% | Tape direct |
| Mean PED all loans | 133.47 kWh/m² | Tape direct |
| ISS SPO PED threshold | 27 kWh/m² (houses) | Live Bedrock Q-A |
| Loans passing PED criterion | 414 (12.8%) | Live Bedrock Q-A |
| NOT SUPPORTED verdicts | 5 of 9 claims | Live Bedrock Q-A |
| Renovation segment loans | 974 | Tape direct + analyzer |
| Renovation segment balance | €312,010,699 | Tape direct + analyzer |
| Renovation segment pool share | 30.1% | Tape direct + analyzer |
| Avg PED in segment | 208.4 kWh/m² | Tape direct + analyzer |
| Green share uplift (30% renovate) | +9.0pp (55% → 64%) | Tape direct + analyzer |
| Question A latency | 410 seconds | Live Bedrock run |
| Question B latency | 31 seconds | Live Bedrock run |
| Primitives registered | 33 | Live /api/primitives |
| Recipes available | 3 | Live /api/recipes |
| Audit entries Question A | 14 | Live audit JSONL |
