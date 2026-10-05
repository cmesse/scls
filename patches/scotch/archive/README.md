# Archived Scotch patches

Patches in this directory are **not applied**. No recipe lists them and the builders read only the
files a recipe names under `patches:`.

| File | For | Why it is here |
|---|---|---|
| `scotch-shared-7.0.16.patch` | Scotch 7.0.16 | `scotch-shared.patch` with its context refreshed against the 7.0.16 tarball on 2026-10-04 (one of seven hunks no longer applied at fuzz 0: upstream added an `add_dependencies` block next to `scotcherrexit` in `src/libscotch/CMakeLists.txt`). The 29 changed lines are identical to the 7.0.15 patch. All three Scotch patches applied at fuzz 0, in recipe order, with this file in place of `scotch-shared.patch`. |

Scotch stays at the version PETSc pins (`doc/CAMPAIGN_POLICY.md` §9); PETSc 3.26.0 pins 7.0.15.
When PETSc moves to 7.0.16, copy the archived file over `../scotch-shared.patch`, re-run
`patch -p1 --dry-run -N -F0` for all three, and delete it from here.
