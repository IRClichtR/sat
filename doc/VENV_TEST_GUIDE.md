# SAT `--venv`: guide for test users

2026-10-30 · Floriane TUERNAL SABOTINOV

## What it is and what you need

`--venv` lets SAT build and run a **native** SALOME application against a Python virtual environment. Missing Python prerequisites (numpy, scipy, Sphinx…) are installed with pip, without root, instead of through `apt`/`dnf`. Without `--venv`, SAT behaves exactly as before.

You need:

- **Linux.** It was tested on Ubuntu 24.04. Windows and non-native apps already build their own isolated Python, so `--venv` refuses them.
- **An application that declares `Python : 'native'`**, e.g. `MEDCOUPLING-9.15.0-native` or `SALOME-master-native`.
- **The branch:** `git fetch && git checkout feat/venv_compilation` in your SAT clone (`github.com:IRClichtR/sat`).
- **`python3-venv`** (Debian/Ubuntu) or its equivalent, so that `python3 -m venv` works. Root is needed only if you choose to install system packages.

## Quick start

The whole workflow is six commands. `APP` is your application; run them from your SAT directory.

1. **Create the venv** (once, no root). By default it goes in `<workdir>/venv`:
   ```bash
   ./sat init --venv
   ```
2. **Check the prerequisites.** Native products are split into a system group (apt/dnf) and a venv group (pip):
   ```bash
   ./sat config APP --check_system --venv
   ```
3. **Install what is missing in the venv** (pip, no root):
   ```bash
   ./sat config APP --check_system --venv --install_venv
   ```
4. **Optional: install missing system packages** (sudo, asks `[y/N]` first):
   ```bash
   ./sat config APP --check_system --venv --install_system
   ```
5. **Fetch and build.** `--venv` combines with every usual option (`-p`, `--with_children`, `--clean_all`…):
   ```bash
   ./sat prepare APP
   ./sat compile APP --venv
   ```
6. **Generate the environment or the launcher, then run.** Activation is not needed: the generated files point at the venv.
   ```bash
   ./sat environ APP --venv          # then: source <target>/env_launch.sh
   ./sat launcher APP --venv         # then: <workdir>/salome  (apps with KERNEL only)
   ```

The one rule to remember: **venv mode is on only when `--venv` is on the command line.** Leave it out and the command behaves as before, even if a venv is configured.

## Command reference

| Command | What it does |
| --- | --- |
| `sat init --venv` | Creates (or reuses) `<workdir>/venv` and records it in `LOCAL.venv` (`data/local.pyconf`). |
| `sat init --venv <path>` | Same, at `<path>`. Fails if `<path>` exists and is not a venv; nothing is written then. |
| `sat init --venv forget` | Forgets `LOCAL.venv`. The venv stays on disk; delete the folder yourself if you want. |
| `sat config APP --check_system --venv` | Shows the system group and the venv group, each with OK/KO. |
| `… --install_venv` | pip-installs the KO venv products into the venv. Requires `--venv` and `--check_system`. |
| `… --install_system` | `sudo apt-get/dnf install -y` of the KO system packages, after a `[y/N]` prompt. Requires `--check_system`; works with or without `--venv`. Refused in batch mode (`-b`). |
| `--venv` on `compile`, `configure`, `make`, `makeinstall`, `script`, `environ`, `launcher`, `application`, `test` | Builds the environment against the venv: `VIRTUAL_ENV`, `PATH`, `PYTHONBIN`, `Python3_EXECUTABLE`. |

`package`, `run` and `shell` have no `--venv`. A launcher generated with `--venv` already starts with the venv interpreter (`#! <venv>/bin/python3`), so `sat run` uses the venv.

**Creating the venv** uses `--system-site-packages`: packages from apt stay visible, and anything pip-installed in the venv takes precedence. It also writes a `<venv>/bin/sat` wrapper that runs SAT with the venv's Python. Using the wrapper does not turn venv mode on; only `--venv` does.

**Pinning versions.** By default `--install_venv` takes the latest version from PyPI. To pin, add a `venv` section to the application:

```
APPLICATION :
{
    ...
    venv : { numpy : '1.26.4' }
}
```

Or for one call, without editing anything (quote the keys): `-o "APPLICATION.venv={'numpy':'1.26.4'}"`. A pin on a product outside the venv group is ignored with a warning. Quote versions: `1.10` unquoted becomes `1.1`.

