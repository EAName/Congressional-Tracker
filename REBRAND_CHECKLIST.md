# Rebrand checklist — Old Dominion Vote Index (placeholder)

Manual steps outside the repository. Complete before the first **public** launch of race pages under the new identity.

## Content freeze (launch gate)

- [ ] **No social posting or screenshot distribution** of the old-brand UI once race pages are feature-complete.
- [ ] The first public artifact of the race pages (site, OG images, shared links) must carry the **new** identity from `config/brand.json` only.

## In-repo (automated / already wired)

- [x] `config/brand.json` — single source for site name, tagline, domain, canonical base, GitHub, social handles
- [x] `config/brand_blocklist.yaml` + `tests/test_brand_blocklist.py` — CI fails on old brand strings in scanned surfaces
- [x] `content/about.md` → exported to `web/data/about.json` — authorship on `/about`, not in banner
- [x] Footer disclosure updated (Prompt 16) — independent analysis + link to About
- [x] `web/next.config.mjs` — 308 redirects from legacy hostnames for top paths
- [x] `web/app/sitemap.ts` + `web/app/robots.ts` — canonical URLs on new domain
- [x] OG race images read `brand.site_name` (no party banner text)
- [x] Advocacy-verb lint + symmetry audit unchanged (`vact audit symmetry`)

## Config swap (when final name is chosen)

- [ ] Edit `config/brand.json`: `site_name`, `domain`, `canonical_base`, remove `*_note` TODO flags
- [ ] Run `./bin/vact export-web` and redeploy
- [ ] Re-run `uv run pytest tests/test_brand_blocklist.py tests/test_advocacy_lint.py -q`

## Vercel / DNS

- [ ] Create or rename Vercel project for **new domain** (do not reuse partisan-era analytics property)
- [ ] Attach production domain from `brand.json`
- [ ] Configure legacy domain (`democratsforvirginia.org`, `www.`) to point at same project **or** edge redirect to new domain
- [ ] Verify 308 redirects for top 20 paths (see `brand.redirect_paths`):
  - `/`, `/analysis`, `/methodology`, `/about`, `/corrections`
  - `/race/va-01`, `/race/va-02`, `/race/va-05`
  - `/races`, `/races/va-01`, …
  - `/delegation`, `/district/1` … `/district/7`
- [ ] Confirm `sitemap.xml` and `robots.txt` on production use new `canonical_base`

## GitHub

- [ ] Rename repository / update description to match new public identity (optional: keep git remote URL stable)
- [ ] Update repo About text and social preview image
- [ ] Pin `config/brand.json` domain in README (replace partisan references)

## Google Sheets audit workbook

- [ ] Re-point `VACT_SHEETS_ID` if workbook is renamed or recreated under new branding
- [ ] Confirm README tab shows new site name (from brand config on next `vact sheets push`)
- [ ] Notify operators that Sheets is **audit only**, not the activist surface

## Analytics

- [ ] **Separate analytics property** for new domain — do not commingle partisan-era traffic with independent-brand launch metrics
- [ ] Archive or read-only old property; document cutover date

## Social handles

- [ ] Register/update handles listed in `config/brand.json` → `social`
- [ ] Update link-in-bio to new domain
- [ ] Purge or unlist cached OG previews on Twitter/Slack/iMessage (platform-specific debugger tools)

## Counsel / compliance

- [ ] Review `COMPLIANCE_QUESTIONS.md` with counsel under new disclosure model
- [ ] Approve footer + About language; update `config/site_disclosure.yaml` if counsel requires race-page disclaimers

## Smoke test before announce

- [ ] `make derived` (or `vact export-web`) green
- [ ] `uv run pytest tests/test_brand_blocklist.py tests/test_advocacy_lint.py -q`
- [ ] `cd web && npm run build`
- [ ] Spot-check `/`, `/race/va-02`, `/about`, `/methodology`, race OG PNG
- [ ] Grep production HTML/JSON for blocklist terms (should be zero outside `/about` affiliation prose)
