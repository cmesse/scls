# Plan — single source of truth for compiler family and OpenMP runtime

**Date:** 2026-08-17
**Author:** Claude (step 1 of the six-step script-change gate)
**Scope:** `python/math_common.py`, `python/rpm_builder.py`, `python/unix_builder.py`,
`python/build_common.py`. No bash script changes proposed.
**Status:** COMPLETE through step 6.

- [x] 1. plan written
- [x] 2. audited by Codex + Grok
- [x] 3. decisions taken (below)
- [x] 4. implemented
- [x] 5. implementation audited by Codex + Grok
- [x] 6. round-2 amendments applied

## Step 3 + 6 decisions

Adopted from round 1: cc/cxx/fc family assertion; MKL interface derived from the
asserted family; keep the raise on unknown/wrapper compilers; `threading:` as a
cross-check with `sequential` meaning `mkl_sequential`; delete the unconsumed
`openmp_libs`; move BOTH Jinja `compiler_family` sites onto the resolver (Grok — the
RPM one guessed from the flavor name, the unix one substring-matched `'icc' in cc`,
which matches `mpicc`).

Adopted from round 2: drop the generic `cc`/`c++` aliases (they can be clang and
would bypass the raise); raise on an unknown `math.threading:` value; raise in
`get_mkl_interface_lib` for LLVM so the MKL policy is one sentence;
`%{mkl_linker_flags}` honours `sequential`; the `accelerate` branch's hardcoded
`-lgomp` now derives from the resolver; guard the two unconditional
`%{mkl_linker_flags}` computations so a non-MKL-policy toolchain does not raise.

~~C5 — strip the OpenMP runtime from `CMAKE_<LANG>_STANDARD_LIBRARIES`~~ REJECTED for
this patch by both auditors and by me. It is the STRUMPACK root-cause fix, it forces a
full mkl+intel stack rebuild, and it needs a Linux `readelf` gate. Christian's call,
separately. If taken: strip inside `get_cmake_args` only, leave
`get_mkl_serial_link_line` / `%{mkl_linker_flags}` alone.

Rejected as out of scope (recipe edits need protocol §7 approval, and this gate covers
scripts): `recipes/mumps.yaml:46,51` hardcodes `-fopenmp`; `recipes/petsc.yaml`
selects `%{libgomp}` vs an absolute `libiomp5.so` per flavor. Both are now documented
out-of-band pins rather than silent divergences.

## Self-caught regression during step 6

Keying the new guard on `flavor.math.linalg == 'mkl'` broke `recipes/blaze.yaml:84-93`,
which expands `%{mkl_linker_flags}` behind a *runtime* MKLROOT test and so is reached
on gnu flavors too — `BLAS_LIBS` went empty on gcc/debug/lbl. Re-keyed the guard on the
toolchain (`compiler_family != 'llvm'`), which is the only thing that actually raises.
Caught by the old-vs-new spec diff, not by either auditor.

## Result

44 generated specs change against HEAD, all intended: `-fopenmp` restored for the six
mpi+openmp+math recipes on every flavor; `-qopenmp` on intel MUMPS; intel
`CMAKE_*_STANDARD_LIBRARIES` moved to the Intel MKL ABI (the P0 from the previous
round). GCC flavors remain 100% gomp — verified by grepping every generated gcc, mkl,
debug, lbl and gcc-mkl-cuda spec for `iomp5`/`mkl_intel_thread`: zero hits. Generation
error count unchanged (135, all pre-existing macOS-host failures).

## Problem being solved

The stack's rule is *the OpenMP runtime follows the compiler, never the math library*:

| compiler family | OpenMP flag | runtime | MKL threading | MKL interface |
|---|---|---|---|---|
| gnu   | `-fopenmp` | `libgomp`  | `mkl_gnu_thread`   | `mkl_gf_*`    |
| intel | `-qopenmp` | `libiomp5` | `mkl_intel_thread` | `mkl_intel_*` |
| llvm  | `-fopenmp` | `libomp` (Linux) / `libgomp` (macOS) | n/a | n/a |

That rule is correct but is currently decided in **six** places that do not agree:

