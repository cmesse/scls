# GKlib is built static, on purpose

**Decision:** GKlib ships as `libGKlib.a` and is absorbed whole into
`libmetis.so`. It is never built as a shared library.

**Status:** settled 2026-08-18. Revisit only if upstream starts tagging
releases and setting a SOVERSION.

## What the arrangement is

`recipes/gklib.yaml` builds a static archive with `-fPIC`.
`patches/metis/metis-libmetis.patch` then links it into METIS with
`-Wl,--whole-archive`, so every GKlib symbol lands inside `libmetis.so`:

```cmake
find_library(GKLIB_LIBRARY GKlib PATHS ${GKLIB_PATH}/lib ...)
target_link_libraries(metis ... -Wl,--whole-archive ${GKLIB_LIBRARY} -Wl,--no-whole-archive m)
```

Measured on the installed `debug` flavor: `libmetis.so.0` exports **639**
`gk_*` symbols. `libparmetis.so` exports **none** — it picks them up at runtime
through `DT_NEEDED: libmetis.so.0`, and needs GKlib only as headers at build
time.

The result is the single-library interface METIS 5.1.0 had, which is what
downstream software actually targets. The `metis` registry entry advertises
exactly that:

```yaml
ldflags: -L/opt/scls/debug/lib -lmetis
```

No recipe in the stack other than `metis`, `parmetis` and `gklib` itself
mentions GKlib. PETSc, SuperLU_DIST, MUMPS and STRUMPACK all reference
`libmetis.so` / `libparmetis.so` by path.

## Why not shared

The `-lmetis` interface is **not** the deciding argument, and it is worth being
precise about that, because it is the intuitive answer and it is wrong.
Downstream code calls `METIS_*`, never `gk_*`. A shared GKlib would be resolved
internally through `DT_NEEDED` on `libmetis.so`, so `-lmetis` alone would keep
working and no consumer would have to name GKlib. Shared would not break the
link line.

What settles it is **ABI versioning**:

- Upstream KarypisLab/GKlib publishes **no releases**. This stack pins a commit
  (`e2856c2f595b`) and the `0.0.1` in the recipe is our invention.
- Upstream's `CMakeLists.txt` offers `option(SHARED "enable shared support" OFF)`
  and sets no `VERSION`/`SOVERSION` properties. A shared build would therefore
  carry an **unversioned SONAME** (`libGKlib.so`), the same wart
  `libparmetis.so` already has.
- SCLS builds with `AutoReqProv: no` by deliberate policy (see
  [`MKL_ABI_POLICY.md`](MKL_ABI_POLICY.md)), so RPM/DEB metadata does not record
  SONAME dependencies. An ABI change would surface at runtime, not install time.

Together those mean a shared GKlib would ask us to maintain an ABI contract
that upstream does not maintain, on a library we track by commit, with no
mechanism to detect a break. That is exactly the failure mode documented for
MKL, except self-inflicted and on every commit bump rather than every major
release.

Upstream defaulting `SHARED` to `OFF` is taken as the developers' own judgement
about the stability of that interface, and we follow it.

## What shared would and would not buy

| | static (chosen) | shared |
|---|---|---|
| `-lmetis` alone works | yes | yes, via `DT_NEEDED` |
| ABI contract required | none | invented, unversioned, unenforceable |
| `gk_*` symbols global | yes, from `libmetis.so` | yes, from `libGKlib.so` |
| runtime dependency | none | mandatory |
| cost of a GKlib fix | relink metis + parmetis | relink nothing |
| footprint | ~166 KB, duplicated once | ~166 KB, shared |

Shared buys only the relink saving. It does **not** reduce `gk_*` namespace
pollution — those symbols are globally exported either way, just from a
different object.

## Consequences

- A GKlib change requires rebuilding **metis and parmetis**, in that order.
  Neither is expensive. Installing a new gklib on its own changes nothing at
  runtime, because the code users execute lives inside `libmetis.so`.
- GKlib is a **build-time** dependency only. Nothing resolves against it at
  runtime, so it does not belong in a flavor's runtime closure.
- Because `libGKlib.a` is installed next to `libmetis.so`, linking
  `-lmetis -lGKlib` would produce duplicate `gk_*` definitions. Downstreams
  should link `-lmetis` alone, as the registry entry says.
- `recipes/gklib.yaml` passes `-DSHARED=OFF`. Upstream's option is `SHARED`,
  **not** `BUILD_SHARED_LIBS` — the recipe previously passed the latter, which
  did nothing; the static build was coming from the upstream default alone.
