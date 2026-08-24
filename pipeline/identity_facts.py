"""Declared company identity — the ONE table the identity gates consult before any string
heuristic. To make an acquired company's board legitimate, add a row here; nothing else.

**Why a table.** "There are Israel jobs on this page" is not "these are THIS company's
jobs", and no string predicate can separate INHERITANCE (Momentis really does post under
its acquirer's `memic` tenant) from THEFT (Bancor onto The Bancorp Bank's iCIMS). The
gates in `pipeline/identity_gate.py` spent seven adversarial waves calibrating heuristics
for that distinction — the parenthetical `A (B)` split, tail-word stripping, a ±1
near-match — and each wave's record ends with the same sentence: the fix is a
DECLARATION, not a cleverer string test (`docs/BACKLOG.md` registry items 21, 49, 50, 61,
69, 71). This is the declaration.

**Semantics — exact, and authoritative for declared rows.**

* `tenants` — the normalized ATS tenant tokens this company legitimately posts under
  (`_norm`: lowercase, alphanumerics only). Consulted by `identity_gate.tenant_is_this_company`
  (against the board host's non-plumbing SUBDOMAIN labels) and `identity_gate.embedded_board_ok`
  (against the board's own token). **Both directions:** a declared row whose checkable tenant
  is not declared is REFUSED. Never matched against a URL PATH — `novartis.wd3.myworkdayjobs
  .com/en-US/riskified` is Novartis's Workday with a site named `riskified`, and a path match
  would walk that incident back in through this table.
* `domains` — domain suffixes an ordinary (non-ATS) careers host may carry for this company.
  Admit-only; consulted by `company_identity.verdict` (this key IS the old `KNOWN_PARENT`).
* `why` — the evidence: the board URL, the acquisition, the date. Required. A row without
  evidence is a guess, and a guess here publishes one company's roles under another's name.

Undeclared rows keep the heuristics. Declared rows skip them entirely — which is also why a
declared row never builds `_name_targets`, so the generic-adjacent-parenthetical residual
(`Citrix (Cloud Software Group)` -> `cloud`, item 71) cannot fire on a declared row.

**What NOT to declare here.**

* Slug-vocabulary misses — `Hippo Insurance`/`hippo70`, `Prilenia Therapeutics`/`prilenia`,
  `Valens Semiconductor`/`valens`, `7AI`/`sevenai`, `Ibex Medical Analytics`/`ib1` — are
  `_NAME_FILLER`/`_TENANT_SUFFIX` vocabulary, item 71's finding, not identity facts. Declaring
  them would hide that finding under this table.
* Opaque Comeet uids (`60.002`) — the uid comes from the company's own page and cannot vouch
  either way; that class stays a visible suspect by design (item 61).
* `pipeline/firmographics.ALIASES` declares four of the same acquisitions for a DIFFERENT
  question (dedup keys for firmographics joins). Two questions, two tables — the same note
  `identity_gate._PLATFORM_ALIAS` carries about `_FETCHER_ALIAS`: "unifying" them
  re-introduces the mis-join it looks like it fixes.

**Finding candidates** (re-run before adding; the registry is rewritten nightly):

    python -c "import csv,urllib.parse;from pipeline import identity_gate as G;from pipeline.company_identity import ATS_HOST;rows=[r for r in csv.reader(open('companies.csv',encoding='utf-8')) if r and len(r)>=6][1:];[print(r[0],'->',r[3][:60]) for r in rows if r[4]=='true' and (r[3] or '').startswith('http') and ATS_HOST.search(urllib.parse.urlparse(r[3]).netloc or '') and not G.tenant_is_this_company(r[0],r[3])]"

prints every ACTIVE ATS row the tenant rule refuses. Each is either an acquisition to
declare (with evidence) or a wrong board to park — never a reason to loosen the rule.

This module imports nothing from `pipeline/` and never reads `companies.csv` at import:
the behavioural fixtures chdir into three-row scratch registries. `validate(rows)` below
is what the test suite runs against the real one.
"""
from __future__ import annotations

import re

