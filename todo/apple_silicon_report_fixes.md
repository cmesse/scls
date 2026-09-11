# Apple Silicon bootstrap report — fixes (2026-09-10)

Source: `tmp/scls_arm64_report.md` (colleague's M2 Pro bootstrap of the `macos` flavor at
`399ae12`). Worked on an Intel Mac; no arm64 host. Round structure: plan → Codex+Grok audit →
patch → Codex+Grok audit → executable gates → devlog. Exchange: `tmp/ai_exchange/arm64_report_fixes.md`.

## Plan
- [x] Read the report, protocol, and every cited file:line; fetch GKlib e2856c2 and PETSc 3.25.0 config sources
- [x] Write the plan entry in the exchange
- [x] Round-1 audit (Codex gpt-5.6-terra/high, Grok grok-4.6/high) and reconcile

## Patches
- [x] F2 `templates/scls-activate.sh.j2`, `templates/scls-deactivate.sh.j2` — bash+zsh portable (self-location, no `read -a`, no `${!var}`)
- [x] F3 `recipes/gklib.yaml` — `flavor_args: macos: [-DNO_X86=ON]`
- [x] F4 `python/unix_builder.py` — macOS never writes the tracked `files/<pkg>.txt`; it writes `work/files/<pkg>.txt`, `SCLS_WRITE_TRACKED_FILES=1` overrides (both auditors rejected seed-if-missing)
- [x] F5 `python/unix_builder.py`, `python/rpm_builder.py` — `%{gcc_version}` / `%{gcc_machine}` macros; `recipes/vtk.yaml` uses them, registry cflags `vtk-9.7`
- [x] F6 `recipes/openmpi.yaml` — `lib/libprrte%{libext}`
- [x] F7 `recipes/petsc.yaml` — `PETSC_ARCH=` as a configure argument per flavor (NOT the report's empty env value: PETSc rejects it), add `gcc:` to build/install maps
- [x] Docs: `README.md`, `doc/MACOS_BUILD.md` status paragraphs
- [x] Changelogs: gklib, openmpi, petsc, vtk, environment (new)

## Gates (this host)
- [x] F2: render templates, source under `bash --norc` and `zsh -f`, assert env
- [x] F5: `check_args` expands the new vtk line to the current Intel hardcode byte-for-byte
- [x] F6/F7: `--spec-only` diffs show only the intended tokens (openmpi mkl+gcc, petsc gcc+lbl; petsc mkl cannot generate on macOS: `%{libgomp}` needs a Linux gcc)
- [x] `python3 python/validate_project.py` clean; `build_order.py` resolves for macos and lbl
- [x] Round-2 audit and reconcile (Codex gpt-6-astra/xhigh, Grok grok-4.6/xhigh; F2 chpwd/cd, bare-prefix prune, `|| :`, changelog sigils, F4 override path fixed and re-gated)
- [x] Devlog `devlog/dl20260910_apple_silicon_report_fixes.md` + index

## Pending an arm64 host (cannot be closed here)
- [ ] gklib, openmpi, vtk, petsc build on Apple Silicon with these changes
- [ ] MUMPS install-name normalizer on arm64 (INC-202)
- [ ] M4/M5 `hw.cpufamily` fallback
