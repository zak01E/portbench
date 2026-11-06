# qport (working name)

Find what stops a C/C++ project from building or behaving the same on **QNX 8.0**, before
you start porting it.

```bash
python -m qport scan path/to/project --md report.md --json report.json
```

What it checks:
- **Linux and glibc APIs missing from QNX** (epoll, eventfd, timerfd, signalfd, prctl, sysinfo,
  getrandom, sendfile, ...). It checks them against the full QNX 8.0 C Library Reference
  (`qport/data/qnx80_libc_index.json`, 1,967 functions, retrieved 2026-11-06). Each finding comes
  with a QNX replacement that the tests verify really exists.
- **Extra libraries** that QNX needs: `-l socket`, `-l fsnotify` (inotify), `-l regex`, and the
  others, read from the "Library:" section of each function page.
- **Behaviour differences learned from real QNX ports**: process priority, `SA_RESTART`,
  `POLLRDHUP`, TCP keepalive option names, missing `<sys/time.h>`, platform `#if` lists that leave
  QNX out, code switched off for old QNX versions. Each finding links to the QNX port where the
  QNX team made the same change.
- **Linux-only paths** (`/proc/cpuinfo`, `/sys/...`) and **build files** that assume Linux.

It knows when code is already handled (`#ifdef __QNX__`), when it sits in a Linux-only branch, or
when it lives in a file for another OS (`freebsd.c`, `win32/`).

Evaluation: `eval/RESULTS.md`. Tests: `python -m pytest tests`.
