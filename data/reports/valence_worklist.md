# Valence adjudication worklist

One row per scoreable-category `(vote, tag)` pair awaiting a valence judgment. `valence = +1` if a **YEA advances** the small-business/affordability axis (lower input costs, easier access to capital, lighter compliance), `-1` if a YEA opposes it, `0` if the vote is not a genuine axis signal (procedural / messaging). **Suggestions are drafts — confirm each before running.** Commit with `vact valence set <vote_id> <TAG> <±1|0>` (or run the generated `.sh`).


## Tier 2 — Substantive passage votes (judge by bill)

| vote_id | tag | date | bill | title | suggest | note |
|---|---|---|---|---|:---:|---|
| `h-119-1-295` | INPUT_COSTS | 2025-11-18 | hjres-131-119 | A joint resolution providing for congressional disapproval u | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-53` | INPUT_COSTS | 2025-02-27 | hjres-20-119 | A joint resolution providing for congressional disapproval u | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-77` | INPUT_COSTS | 2025-03-27 | hjres-24-119 | A joint resolution providing for congressional disapproval u | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-71` | TAX_BURDEN | 2025-03-11 | hjres-25-119 | A joint resolution providing for congressional disapproval u | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-52` | INPUT_COSTS | 2025-02-26 | hjres-35-119 | A joint resolution providing for congressional disapproval u | **+1** | CRA repeal of the EPA methane/waste-emissions charge on oil & gas systems — a YEA lowers energy input costs → +1. Confirm. |
| `h-119-1-52` | REGULATORY_BURDEN | 2025-02-26 | hjres-35-119 | A joint resolution providing for congressional disapproval u | **+1** | CRA repeal of the EPA methane/waste-emissions charge on oil & gas systems — a YEA lowers energy input costs → +1. Confirm. |
| `h-119-1-59` | INPUT_COSTS | 2025-03-05 | hjres-42-119 | A joint resolution providing for congressional disapproval u | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-58` | REGULATORY_BURDEN | 2025-03-05 | hjres-61-119 | A joint resolution providing for congressional disapproval u | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-78` | INPUT_COSTS | 2025-03-27 | hjres-75-119 | A joint resolution providing for congressional disapproval u | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-111` | REGULATORY_BURDEN | 2025-04-30 | hjres-87-119 | A joint resolution providing congressional disapproval under | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-114` | REGULATORY_BURDEN | 2025-05-01 | hjres-88-119 | A joint resolution providing congressional disapproval under | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-112` | REGULATORY_BURDEN | 2025-04-30 | hjres-89-119 | A joint resolution providing congressional disapproval under | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-279` | INPUT_COSTS | 2025-09-18 | hr-1047-119 | GRID Power Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-68` | WORKFORCE | 2025-03-11 | hr-1156-119 | Pandemic Unemployment Fraud Enforcement Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-2-164` | REGULATORY_BURDEN | 2026-05-13 | hr-1346-119 | Nationwide Consumer and Fuel Retailer Choice Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-358` | REGULATORY_BURDEN | 2025-12-18 | hr-1366-119 | Mining Regulatory Clarity Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-304` | INPUT_COSTS | 2025-11-20 | hr-1949-119 | Unlocking our Domestic LNG Potential Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-171` | WORKFORCE | 2025-06-12 | hr-2056-119 | District of Columbia Federal Immigration Compliance Act | **0** | DC immigration-compliance bill tagged WORKFORCE — messaging, not a genuine small-business-climate signal. Consider 0 or re-tag. |
| `h-119-2-19` | WORKFORCE | 2026-01-13 | hr-2262-119 | Flexibility for Workers Education Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-151` | HEALTH_COSTS | 2025-06-04 | hr-2483-119 | SUPPORT for Patients and Communities Reauthorization Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-332` | WORKFORCE | 2025-12-11 | hr-2550-119 | Protect America’s Workforce Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-35` | INPUT_COSTS | 2025-02-07 | hr-26-119 | Protecting American Energy Production Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-153` | ACCESS_TO_CAPITAL | 2025-06-05 | hr-2931-119 | Save SBA from Sanctuary Cities Act | **0** | Conditions SBA funds on sanctuary-city status — immigration messaging, not an access-to-capital change. Consider 0 or re-tag. |
| `h-119-1-156` | ACCESS_TO_CAPITAL | 2025-06-06 | hr-2966-119 | American Entrepreneurs First Act | **-1** | Narrows SBA loan eligibility (citizenship) — a YEA REDUCES access to capital for some firms → -1 under the axis. Low confidence; confirm. |
| `h-119-2-31` | WORKFORCE | 2026-01-15 | hr-2988-119 | Protecting Prudent Investment of Retirement Savings Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-278` | INPUT_COSTS | 2025-09-18 | hr-3015-119 | National Coal Council Reestablishment Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-277` | INPUT_COSTS | 2025-09-18 | hr-3062-119 | Promoting Cross-border Energy Infrastructure Act | **REVIEW** | Cross-border energy permitting tagged WORKFORCE — likely a tag mismatch (INPUT_COSTS?). Re-check tag before valence. |
| `h-119-1-303` | INPUT_COSTS | 2025-11-20 | hr-3109-119 | REFINER Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-15` | TAX_BURDEN | 2025-01-15 | hr-33-119 | To amend the Internal Revenue Code of 1986 to provide specia | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-347` | INPUT_COSTS | 2025-12-17 | hr-3616-119 | Reliable Power Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-2-64` | INPUT_COSTS | 2026-02-11 | hr-3617-119 | Securing America’s Critical Minerals Supply Act | **+1** | Secures domestic critical-mineral supply — a YEA eases input-cost/supply risk → +1. Low confidence; confirm. |
| `h-119-1-323` | INPUT_COSTS | 2025-12-11 | hr-3628-119 | State Planning for Reliability and Affordability Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-342` | INPUT_COSTS | 2025-12-16 | hr-3632-119 | Power Plant Reliability Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-324` | INPUT_COSTS | 2025-12-11 | hr-3638-119 | Electric Supply Chain Act | **+1** | Electric supply-chain security — a YEA eases input-cost/supply risk → +1. Low confidence; confirm. |
| `h-119-1-334` | INPUT_COSTS | 2025-12-12 | hr-3668-119 | Improving Interagency Coordination for Pipeline Reviews Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-262` | FEDERAL_CONTRACTING | 2025-09-10 | hr-3838-119 | Streamlining Procurement for Effective Execution and Deliver | **+1** | This is the FY2026 NDAA (SPEED Act procurement streamlining bundled in) — plausibly pro-contractor → +1, but it's an omnibus defense authorization. Low confidence; confirm. |
| `h-119-1-330` | REGULATORY_BURDEN | 2025-12-11 | hr-3898-119 | PERMIT Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-2-55` | INPUT_COSTS | 2026-02-04 | hr-4090-119 | Critical Mineral Dominance Act | **+1** | Critical-mineral domestic supply — a YEA eases input-cost/supply risk → +1. Low confidence; confirm. |
| `h-119-2-23` | INPUT_COSTS | 2026-01-13 | hr-4593-119 | SHOWER Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-2-76` | INPUT_COSTS | 2026-02-24 | hr-4626-119 | Don’t Mess With My Home Appliances Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-2-134` | INPUT_COSTS | 2026-04-22 | hr-4690-119 | Reliable Federal Infrastructure Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-2-78` | INPUT_COSTS | 2026-02-25 | hr-4758-119 | Homeowner Energy Freedom Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-356` | REGULATORY_BURDEN | 2025-12-18 | hr-4776-119 | SPEED Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-362` | HEALTH_COSTS | 2025-12-18 | hr-498-119 | Do No Harm in Medicaid Act | **REVIEW** | Medicaid restriction bill — contested; not a clean affordability signal. Judge the health-cost direction deliberately. |
| `h-119-2-12` | INPUT_COSTS | 2026-01-09 | hr-5184-119 | Affordable HOMES Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-2-216` | WORKFORCE | 2026-06-09 | hr-5408-119 | Faster Labor Contracts Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-2-137` | INPUT_COSTS | 2026-04-23 | hr-5587-119 | HEATS Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-2-136` | REGULATORY_BURDEN | 2026-04-22 | hr-6387-119 | FIRE Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-2-118` | REGULATORY_BURDEN | 2026-04-16 | hr-6398-119 | RED Tape Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-2-116` | REGULATORY_BURDEN | 2026-04-16 | hr-6409-119 | FENCES Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-349` | HEALTH_COSTS | 2025-12-17 | hr-6703-119 | Lower Health Care Premiums for All Americans Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-2-198` | WORKFORCE | 2026-06-03 | hr-7726-119 | No Funds for Repeat Child Care Violations Act | **REVIEW** | Defunds child-care violators — effect on child-care access/cost is ambiguous. Judge deliberately. |
| `h-119-1-360` | REGULATORY_BURDEN | 2025-12-18 | hr-845-119 | Pet and Livestock Protection Act | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-2-121` | TAX_BURDEN | 2026-04-16 | hres-1156-119 | Expressing support for tax policies that support working fam | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-96` | ACCESS_TO_CAPITAL | 2025-04-09 | sjres-18-119 | A joint resolution disapproving the rule submitted by the Bu | **0** | CRA repeal of the CFPB overdraft-fee cap at very large banks — a consumer bank-fee rule, not small-business capital access (ACCESS_TO_CAPITAL tag misfit). Suggest 0. |
| `h-119-1-143` | REGULATORY_BURDEN | 2025-05-22 | sjres-31-119 | A joint resolution providing for congressional disapproval u | **REVIEW** | No curation note — judge from the title/source. |
| `h-119-1-296` | INPUT_COSTS | 2025-11-18 | sjres-80-119 | A joint resolution providing for congressional disapproval u | **REVIEW** | No curation note — judge from the title/source. |

