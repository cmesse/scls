# Plan: `libscotchmetis` in the Scotch recipe — keep the build, namespace the symbols?

**Status:** investigation only, deferred 2026-09-22 as out of scope. No recipe change made.
**Update 2026-10-04:** measured on the macOS install; see the addendum at the end. Backlog item, not a blocker (`doc/CAMPAIGN_POLICY.md` §2: present in the published packages, not made worse by the campaign).
**Author:** Claude, 2026-09-22
**Trigger:** "what is libscotchmetis used for? If it is not required when we have metis, can we turn this off?"
**Hardware caveat:** macOS dev host — no `rpmbuild`, and the question can only be *closed* by a
real Linux build plus a PETSc partitioner run. Everything below is a static source trace
(protocol level 5) against the tarballs in `work/sources/`.

## Question

`recipes/scotch.yaml:48` sets `-DBUILD_LIBSCOTCHMETIS=ON`. Since SCLS ships real METIS and
ParMETIS, is the Scotch METIS-emulation layer dead weight that can be switched off?

## Finding 1 — the serial shim is unused, but the switch is not fine-grained

`libscotchmetisv3` / `libscotchmetisv5` implement the METIS C API (`METIS_PartGraphKway`,
`METIS_NodeND`, …) on top of Scotch. Nothing in the stack links them, and
`-DINSTALL_METIS_HEADERS=OFF` (`recipes/scotch.yaml:50`) already keeps Scotch's `metis.h` out of
the prefix, so nothing *can* compile against them.

But `BUILD_LIBSCOTCHMETIS` gates the entire `src/libscotchmetis` subdirectory
(`src/CMakeLists.txt:220-222`, Scotch 7.0.11 tarball), and that directory also builds
**`libptscotchparmetisv3`** (`src/libscotchmetis/CMakeLists.txt:162`) — the ParMETIS-API layer over
PT-Scotch. Scotch offers no separate switch for the two.

## Finding 2 — PETSc hard-requires `libptscotchparmetis*`

`config/BuildSystem/config/packages/PTSCOTCH.py:13-14` (checked in the **3.25.0** tarball;
the recipe is at 3.25.4, so re-confirm before acting):

```python
self.liblist = [['libptesmumps.a','libptscotchparmetisv3.a','libptscotch.a','libptscotcherr.a',
                 'libesmumps.a','libscotch.a','libscotcherr.a'],
                ['libptesmumps.a','libptscotchparmetis.a','libptscotch.a','libptscotcherr.a',
                 'libesmumps.a','libscotch.a','libscotcherr.a']]
```

Both alternatives need a ptscotchparmetis library. Dropping `BUILD_LIBSCOTCHMETIS` therefore breaks
`--with-ptscotch-dir=%{prefix}` (`recipes/petsc.yaml:144`) at PETSc configure time.

**Conclusion: do not turn the option off.** The saving is two unused `.so` files; the cost is PETSc.
Other Scotch consumers do not use the shim either way — `mumps` takes `esmumps`
(`-DBUILD_LIBESMUMPS=ON`, a separate switch), `strumpack` takes `TPL_ENABLE_SCOTCH/PTSCOTCH`.
STRUMPACK's own `FindSCOTCH.cmake` was **not** inspected (no tarball locally); check it before any
change.

## Finding 3 — the real issue: unprefixed symbols collide with the genuine ParMETIS

`SCOTCH_METIS_PREFIX` is not set, so it defaults OFF
(`src/libscotchmetis/CMakeLists.txt:96-97,177-178`), and `libptscotchparmetisv3.so` exports
unprefixed `ParMETIS_V3_*` — the same symbols as the real `libparmetis.so`. PETSc links **both**
(`recipes/petsc.yaml:34-35,142-144`), so which implementation a `ParMETIS_V3_PartKway` call binds to
is link-order dependent. `AutoReqProv: no` means nothing in the package metadata would ever flag it.

Not known to be broken today — no misbehaviour has been reported — but it is an unexamined
interposition hazard, not a design choice we made.

## Proposed work (deferred)

1. On a Linux build host, check what actually binds today:
   `nm -D --defined-only` on `libparmetis.so` and `libptscotchparmetisv3.so` for the overlap, then
   `LD_DEBUG=bindings` on a PETSc run using the ParMETIS partitioner.
2. If the shim wins any binding, add `-DSCOTCH_METIS_PREFIX=ON` to `recipes/scotch.yaml`. This
   renames Scotch's copies to `SCOTCH_*` while still producing the library *files* PETSc's link
   check looks for, so Finding 2 stays satisfied — but that must be confirmed, not assumed:
   PETSc's check links the library, it does not only stat it.
3. Re-run the PETSc and STRUMPACK test suites. Regenerate `files/scotch.txt` only if the installed
   set changes (it should not; the prefix affects symbol names, not filenames).

## Gate

Recipe edit requires explicit approval (CLAUDE.md edit-safety) and the six-step script/recipe gate:
plan → two blind audits → decide → implement → two blind audits → adjust. Nothing here is
actionable on the macOS dev host.

