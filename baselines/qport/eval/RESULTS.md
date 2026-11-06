# qport evaluation log

## Method
For a library that the QNX team ported (github.com/qnx-ports/<name>, branch `qnx-<version>`), we
diff the upstream release tag against the QNX branch. A **fix site** is a group of changed lines in
code or build files (not tests, docs or files named after QNX) **whose change mentions QNX**. The
last condition is needed because some QNX branches start from a slightly different upstream commit.
A site counts as **flagged** if qport, run on the *upstream* code, reports something within 3 lines.
Test-install changes (`if(QNX) install(TARGETS ... tests)`) are counted apart as "packaging".

Script: `eval/holdout.py <workdir> dev|test`. Results: `eval/holdout_dev.json`, `eval/holdout_test.json`.

## v0.1 (2026-11-06)
- Rules come from the QNX 8.0 C Library Reference (1,967 functions indexed) and from the libuv and
  libevent ports (first seen).
- **Development set** (mosquitto, nghttp2, dlt-daemon, jansson, libyaml, unbound, lighttpd1.4,
  libwebsockets, libusb). It was used to add rules (timeval include, TCP keepalive names,
  endianness macros, no libpthread). Score: **8 / 31 sites**.
- **Test set**, frozen before looking at any of its diffs (cJSON, iperf3, lldpd, gflags, glog,
  brotli, check, zenoh-pico, fribidi, libxml2, rtl-sdr). Score: **8 / 51 sites (16 %)**.
  - Note: the "mentions QNX" filter was added after a first test run had shown version noise
    (cJSON's QNX branch is not based exactly on v1.7.18). No rule was changed between the two runs.

### What v0.1 misses (from the test set, so it must NOT be used to claim v0.2 test scores)
1. Project-specific platform macros (`HOST_OS_FREEBSD`, `GLOG_OS_LINUX`, `ZENOH_LINUX`,
   `OS_HAIKU`): the platform-list rule only knows compiler macros (`__linux__`, `__FreeBSD__`).
2. CMake platform lists (`if(UNIX OR MINGW)`, `CMAKE_SYSTEM MATCHES "OpenBSD"`).
3. Changes that need knowledge of the program (privilege separation in lldpd, glog symbolizer).
   A static scan cannot find these; only building and running the tests on QNX does.

Next: fix 1 and 2, then measure on a **new** frozen test set (e.g. c-ares, iperf2, libdaemon,
avahi, sscep, tftp-hpa, lua, rapidjson, tinyxml2, pistache).

## v0.2 (2026-11-06)
New rules:
- **Project platform macros**: `#if` lines are read for OS families from compiler macros and from
  project macros (`HOST_OS_FREEBSD`, `GLOG_OS_LINUX`, `ZENOH_LINUX`). Feature macros
  (`HAVE_LINUX_...`) do not count; `__unix__`/`POSIX` in the list means QNX is already covered.
- **Platform detection chains**: `#if A #elif B #elif C ... #endif` covering 3+ OS families and no
  QNX. Reported where the QNX case would go (the `#else`, or the `#endif`).
- **CMake platform lists**: `if()`/`elseif()` testing `CMAKE_SYSTEM_NAME MATCHES "FreeBSD|..."` or
  2+ OS variables (`APPLE OR WIN32`) without QNX. `UNIX OR ...` lists are only INFO.

Scores:
| Set | v0.1 | v0.2 | Note |
|---|---|---|---|
| Development (9 repos) | 8 / 31 | 9 / 31 | used to write rules |
| Test 1 (11 repos) | 8 / 51 | 14 / 51 | **no longer clean**: v0.2 was written knowing its misses |
| **Test 2 (7 repos, frozen before v0.2)** | – | **5 / 39 (13 %)** | the honest v0.2 number |

Test 2 = c-ares, avahi, sscep, lua, rapidjson, tinyxml2, pistache (`eval/holdout_test2.json`).
iperf2, libdaemon and tftp-hpa were dropped before cloning: no GitHub upstream with tags.
Extra CHECK findings vs v0.1 on dev + test 1: about +15 %.

### What v0.2 misses on test 2 (do NOT use test 2 to claim v0.3 scores)
- 15 of c-ares's 17 sites are a QNX feature (reloading the resolver config, QNX logging): new
  code, not a portability fix. No static scan can predict them.
- **Single-OS branches** that QNX joined: `#ifdef __APPLE__` → `|| __QNX__`, `#ifdef __NetBSD__`,
  `_IS_BSD` (pistache, 6 sites). The tool only reports lists of 2+ OSes, to stay quiet.
- **Negated lists**: `#if !defined(__linux__)` → `&& !defined(__QNX__)` (pistache, 3 sites).
- `__QNXNTO__` replaced by `__QNX__` (tinyxml2).
- Meson `host_machine.system()` lists (pistache), compiler flags (rapidjson `-march=native`),
  a header name clash with QNX `malloc.h` (avahi).
