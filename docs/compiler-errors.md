# Dealing with compiler errors

It becomes quite difficult to reproduce a compiler error on someone
else's machine when they do not have the same setup. There are several
variables that can come into play.

- Compiler version (e.g., clang-16 vs. clang-17)
- Toolchain version (e.g., r25 vs r26)
- Compiler invocation commands
  - Optimization flags (e.g., `-O3 -fno-vectorize`)
  - Macro definitions (e.g., `-DNDEBUG`)
  - Include paths (e.g., `-I/my/local/usr/include/`)
  - Warning flags (e.g., `-Wall`)
  - Language specific flags (e.g., `-std=c++20`)
- Local machine environment (e.g, Windows vs. Linux)

While all of them may not be affecting the issue at hand, it is better
to minimize the differences in order to quickly get to the bottom of
it. Many of the variable above can be reduced by providing the
compiler invocation command and a preprocessed file.

## Things to share when reporting compiler error

- The preprocessed file (.i for C, .ii for C++)
- Compiler invocation command
- Details on development environment

## Generating preprocessed file

A preprocessed file is a standalone translation unit that doesn't need
any header file depenencies and macro definitions to reproduce
compilation on another machine.

Use the `--save-temps` compiler option, for example:

```sh
user@laptop: ~/Desktop/bugs$ clang++ -std=c++20 a.cpp --save-temps -c
```

This will generate `a.ii` file in the same directory from where clang
was invoked e.g., `~/Desktop/bugs/a.ii` in this case.

## Getting the compiler invocation command

A compiler invocation command is what the compiler is fed when
building a translation unit. For example `clang++ -std=c++20 a.cpp
--save-temps -c` is a compiler invocation. When working with complex
build systems(e.g., bazel, scons) it may not be straightforward to get
hold of the compiler invocation. Usually when there are compiler
errors, the build system will print the command on the console. Build
systems might also have a **verbose** mode to print all the compiler
invocations.

## Getting the details of developer environment

It is often helpful to know more about the developer environment like

- Operating system (Linux, Windows, Mac etc.)
- Processor type (X86_64, Arm64 etc.)