## Reading the check output

With `--venv`, the check prints the system group first, then the venv group. A venv group line looks like `- numpy : OK (system 1.26.4)`.

| Line | Meaning | What to do |
| --- | --- | --- |
| `OK (venv 2.1.0)` | Installed in the venv. | Nothing. |
| `OK (system 1.26.4)` | Not in the venv, but visible from the system (apt or `~/.local`). It is used as is. | Nothing, unless you want a different version: pin it. |
| `KO (not installed)` | Found nowhere. | `--install_venv` |
| `KO (system 24.0, pinned 24.2)` | Found, but not the pinned version. | `--install_venv` installs the pin into the venv. |
| System group `KO` | apt/dnf package missing. | `--install_system`, or install it yourself. |

A missing system package is listed again at the end as a missing run-time or compile-time dependency, as before. On MEDCOUPLING-9.15.0-native (Ubuntu 24.04), the check found 26 venv products already OK from apt; `--install_venv` installed the 2 missing ones.

## Going back, and switching a product

To stop using the venv, leave `--venv` out of your commands. To forget it entirely, run `./sat init --venv forget`, then delete the folder if you want. Products built with `--venv` should be rebuilt without it (`--clean_all`).

**Switching a product from compiled to pip** is a configuration change only. Declare it `'native'` in the application, permanently or for one call:

```bash
./sat config APP --check_system --venv --install_venv -o "APPLICATION.products.packaging='native'"
./sat compile APP --venv -p packaging --with_children --clean_all -o "APPLICATION.products.packaging='native'"
```

The product must have `pip:"yes"` in its `default` section. To switch back, drop the `-o` (or restore the old declaration) and rebuild with `--with_children --clean_all`. The compiled build then wins over the copy left in the venv.

## Known limitations (already tracked)

No need to report these; do tell us if they block you.

- **CMake still finds `/usr/bin/python3`.** SALOME's CMake macros locate Python through `PYTHON_ROOT_DIR`, which stays `/usr`. It has no effect while the venv uses the system Python, but a package installed *only* in the venv is not seen at build time.
- **Versioned pip products end as `KO NO INSTALL DIR`** when compiled with `--venv`. pip does install them into the venv; SAT then looks for them in `INSTALL/Python`. Products declared `'native'` are not affected.
- **No `sat launcher` check on apps without KERNEL** (e.g. MEDCOUPLING). The launcher fails there with or without `--venv`.
- **No check that the venv's Python matches the Python running SAT.** Create the venv with the same `python3` you build with.
- **`sat config --venv` without `--check_system` is silently ignored.**
- **SAT errors print as `<bound method …>`.** The message text inside is correct. This bug predates the feature.

## What to test and how to report

Tick what you tried; each line says what you should see.

- [ ] **Nothing changes without `--venv`.** `./sat environ APP --target /tmp/env_a` gives the same files as on `master`.
- [ ] **Only 4 lines differ with `--venv`.** `./sat environ APP --venv --target /tmp/env_b`, then `diff /tmp/env_a/env_launch.sh /tmp/env_b/env_launch.sh` shows `VIRTUAL_ENV`, `PATH`, `PYTHONBIN`, `Python3_EXECUTABLE` only.
- [ ] **Check and install** on your app: no KO left in the venv group after `--install_venv`.
- [ ] **Full build:** `./sat compile APP --venv` ends with `Compilation: OK`.
- [ ] **Runtime from the venv, not activated:** `source /tmp/env_b/env_launch.sh && python3 -c "import sys; print(sys.prefix)"` prints the venv path.
- [ ] **Launcher** (apps with KERNEL): `head -1 <workdir>/salome` shows `#! <venv>/bin/python3`, and SALOME starts.
- [ ] **Forget:** after `./sat init --venv forget`, `--venv` fails with `no venv configured: run 'sat init --venv [<path>]'`.
- [ ] **Errors are clear:** `--install_venv` without `--venv`, or `--install_*` without `--check_system`, each names the fix.

To report a problem, open an issue on `github.com/IRClichtR/sat` (branch `feat/venv_compilation`) with:

- the application and your distribution (`cat /etc/os-release`)
- the exact command and its full output (add `-v 5` for more detail)
- the venv path and `<venv>/bin/python --version`
- the matching log from `<workdir>/LOGS` if a build failed