## Addendum 2026-10-04 — measured on the macOS install (scotch 7.0.11, petsc 3.25.0)

Evidence level: executed on the macOS dev host against `/opt/scls` (`otool -L`, `nm -m`,
`nm -gU`). Older versions than the recipes (7.0.15, 3.25.5); nothing measured on Linux.

**Who links the compatibility libraries.** Only `libpetsc` and `libslepc` carry
`libptscotchparmetisv3` as a dependency. Nothing links `libscotchmetisv3`/`v5`. MUMPS links
`ptesmumps`/`ptscotch`/`scotch` (`templates/mumps/Makefile.inc.j2:65`); STRUMPACK does not link
either compatibility library. `PETSc.pc` and `petscvariables` list `-lptscotchparmetisv3`.

**PETSc needs the ParMETIS-compatible library.** `PTSCOTCH.py` is unchanged between PETSc 3.25.0
(local tarball) and the `v3.25.5` tag (fetched 2026-10-04): both link alternatives list a
`libptscotchparmetis*`, and `functionsDefine = ['SCOTCH_ParMETIS_V3_NodeND']`. The installed
`libpetsc` imports `SCOTCH_ParMETIS_V3_NodeND` from it.

**Finding 3 is real, not hypothetical.** `libpetsc` imports, per `nm -m`:

| symbol | bound to |
|---|---|
| `ParMETIS_V3_PartKway`, `ParMETIS_V3_Mesh2Dual` | `libptscotchparmetisv3` (Scotch's emulation) |
| `ParMETIS_V3_AdaptiveRepart`, `ParMETIS_V3_RefineKway`, `ParMETIS_V32_NodeND` | `libparmetis` |
| `METIS_NodeND`, `METIS_PartGraphKway`, `METIS_PartGraphRecursive`, `METIS_SetDefaultOptions` | `libmetis` |

PETSc's link line has `-lptscotchparmetisv3` before `-lparmetis`. So PETSc's `parmetis`
partitioner runs PT-Scotch for k-way partitioning and the real ParMETIS for repartitioning and
refinement. `libparmetis` and `libptscotchparmetisv3` export 20 common names (four functions in
five spellings each); `libmetis` and `libscotchmetisv3` export 30.

**Upstream's configuration.** PETSc builds its own Scotch with `-DSCOTCH_METIS_PREFIX:BOOL=ON`
and `-DINSTALL_METIS_HEADERS:BOOL=OFF` (`PTSCOTCH.py`, `formCMakeConfigureArgs`). SCLS sets only
the second.

### Impact radius

| Option | Changes | Builds | Notes |
|---|---|---|---|
| **A. Leave** | none | 0 | PETSc's `parmetis` k-way partitioner keeps running PT-Scotch |
| **B. `-DSCOTCH_METIS_PREFIX=ON`** | `recipes/scotch.yaml` (one option) | scotch on 14 host/flavor cells; macOS and lbl source builds | Matches PETSc upstream. On ELF the already-built `libpetsc` should then resolve `ParMETIS_V3_PartKway` from `libparmetis` without a rebuild (lookup is by name across loaded libraries) — **inferred, to be confirmed on one Linux host**. macOS needs petsc and slepc rebuilt (two-level namespace). Manifest expected unchanged (file names do not change) — unconfirmed |
| **C. `-DBUILD_LIBSCOTCHMETIS=OFF`** | scotch recipe; `files/scotch.txt` (10 lines); petsc: drop `--with-ptscotch-dir` or patch `PTSCOTCH.py` | scotch, petsc, slepc: 3 x 14 = 42 cells, petsc being the longest build in the stack | petsc and slepc must rebuild because they carry the library as a dependency and would not load. petsc 3.25.5-1 and slepc 3.25.2-1 are published, so both need a release bump. Dropping PT-Scotch from PETSc removes its `ptscotch` partitioner |

scotch 7.0.15-2 has been published on noble and resolute since 2026-10-05 UTC, so the option costs a
release bump (7.0.15-3). mumps, strumpack and ipopt are unaffected by either option: `libscotch`,
`libptscotch` and `libesmumps` keep their SONAMEs.

**Decision (Christian, 2026-10-04): option B, stay close to PETSc upstream.** `-DSCOTCH_METIS_PREFIX=ON`
goes into the next math campaign together with the PETSc bump. PETSc `v3.26.0` still builds its own
Scotch 7.0.15 with `-DSCOTCH_METIS_PREFIX:BOOL=ON` and still links `libptscotchparmetisv3`
(`PTSCOTCH.py` at that tag, fetched 2026-10-04). Option C was weighed and dropped: it needs a patch to
`PTSCOTCH.py`, removes PT-Scotch nested-dissection ordering
(`src/mat/graphops/partition/impls/scotch/scotch.c:296-306` in 3.25.0), and rebuilds petsc and slepc for
no gain over B. Gate for the campaign: on Linux, every `ParMETIS_V3_*` import of `libpetsc.so` binds to
`libparmetis.so`.