1. `math_common.get_mkl_interface_lib:18-21` — "icx-family, else GNU" (default-to-gnu).
2. `math_common.get_mkl_serial_link_line:30-39` — same default-to-gnu rule.
3. `math_common.get_math_link_line:102,114` — `compiler == 'gcc'` **exactly**, elif
   icx-family, **else nothing at all** (no runtime, no MKL threading layer).
4. `math_common.get_math_compile_flags:213-219` — matches `gcc`/`g++`/`gfortran`.
5. `rpm_builder.py:955-956` — hardcoded `-fopenmp` / `-lgomp`, compiler-blind.
6. `unix_builder.py:1543-1544` — the same hardcode.

Three different definitions of "is this GCC" (1/2 vs 3 vs 4) is the hole the `mpicc`
override fell through: it produced a silent default in some functions and a silent
no-op in others. A seventh decision point, `math.threading:` in every flavor YAML, is
read at `math_common.py:59` but only ever consulted inside one clang sub-condition —
it is inert for gnu and intel, i.e. a placebo knob.

## Proposed changes

### C1 — `math_common.py`: one resolver, everything derives from it

Add, as the only place a compiler family is ever decided:

```python
_FAMILY_BY_NAME = {
    'gcc': 'gnu', 'g++': 'gnu', 'gfortran': 'gnu', 'gnu': 'gnu',
    'icx': 'intel', 'icpx': 'intel', 'icc': 'intel', 'icpc': 'intel',
    'ifx': 'intel', 'ifort': 'intel',
    'clang': 'llvm', 'clang++': 'llvm', 'flang': 'llvm',
}
_MPI_WRAPPERS = {'mpicc', 'mpicxx', 'mpic++', 'mpiCC', 'mpifort', 'mpif77',
                 'mpif90', 'mpiicc', 'mpiicpc', 'mpiifort'}

def compiler_family(flavor: Dict) -> str:
    """'gnu' | 'intel' | 'llvm' — the single source of truth."""
```

Resolution rules, in order:

1. Take `flavor['compilers']['cc']`.
2. `os.path.basename()` it, so bootstrap's `/usr/bin/gcc` and a gcc-toolset absolute
   path both resolve (this also closes the latent bootstrap gap the last review
   raised).
3. Strip a trailing `-<version>` suffix (`gcc-13` -> `gcc`).
4. If the result is an MPI wrapper, **raise `ValueError`** with a message naming the
   caller's mistake ("resolve native compilers before asking for a compiler family").
5. If the result is not in `_FAMILY_BY_NAME`, **raise `ValueError`**.

Raising rather than defaulting is the point: an unrecognised compiler currently
produces a wrong-but-silent link line. Spec generation is cheap and runs on the dev
host, so a misconfiguration fails at `--spec-only` instead of shipping a mixed ABI.

Derived helpers, each a one-liner over `compiler_family`:

```python
def openmp_flag(flavor) -> str          # '-fopenmp' | '-qopenmp'
def openmp_runtime_lib(flavor) -> str   # '-lgomp' | '-liomp5' | '-lomp'
def mkl_threading_lib(flavor) -> str    # 'mkl_gnu_thread' | 'mkl_intel_thread'
def mkl_interface_lib(flavor) -> str    # existing name, reimplemented on the resolver
```

`openmp_runtime_lib` keeps today's macOS/llvm special case (`-lgomp` on macOS,
`-lomp` on Linux) — SCLS's macOS flavor is gcc-based, so this branch is currently
unreachable, but the behaviour is preserved rather than changed.

Then rewrite the four existing functions to call these and delete their private
compiler tests. Behaviour for gnu and intel is unchanged; the only semantic change is
that a previously-silent fallthrough now raises.

### C2 — `math.threading:` becomes a cross-check, not a second source of truth

Keep the field, give it one job: assert what the flavor intends, and fail if it
contradicts the compiler.

- `threading: openmp` or `threading: intel` -> MKL uses a threading layer; **which**
  runtime is still decided solely by `compiler_family`.
- `threading: sequential` -> `mkl_sequential`, no OpenMP runtime.
- `threading: intel` with a non-intel compiler family (or `openmp` with intel) ->
  raise, naming both the flavor field and the compiler.

