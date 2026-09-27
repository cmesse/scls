# Devlog 2026-09-26 — Ipopt 3.14.20 recipe and the RPM autotools argument gap

**Date:** 2026-09-26
**Topic:** New recipe `recipes/ipopt.yaml` (Ipopt 3.14.20, EPL-2.0) on top of the stack's MPI MUMPS; first autotools recipe to need an SCLS placeholder in `configure.args`, which exposed that the RPM builder neither expands nor quotes them
**AIs involved:** Claude (Fable 5.1), Codex (gpt-5.6-terra/high), Grok (grok-4.7/high) — one blind jury round on the recipe
**Claude Confidence:** high on the recipe's unix/deb behaviour (full build + 7/7 tests on macOS); high on the RPM defect (rendered spec in hand); medium (~70%) on the RPM %check passing as root
**Auditor Confidence:** high (both); both independently found the RPM defect and the then-missing manifest
**Flavor / Host:** macos flavor built and tested on the Intel macOS dev host (GCC in /opt/scls, MUMPS 5.8.2 registry); RPM claims top out at `--spec-only`
**Upstream References:** upstream Ipopt 3.14.20 `configure.ac:76-84,116,131-141,149,221-227,235-240,379-385,470-490,498-507`; `configure:25185-25264,25278-25279,25356,25728,25933,26397-26418`; `src/Algorithm/LinearSolvers/IpMumpsSolverInterface.cpp:24-29,56-78`; `Makefile.am:13,17-18`; `src/Makefile.am:7-8,84,299-300`; `contrib/sIPOPT/src/Makefile.am:7-22`; `test/Makefile.am:11-18`; `LICENSE:1`
**Verification:** full build + `make test` (7/7 passed) with `python python/unix_builder.py --package ipopt --flavor macos build test`; staged `make install DESTDIR=` for the manifest; `validate_project.py` clean; `build_order.py` resolves; `--spec-only` for mkl/gcc/debug/intel/gcc-mkl-cuda generates. **Not done:** any Linux build, RPM install, `%check` as root.

## Summary

Ipopt fits: a leaf package, autotools, every dependency already in every flavor. The recipe
builds and passes upstream's unit tests on macOS against the stack's MPI MUMPS and OpenBLAS.
The RPM side cannot build it yet: `rpm_builder.get_direct_configure_command` writes recipe
`configure.args` into the spec verbatim, so `%{math_ldflags}` reaches rpm as a literal and the
space-bearing MUMPS link line splits into separate configure words. Ipopt is the first autotools
recipe to use either. A 38-line builder fix is prototyped and rendered but **not applied** — it
is a `python/` change and needs Christian's approval. Two policy items are also his: EPL-2.0 is
not in `doc/LICENSE_POLICY.md`, and the singleton `MPI_Init` on library load is kept at upstream's
default.

## Key Findings

- **F1 (P0, all RPM flavors): autotools `configure.args` bypass macro expansion and quoting on
  the RPM path.** `rpm_builder.py:888-902` appends recipe args raw, `:930-957` joins them
  unquoted; `check_args` (`:640-700`) is never called for this path and the template's
  quote-if-space rule (`templates/default.spec.j2:169,189`) covers only cmake/custom. The unix
  and deb builders are correct (`unix_builder.py:352`, `deb_builder.py:210`). Rendered result
  before the fix, `scls-mkl-ipopt.spec:94-96`:
  `--with-lapack-lflags=%{math_ldflags}` and `--with-mumps-lflags=-L%{prefix}/lib -ldmumps
  -lmumps_common -lpord` (unquoted). Consequence (Grok): an empty lapack flag falls through to
  Ipopt's own probe, which on Linux tries `-lmkl_intel_lp64 -lmkl_sequential -lmkl_core`
  (`configure:25278-25279`) — the Intel-ABI, sequential layer, against the stack's
  `mkl_gf_lp64` + `gnu_thread` policy (`math_common.py:184-230`).
- **F2 (P2): the RPM path does not add `%{math_ldflags}` to the exported LDFLAGS** for
  autotools+math recipes (`unix_builder.py:233` does). Harmless for ipopt once F1 lands because
  the LAPACK line goes in through `--with-lapack-lflags`; recorded as a divergence.
- **MKL Pardiso needs nothing extra.** `--with-lapack-lflags` carries `libmkl_core` on the MKL
  flavors; configure finds `pardiso` there and defines `IPOPT_HAS_PARDISO_MKL`
  (`configure.ac:221-227`). On the macOS/OpenBLAS build the probe correctly failed
  (`config.h:125` undefined). Pardiso from pardiso-project.org is proprietary and not
  considered; users can dlopen it at runtime through the loader that stays on.
- **MPI at load.** `libipopt` links `libmpi` (mpicxx) and its MUMPS interface calls `MPI_Init`
  in a constructor when not already initialised, `MPI_Finalize` in a destructor
  (`IpMumpsSolverInterface.cpp:56-78`; `config.h:52,164`). Kept at upstream default: with the
  MPI MUMPS a non-MPI caller would otherwise crash inside MUMPS. Worked as a singleton on macOS.
- **`%setup -n`.** GitHub's archive of tag `releases/3.14.20` extracts to
  `Ipopt-releases-3.14.20`; `_resolve_source_directory` (`rpm_builder.py:1308-1336`) auto-detects
  only when the tarball is in SOURCES. Pinned with `source.directory:` so the spec is right
  regardless.