---

### Source links

- `h-119-1-295` — [hjres-131-119](https://clerk.house.gov/evs/2025/roll295.xml)
- `h-119-1-53` — [hjres-20-119](https://clerk.house.gov/evs/2025/roll053.xml)
- `h-119-1-77` — [hjres-24-119](https://clerk.house.gov/evs/2025/roll077.xml)
- `h-119-1-71` — [hjres-25-119](https://clerk.house.gov/evs/2025/roll071.xml)
- `h-119-1-52` — [hjres-35-119](https://clerk.house.gov/evs/2025/roll052.xml)
- `h-119-1-52` — [hjres-35-119](https://clerk.house.gov/evs/2025/roll052.xml)
- `h-119-1-59` — [hjres-42-119](https://clerk.house.gov/evs/2025/roll059.xml)
- `h-119-1-58` — [hjres-61-119](https://clerk.house.gov/evs/2025/roll058.xml)
- `h-119-1-78` — [hjres-75-119](https://clerk.house.gov/evs/2025/roll078.xml)
- `h-119-1-111` — [hjres-87-119](https://clerk.house.gov/evs/2025/roll111.xml)
- `h-119-1-114` — [hjres-88-119](https://clerk.house.gov/evs/2025/roll114.xml)
- `h-119-1-112` — [hjres-89-119](https://clerk.house.gov/evs/2025/roll112.xml)
- `h-119-1-279` — [hr-1047-119](https://clerk.house.gov/evs/2025/roll279.xml)
- `h-119-1-68` — [hr-1156-119](https://clerk.house.gov/evs/2025/roll068.xml)
- `h-119-2-164` — [hr-1346-119](https://clerk.house.gov/evs/2026/roll164.xml)
- `h-119-1-358` — [hr-1366-119](https://clerk.house.gov/evs/2025/roll358.xml)
- `h-119-1-304` — [hr-1949-119](https://clerk.house.gov/evs/2025/roll304.xml)
- `h-119-1-171` — [hr-2056-119](https://clerk.house.gov/evs/2025/roll171.xml)
- `h-119-2-19` — [hr-2262-119](https://clerk.house.gov/evs/2026/roll019.xml)
- `h-119-1-151` — [hr-2483-119](https://clerk.house.gov/evs/2025/roll151.xml)
- `h-119-1-332` — [hr-2550-119](https://clerk.house.gov/evs/2025/roll332.xml)
- `h-119-1-35` — [hr-26-119](https://clerk.house.gov/evs/2025/roll035.xml)
- `h-119-1-153` — [hr-2931-119](https://clerk.house.gov/evs/2025/roll153.xml)
- `h-119-1-156` — [hr-2966-119](https://clerk.house.gov/evs/2025/roll156.xml)
- `h-119-2-31` — [hr-2988-119](https://clerk.house.gov/evs/2026/roll031.xml)
- `h-119-1-278` — [hr-3015-119](https://clerk.house.gov/evs/2025/roll278.xml)
- `h-119-1-277` — [hr-3062-119](https://clerk.house.gov/evs/2025/roll277.xml)
- `h-119-1-303` — [hr-3109-119](https://clerk.house.gov/evs/2025/roll303.xml)
- `h-119-1-15` — [hr-33-119](https://clerk.house.gov/evs/2025/roll015.xml)
- `h-119-1-347` — [hr-3616-119](https://clerk.house.gov/evs/2025/roll347.xml)
- `h-119-2-64` — [hr-3617-119](https://clerk.house.gov/evs/2026/roll064.xml)
- `h-119-1-323` — [hr-3628-119](https://clerk.house.gov/evs/2025/roll323.xml)
- `h-119-1-342` — [hr-3632-119](https://clerk.house.gov/evs/2025/roll342.xml)
- `h-119-1-324` — [hr-3638-119](https://clerk.house.gov/evs/2025/roll324.xml)
- `h-119-1-334` — [hr-3668-119](https://clerk.house.gov/evs/2025/roll334.xml)
- `h-119-1-262` — [hr-3838-119](https://clerk.house.gov/evs/2025/roll262.xml)
- `h-119-1-330` — [hr-3898-119](https://clerk.house.gov/evs/2025/roll330.xml)
- `h-119-2-55` — [hr-4090-119](https://clerk.house.gov/evs/2026/roll055.xml)
- `h-119-2-23` — [hr-4593-119](https://clerk.house.gov/evs/2026/roll023.xml)
- `h-119-2-76` — [hr-4626-119](https://clerk.house.gov/evs/2026/roll076.xml)
- `h-119-2-134` — [hr-4690-119](https://clerk.house.gov/evs/2026/roll134.xml)
- `h-119-2-78` — [hr-4758-119](https://clerk.house.gov/evs/2026/roll078.xml)
- `h-119-1-356` — [hr-4776-119](https://clerk.house.gov/evs/2025/roll356.xml)
- `h-119-1-362` — [hr-498-119](https://clerk.house.gov/evs/2025/roll362.xml)
- `h-119-2-12` — [hr-5184-119](https://clerk.house.gov/evs/2026/roll012.xml)
- `h-119-2-216` — [hr-5408-119](https://clerk.house.gov/evs/2026/roll216.xml)
- `h-119-2-137` — [hr-5587-119](https://clerk.house.gov/evs/2026/roll137.xml)
- `h-119-2-136` — [hr-6387-119](https://clerk.house.gov/evs/2026/roll136.xml)
- `h-119-2-118` — [hr-6398-119](https://clerk.house.gov/evs/2026/roll118.xml)
- `h-119-2-116` — [hr-6409-119](https://clerk.house.gov/evs/2026/roll116.xml)
- `h-119-1-349` — [hr-6703-119](https://clerk.house.gov/evs/2025/roll349.xml)
- `h-119-2-198` — [hr-7726-119](https://clerk.house.gov/evs/2026/roll198.xml)
- `h-119-1-360` — [hr-845-119](https://clerk.house.gov/evs/2025/roll360.xml)
- `h-119-2-121` — [hres-1156-119](https://clerk.house.gov/evs/2026/roll121.xml)
- `h-119-1-96` — [sjres-18-119](https://clerk.house.gov/evs/2025/roll096.xml)
- `h-119-1-143` — [sjres-31-119](https://clerk.house.gov/evs/2025/roll143.xml)
- `h-119-1-296` — [sjres-80-119](https://clerk.house.gov/evs/2025/roll296.xml)