No flavor YAML changes needed: `intel.yaml` (`icx` + `intel`) and the six gcc flavors
(`gcc` + `openmp`) are all already consistent. This turns the placebo into a guard.

### C3 — `rpm_builder.py`: use the resolver, and finish the `math_flavor()` fix

- `955-956`: `context['openmp_flag'] = openmp_flag(self.math_flavor())`.
- Delete `context['openmp_libs']` entirely — it is set in both builders and consumed
  by no template or recipe (verified by grep). Dead code that encodes a duplicate
  policy decision is exactly what this plan is removing.
- **`1457-1459`: pass `self.math_flavor()` into `get_cmake_args`.** This is the P0
  regression the last review confirmed: `CMAKE_CXX_STANDARD_LIBRARIES` currently
  keeps the gfortran MKL ABI while `TPL_BLAS_LIBRARIES` takes the Intel ABI, on one
  cmake line, on the intel flavor.

### C4 — `unix_builder.py`: same treatment

- `1543-1544`: derive `openmp_flag` from the resolver; drop `openmp_libs`.
- `get_cmake_args` at `338` already receives the unmutated flavor — no change, but
  the audit should confirm unix_builder never mutates `flavor['compilers']`.

### C5 (SEPARATE DECISION — needs Christian's explicit sign-off before I apply it)

`build_common.get_cmake_args:785` builds `CMAKE_{C,CXX}_STANDARD_LIBRARIES` from
`get_mkl_serial_link_line`, which includes the OpenMP runtime. The literal `-lgomp`
in that variable is the confirmed root cause of the STRUMPACK probe failure: it makes
any cmake `try_compile` that links an OpenMP imported target link with **no** OpenMP
runtime and fail (measured; see `devlog/dl20260817_strumpack_openmp_tasking.md`).

Proposal: emit the MKL libraries in `CMAKE_<LANG>_STANDARD_LIBRARIES` **without** the
OpenMP runtime, and let `-fopenmp`/`-qopenmp` in `CFLAGS`/`CXXFLAGS` supply it.

- Pro: fixes the root cause for every mkl/intel cmake package at once, and the
  recipe-level pin in `recipes/strumpack.yaml` becomes belt-and-braces.
- Con: changes the link line of **every** mkl and intel package -> full rebuild of
  both stacks. Packages that link MKL's `mkl_gnu_thread` but are *not* compiled with
  `-fopenmp` would lose their `DT_NEEDED libgomp`. Fix C3/C4 restore `-fopenmp` for
  mpi+openmp+math recipes, but a package with `features.math` and
  `features.openmp: false` would be affected.
- This is a packaging/ABI decision, not an AI-vote question.

## Explicitly NOT in scope

- No recipe or flavor YAML edits.
- No change to the gnu-vs-intel policy itself — only to how many places decide it.
- No bash script changes.

## Verification plan

- [x] `--spec-only` for every recipe x all six Linux flavors, old vs new, diffed
- [x] Assert the only intended diffs appear (intel `CMAKE_*_STANDARD_LIBRARIES`
      moving to the Intel ABI; no other spec changes)
- [x] Unit-ish check of `compiler_family` against every flavor YAML plus
      `bootstrap_compilers` and a gcc-toolset absolute path
- [x] Confirm the raise path triggers on `mpicc` and on an unknown compiler
- [x] Dev-host ceiling: no `rpmbuild`, no install test. Anything about runtime
      behaviour stays pending a Linux build host.

## Open questions for the auditors

1. Is raising on an unknown/MPI compiler too aggressive for a build system, given it
   turns a misconfigured flavor into a hard spec-generation failure?
2. Does C2 (`threading:` as a cross-check) actually add value, or should the field be
   deleted outright?
3. Is `openmp_libs` genuinely dead? I grepped `templates/` and `recipes/`; confirm.
4. Have I missed a seventh place where an OpenMP runtime or MKL threading layer is
   chosen — including anything in `deb_builder.py`, which inherits `UnixBuilder`?
5. C5: does removing the OpenMP runtime from `CMAKE_<LANG>_STANDARD_LIBRARIES` break
   any package that links MKL threaded but does not compile with `-fopenmp`?