- **Manifest.** 94 entries: `include/coin-or/*` (Ipopt + sIpopt headers), `libipopt.so{,.*}`,
  `libsipopt.so{,.*}` (SONAME .3), `lib/pkgconfig/ipopt.pc`, `share/doc/ipopt/{AUTHORS,
  ChangeLog.md,LICENSE,README.md}`. `.la` files excluded (deleted by both builders). License text
  reaches the package via upstream `doc_DATA` with no install hook.
- **Runtime closure (macOS `otool -L`):** libdmumps, libmumps_common, libpord, libopenblas,
  libmpi, libstdc++, libgcc_s — all covered by `requires: openmpi, mumps`, the flavor math
  provider and `environment`.
- Out of scope, noted: `rpm_builder.py:502-505` derives `mkl_root` from the flavor *name*
  containing "mkl", so the `intel` flavor leaves `%{mklroot}` literal on the cmake path
  (`scls-intel-scalapack.spec:125`); intel is source-build only today. `binutils.yaml:6-7`
  `--host=%{host}` is likewise unexpanded on the RPM path; binutils is lbl/macos only.

## Changes Made / Proposed

Made (all approved scope for "write a recipe"):
- `recipes/ipopt.yaml` — new. Decisions and their reasons are in the recipe comments.
- `files/ipopt.txt` — new, from the staged macOS install.
- `changelogs/ipopt.md` — new, 3.14.20-1.

Proposed, **not applied** (needs approval):
1. `python/rpm_builder.py` `get_direct_configure_command`: expand SCLS placeholders via
   `check_args` (keeping `%{prefix}` and `%{cuda}` as the RPM macros the spec defines) and
   single-quote args containing space/;/</>. Rendered with a scratchpad copy for 20
   (recipe, flavor) pairs: 14 existing autotools configure blocks byte-identical, ipopt correct
   on mkl/gcc/debug/gcc-mkl-cuda, binutils `%{host}` becomes the real triplet. Blast radius:
   spec text of existing autotools packages unchanged, so no rebuild is implied by the builder
   change itself. Diff below.
2. `doc/LICENSE_POLICY.md`: add an "EPL-2.0 Libraries" section (weak copyleft; source of the
   EPL module itself must be available — met by SRPM / source DMG; no obligation on linking
   programs; not GPL) and list EPL-2.0 beside LGPL / CeCILL-C in the summary. Attempted this
   session; blocked by the permission gate, so left for Christian.

### Proposed diff for python/rpm_builder.py

```diff
--- python/rpm_builder.py	2026-09-22 00:14:53
+++ /private/tmp/claude-501/-Users-christian-codes-scls/f3e90fee-9598-4e98-96b5-b53a270c80d8/scratchpad/fixroot/python/rpm_builder.py	2026-09-26 20:13:41
@@ -939,7 +939,35 @@
 
         # Get our custom configure arguments with RPM macros preserved
         args = self.get_configure_args_for_rpm()
+
+        # Expand SCLS placeholders (%{math_ldflags}, %{mkl_linker_flags},
+        # %{libext}, ...) exactly as unix_builder.configure does through
+        # check_args (unix_builder.py:352), so an autotools recipe renders the
+        # same configure line on every builder. %{prefix} and %{cuda} are the
+        # two placeholders the spec itself defines as RPM macros
+        # (templates/default.spec.j2:5,19); they are kept as macros rather
+        # than expanded to literal paths, so existing autotools specs render
+        # unchanged. Added for ipopt, the first autotools recipe to use
+        # %{math_ldflags} in configure.args; before this the placeholder
+        # reached the spec verbatim and rpm passed it through as a literal.
+        keep = {'%{prefix}': '@SCLS_RPM_PREFIX@', '%{cuda}': '@SCLS_RPM_CUDA@'}
+        for macro, sentinel in keep.items():
+            args = [a.replace(macro, sentinel) for a in args]
+        args = self.check_args(args)
+        for macro, sentinel in keep.items():
+            args = [a.replace(sentinel, macro) for a in args]
 
+        # Quote arguments that would otherwise split into several shell
+        # words — the same rule the template applies to cmake and custom
+        # configure arguments (templates/default.spec.j2:169,189). RPM macro
+        # expansion happens before the shell sees the line, so %{prefix}
+        # inside single quotes still expands.
+        def _quote(arg: str) -> str:
+            if any(ch in arg for ch in (' ', ';', '<', '>')):
+                return "'" + arg + "'"
+            return arg
+        args = [_quote(a) for a in args]
+
         # Build the direct configure command
         cmd_parts = ['./configure']
         cmd_parts.extend(args)
```

## Open Questions

- Approve the builder fix above? Without it no RPM flavor can build ipopt. Alternative: expand
  only the SCLS-specific placeholders instead of routing through `check_args`; the prototype
  chose `check_args` for parity with `unix_builder.py:352` and the custom path (`rpm_builder.py:927`).
- EPL-2.0 policy entry (Christian's call, not a vote).
- Keep `--enable-mpiinit` (upstream default) or pass `--disable-mpiinit`? Kept; see Key Findings.
- Linux evidence pending: RPM build on a build host, `%check` running `make test` as root with
  `OMPI_ALLOW_RUN_AS_ROOT*` set, `ldd libipopt.so` closure, MKL-flavor `IPOPT_HAS_PARDISO_MKL`.
- Round 2 (xhigh, per protocol §9.1) should run on the combined diff once the builder fix is
  approved and applied; running it now would only re-find F1.

## Files Updated

- recipes/ipopt.yaml (new)
- files/ipopt.txt (new)
- changelogs/ipopt.md (new)
- devlog/dl20260926_ipopt_recipe.md (this file), devlog/README.md
- tmp/ai_exchange/plan_ipopt_recipe.md (ephemeral: pre-registration, Codex + Grok entries, verification, reconciliation)
