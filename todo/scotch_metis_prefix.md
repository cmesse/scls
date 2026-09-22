# Plan: `libscotchmetis` in the Scotch recipe — keep the build, namespace the symbols?

**Status:** investigation only, deferred 2026-09-22 as out of scope. No recipe change made.
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
