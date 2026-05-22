# VTK on macOS

VTK 9 interactive rendering on macOS needs the native Cocoa backend in the SCLS
stack. The earlier GCC + XQuartz/X11 experiment is not viable for VTK 9
render windows on the tested machine because XQuartz only exposes OpenGL 2.1,
while VTK 9 requires OpenGL 3.2 or newer.

## Working configuration

The macOS VTK recipe is intentionally a hybrid build:

- Use Apple's `/usr/bin/gcc` and `/usr/bin/g++` frontends, which are Apple
  Clang, so VTK can compile its Cocoa Objective-C++ sources.
- Enable Cocoa and disable X11:

  ```cmake
  -DVTK_USE_COCOA=ON
  -DVTK_USE_X=OFF
  ```

- Keep the SCLS GCC `libstdc++` ABI so GCC-built BELFEM/Tycho can consume VTK
  without crossing into Apple's `libc++` ABI.
- Compile Apple Clang C++ and Objective-C++ sources against the SCLS
  `libstdc++` headers and runtime using `-stdlib=libstdc++`.
- Use `-femulated-tls`, because SCLS GCC's Darwin `libstdc++` exposes some
  thread-local runtime state through GCC's emulated TLS mechanism.

This is unusual, but it keeps the compiler/runtime fault line local to VTK
instead of rebuilding the whole scientific stack with Apple Clang.

## SMP backend

The macOS VTK build must use the Sequential SMP backend:

```cmake
-DVTK_SMP_IMPLEMENTATION_TYPE=Sequential
-DVTK_SMP_ENABLE_STDTHREAD=OFF
```

`STDThread` is not safe in this hybrid AppleClang + SCLS `libstdc++` build.
It links after adding `-femulated-tls`, but crashes at runtime in VTK's
`vtkSMPThreadPool` while completing `std::future` jobs through
`std::call_once`.

TBB might be a future way to recover VTK-side parallelism without OpenMP or
`STDThread`, but it has not been tested in this stack and would add another
dependency.

## Failed XQuartz path

We tested a GCC-built VTK with:

```cmake
-DVTK_USE_COCOA=OFF
-DVTK_USE_X=ON
```

That path required patches for VTK's X11 and GLX runtime loaders because VTK
looked for Linux `.so` names while XQuartz provides `.dylib` libraries under
`/opt/X11`. After fixing the loader names, rendering still failed because
XQuartz reported only OpenGL 2.1:

```text
OpenGL version string: 2.1
```

VTK then correctly rejected the context because it needs OpenGL 3.2 or newer.
Therefore XQuartz/X11 should not be used as the macOS VTK 9 interactive
rendering backend in SCLS.

## Whole-stack Clang alternative

Building the whole macOS stack with Apple Clang remains possible in principle,
but it would require solving OpenMP and Fortran integration separately.
`gfortran` still comes from GCC, and many SCLS packages depend on predictable
C/C++/Fortran runtime interoperability. For now, the lower-risk approach is to
keep the scientific stack on SCLS GCC/gfortran and treat VTK as the Cocoa
exception.