# One entry per registry row (exact `company_name`, matched case-insensitively). Keep the
# `why` honest and dated: it is the only thing standing between "declared" and "guessed".
DECLARED = {
    # --- the seven `A (B)` Workday acquisitions the parenthetical heuristic used to admit;
    #     declared so the heuristic can be deleted (wave-5 measurement: exactly these seven)
    "Merck (MSD)": {
        "tenants": ("msd",),
        "why": "msd.wd5.myworkdayjobs.com is MSD's own Workday; Merck & Co posts as MSD ex-US. 2026-08-24"},
    "VMware (Broadcom)": {
        "tenants": ("broadcom",),
        "why": "acquired by Broadcom 2023; board is broadcom.wd1.myworkdayjobs.com. 2026-08-24"},
    "Splunk (Cisco)": {
        "tenants": ("cisco",),
        "why": "acquired by Cisco 2024; board is cisco.wd5.myworkdayjobs.com. 2026-08-24"},
    "Habana Labs (Intel)": {
        "tenants": ("intel",),
        "why": "acquired by Intel 2019; board is intel.wd1.myworkdayjobs.com (item 49's worked example). 2026-08-24"},
    "Sony (Sony Semiconductor Israel)": {
        "tenants": ("sonyglobal",),
        "why": "Sony group board sonyglobal.wd1.myworkdayjobs.com carries the Israel semiconductor site. 2026-08-24"},
    "Aristocrat (Product Madness)": {
        "tenants": ("aristocrat",),
        "why": "Product Madness is an Aristocrat studio; board is aristocrat.wd3.myworkdayjobs.com. 2026-08-24"},
    "Flex (Flextronics)": {
        "tenants": ("flextronics",),
        "why": "Flex's legal tenant is flextronics: flextronics.wd1.myworkdayjobs.com. 2026-08-24"},

    # --- brand/parent domains, migrated verbatim from company_identity.KNOWN_PARENT
    #     (admit-only, ordinary hosts; each was verified by hand when it was added there)
    "AWS": {"domains": ("amazon.jobs", "amazon.com"), "why": "KNOWN_PARENT migration"},
    "Amazon Web Services": {"domains": ("amazon.jobs", "amazon.com"),
                            "why": "KNOWN_PARENT migration; a synonym key, not a registry row"},
    "Google Israel": {"domains": ("google.com", "abc.xyz"), "why": "KNOWN_PARENT migration"},
    "Microsoft Israel": {"domains": ("microsoft.com",), "why": "KNOWN_PARENT migration"},
    "Microsoft (Xbox/Gaming)": {"domains": ("microsoft.com",), "why": "KNOWN_PARENT migration"},
    "Volkswagen (CARIAD)": {"domains": ("volkswagen-group.com", "cariad.technology"),
                            "why": "KNOWN_PARENT migration"},
    "Siemens Digital Industries Software": {"domains": ("sw.siemens.com", "siemens.com"),
                                            "why": "KNOWN_PARENT migration"},
    "Siemens EDA": {"domains": ("sw.siemens.com", "siemens.com"), "why": "KNOWN_PARENT migration"},
    "Applied Materials Israel": {"domains": ("appliedmaterials.com",), "why": "KNOWN_PARENT migration"},
    "GE HealthCare Israel": {"domains": ("gehealthcare.com",), "why": "KNOWN_PARENT migration"},
    "Procter & Gamble": {"domains": ("pgcareers.com",), "why": "KNOWN_PARENT migration"},
    "Deutsche Post DHL": {"domains": ("dhl.com",), "why": "KNOWN_PARENT migration"},
    "Johnson & Johnson": {"domains": ("jnj.com",), "why": "KNOWN_PARENT migration"},
    "General Motors Israel": {"domains": ("gm.com",), "why": "KNOWN_PARENT migration"},
    "UserWay": {"domains": ("levelaccess.com",), "why": "acquired by Level Access; KNOWN_PARENT migration"},
    "Abbott": {"domains": ("jobs.abbott",), "why": "KNOWN_PARENT migration"},
    "ABB": {"domains": ("careers.abb", "abb.com"), "why": "KNOWN_PARENT migration"},
}

# Deliberately NOT declared, and why -- so the next reader does not "fix" them:
#   OTORIO -> armissecurity: the row is inactive with an empty api_url and Armis is
#     active on that same board; declaring it is a coverage choice (a duplicate active
#     board pair), not a repair.  Siemens Healthineers: its own page says only "Siemens";
#     a `names` hook was cut -- short strict names are the Sight/Sight-Sciences hazard
#     (item 50). Comeet-uid rows, and every `_NAME_FILLER` vocabulary miss: see above.


def _key(name):
    return " ".join((name or "").strip().lower().split())


_INDEX = {_key(k): v for k, v in DECLARED.items()}
assert len(_INDEX) == len(DECLARED), "two DECLARED keys differ only by case/whitespace"


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def facts(name):
    """The declaration for this registry name, or {} -- never raises."""
    return _INDEX.get(_key(name), {})


def tenants(name):
    """Declared ATS tenant tokens, normalized; empty frozenset when undeclared."""
    return frozenset(_norm(t) for t in facts(name).get("tenants", ()) if _norm(t))


def domains(name):
    """Declared ordinary-host domain suffixes (the old KNOWN_PARENT contract)."""
    return tuple(facts(name).get("domains", ()))


def validate(rows, ats_host_rx, plumbing):
    """Self-consistency of DECLARED against the real registry. Returns a list of problems
    (empty = consistent). Called by the test suite, never at import.

    `rows` are companies.csv body rows; `ats_host_rx` is `company_identity.ATS_HOST`;
    `plumbing(label)` is `identity_gate._plumbing`.
    """
    import urllib.parse
    by_name = {_key(r[0]): r for r in rows if r and len(r) >= 6}
    problems = []
    for name, d in DECLARED.items():
        if not d.get("why"):
            problems.append(f"{name}: no `why` -- a declaration without evidence is a guess")
        if not d.get("tenants") and not d.get("domains"):
            problems.append(f"{name}: declares nothing")
        row = by_name.get(_key(name))
        if d.get("tenants"):
            if row is None:
                problems.append(f"{name}: declares tenants but is not a registry row")
                continue
            host = (urllib.parse.urlparse(row[3] or "").netloc or "").lower()
            if host and ats_host_rx.search(host):
                labels = [_norm(l) for l in host.split(".")[:-2] if not plumbing(l)]
                tok = _norm((row[2] or "").split("/")[0])
                declared = {_norm(t) for t in d["tenants"]}
                if labels and not (declared & set(labels)):
                    problems.append(f"{name}: declared tenants {sorted(declared)} match none of "
                                    f"the board's subdomain labels {labels} ({row[3][:60]})")
                elif not labels and tok and tok not in declared \
                        and (row[3] or "") not in d["why"]:
                    problems.append(f"{name}: declared tenants {sorted(declared)} do not match "
                                    f"the row's token {tok!r} and `why` does not name the board")
    return problems
