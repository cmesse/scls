# Licence policy restated: published binaries BSD-3-compatible, no GPL; website build-tools table

**Date:** 2026-10-05 (PDT)
**Host:** macOS dev host; website rendered with `./makeweb`. No package was built.
**Topic:** restate the licence policy as Christian intends it, in every standing document and on
the website; make the website generator follow it
**Auditors:** Codex `gpt-5.6-terra` `xhigh`, Grok `grok-4.7` `xhigh`; plan round and
implementation round, both blind. Exchange: `tmp/ai_exchange/plan_license_policy_no_gpl.md`.
**Verification:** generation gate for the website (below). The policy text is reviewed, not
verified; it is engineering policy, not a counsel opinion.

## Decision (Christian, 2026-10-05)

Published binaries must all be BSD-3 or compatible, no GPL. GPL is allowed for build tools in the
build scripts, because macOS and unsupported Unix systems may need them. pkg-config belongs to the
build-tools section of the website.

## What the rule means in the documents

- "Compatible" is written out as: permissive, or weak copyleft whose obligations attach to the
  library itself (LGPL, CeCILL-C, EPL-2.0). mumps and scotch (CeCILL-C) and ipopt (EPL-2.0) are in
  every published flavor, so a bare "BSD-3-compatible" would have contradicted the package table.
- EPL-2.0 is new to `doc/LICENSE_POLICY.md`. The policy did not mention it although ipopt has
  shipped since 3.14.20-1. The wording follows EPL-2.0 section 1 (a work that only contains
  declarations and interfaces in order to link or bind by name is not a "Modified Work"); checked
  by Grok against upstream Ipopt 3.14.20 `LICENSE:41-48`. Application to a given downstream
  product is left to that product's counsel.
- The GCC runtime stays the one case where the output of GPL code is linked into what ships
  (GCC Runtime Library Exception). It is named wherever "no GPL" is stated.
- GMP/MPFR/MPC are unchanged: system packages on the public flavors, built in-stack on `lbl` and
  `macos`.

## Changes

- `doc/LICENSE_POLICY.md`: new lead rule "Published Binaries"; "GPL-3 Linkable Libraries" and
  "GPL-2 Libraries" merged into "GPL Linkable Libraries"; "GPL-3 Build Tools" is now "GPL Build
  Tools" (any version, pkg-config added, reason stated); "Weak-Copyleft Libraries" with the EPL-2.0
  paragraph; summary list rewritten (the "GPL-2-or-later scientific libraries allowed" line is
  gone).
- `README.md`, `CLAUDE.md` (Licensing), `doc/AI_COLLABORATION_PROTOCOL.md` (review-priority row 7),
  `.claude/commands/update-plan.md` (exclusion table): same rule.
- `web/scls.html.j2`: Design-Philosophy bullet and Packages intro; section "Source-Only Packages
  (GPL-3 / LGPL-3)" is now "Build Tools and Toolchain Prerequisites (GPL / LGPL)"; display strings
  for gcc (with the exception), gmp ("or"), sed.
- `python/generate_website.py`: `split_packages()` no longer keys on the substring `GPL-3`.
  - a package on a public flavor (gcc, mkl, debug) goes to the shipped table;
  - a GPL-family package that no public flavor ships and `macos` builds goes to the build-tools
    table (adds pkg-config);
  - a package on a public flavor whose licence string names the GPL, or that is gmp, mpfr or mpc,
    is a policy violation: the generator exits 1 and writes no page. A recipe or flavor file that
    fails to load, or a missing public flavor, is fatal too (before, it was a warning and the file
    was skipped).
  The GPL test is lexical: `LGPLv3+ or GPLv2+` counts as GPL. Codex asked for an allowance for
  the dual licence, Grok against; no allowance, since GMP is excluded from the public flavors by
  name anyway.

## Gates that ran

- `./makeweb` rc=0. Shipped table: the same 40 names as before the change. Build-tools table: the
  previous 11 plus pkg-config. Tag-balance parse of `scls.html`: empty stack.
- Synthetic recipe sets (copy of `recipes/` plus one file enabled for `gcc`): GPL-2.0-or-later,
  mpfr, gmp, an unparsable recipe: rc=1, no output file. LGPL-2.1-or-later: rc=0, listed as shipped.
  Flavor directory without `mkl.yaml`: rc=1, no output.

## Open

- The website is not deployed. Its table shows recipe versions, so deployment follows the
  publication of the 2026-10-04 campaign (`todo/backlog.md` §1).
- Two items found by the auditors and not changed, because they are builder and staging-script
  edits (`todo/backlog.md` §4): the builders' licence warning is keyed on the substring `GPL-3`
  (`python/rpm_builder.py:2323-2328`, `python/unix_builder.py:1544-1549`; `deb_builder.py` has
  none), and nothing checks licences at staging beyond the hard-coded SuiteSparse entry.
- `CLAUDE.md` and protocol row 7 say GMP/MPFR/MPC "use system `*-devel`"; no recipe requires
  `mpc-devel`, and `mpc` is an `lbl`-only package (Grok, P2). Wording left as it was.

## Files

- doc/LICENSE_POLICY.md, README.md, CLAUDE.md, doc/AI_COLLABORATION_PROTOCOL.md
- .claude/commands/update-plan.md
- web/scls.html.j2, python/generate_website.py
- todo/backlog.md
- devlog/dl20261005_license_policy_no_gpl.md (this file), devlog/README.md
