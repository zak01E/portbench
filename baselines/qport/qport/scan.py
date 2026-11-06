"""Scan C/C++ sources for things that will not build or behave the same on QNX 8.0."""
import os
import re
from dataclasses import dataclass, field, asdict

from . import kb

SRC_EXT = {".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx", ".ipp", ".inl"}
SKIP_DIRS = {".git", ".svn", "build", "_build", "node_modules", ".cache", "out"}

INCLUDE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]')
PP = re.compile(r"^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)")
CALL = re.compile(r"(\.|->|::)?\s*\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
# A function definition starts at column 0 with a return type and has no ';' on the line.
DEFN = re.compile(r"^(?!return\b|if\b|else\b|while\b|for\b|switch\b|do\b|case\b)"
                  r"(?:[A-Za-z_][\w\s\*&:<>,]*[\s\*&])?([A-Za-z_]\w*)\s*\([^;]*$")
IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
STRING = re.compile(r'"((?:[^"\\\n]|\\.)*)"')
QNX_MACRO = re.compile(r"__QNX__|__QNXNTO__|\bQNX\b|__nto__")
LINUX_MACRO = re.compile(r"__linux__|__linux\b|\blinux\b|__gnu_linux__|__GLIBC__")
QNX_EXCLUDE = re.compile(r"!\s*defined\s*\(?\s*(__QNX__|__QNXNTO__)")
NOT_LINUX = re.compile(r"!\s*defined\s*\(?\s*(__linux__|__linux|linux|__gnu_linux__|__GLIBC__)|#\s*ifndef")

FEATURE_MACRO = re.compile(r"\b\w*(HAVE|USE|ENABLE)_\w+")

# Platform tags taken from path components: src/unix/freebsd.c, platform/windows/, epoll.c ...
OTHER_OS = {"darwin", "macos", "mac", "apple", "ios", "osx", "freebsd", "openbsd", "netbsd",
            "dragonfly", "bsd", "sunos", "solaris", "illumos", "aix", "os390", "zos", "cygwin",
            "mingw", "win", "win32", "win64", "windows", "wince", "haiku", "hurd", "kqueue",
            "devpoll", "evport", "iocp", "wepoll", "android", "emscripten", "wasm", "fuchsia"}
LINUX_ONLY = {"linux", "epoll", "inotify", "eventfd", "timerfd", "io_uring", "uring", "glibc"}
PATH_TOKEN = re.compile(r"[A-Za-z0-9]+")


_OS_MACRO_GROUP = {"__linux__": "LINUX", "BSD": "BSD", "__FreeBSD__": "FREEBSD", "__NetBSD__": "NETBSD",
                   "__OpenBSD__": "OPENBSD", "__APPLE__": "APPLE", "__sun": "SUN", "__DragonFly__": "DRAGONFLY",
                   "_AIX": "AIX", "__MVS__": "ZOS", "__HAIKU__": "HAIKU", "__CYGWIN__": "CYGWIN",
                   "_WIN32": "WINDOWS", "__unix__": "UNIX", "__unix": "UNIX"}


def os_groups(cond):
    """OS families named in a preprocessor condition, from compiler macros (__FreeBSD__) and
    project macros (HOST_OS_FREEBSD, GLOG_OS_LINUX). Feature macros (HAVE_LINUX_...) do not count."""
    out = set()
    for name in IDENT.findall(cond):
        if name in _OS_MACRO_GROUP:
            out.add(_OS_MACRO_GROUP[name])
            continue
        if name == "defined" or FEATURE_MACRO.fullmatch(name) or "_H" in name[-3:]:
            continue
        parts = [p.lower() for p in name.strip("_").split("_") if p]
        if len(parts) < 2 and name.strip("_").lower() not in ("linux", "unix"):
            continue  # a bare word such as "sun" or "BSD" alone is too ambiguous
        for p in parts:
            if p in kb.OS_WORDS:
                out.add(kb.OS_WORDS[p])
    return out


def platform_of(rel):
    """'other' (not compiled for QNX), 'linux' (Linux-only file) or None."""
    toks = {t.lower() for t in PATH_TOKEN.findall(rel.rsplit(".", 1)[0])}
    if toks & {"qnx", "nto"}:
        return "qnx"
    if toks & OTHER_OS:
        return "other"
    if toks & LINUX_ONLY:
        return "linux"
    return None


API_BY_NAME = {}
for rule in kb.LINUX_APIS:
    for n in rule["names"]:
        API_BY_NAME[n] = rule
SOCKET = set(kb.SOCKET_FUNCS)


@dataclass
class Finding:
    file: str
    line: int
    severity: str
    rule: str
    symbol: str
    message: str
    evidence: str = ""
    context: str = ""        # preprocessor context, e.g. "inside #ifdef __linux__"
    code: str = ""
    end_line: int = 0         # last line of a multi-line #if condition


@dataclass
class FileResult:
    path: str
    findings: list = field(default_factory=list)


def strip_comments(text):
    """Blank out comments, keep line breaks and string literals."""
    out = []
    i, n = 0, len(text)
    state = None
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if state is None:
            if c == "/" and nxt == "/":
                state = "line"; i += 2; continue
            if c == "/" and nxt == "*":
                state = "block"; out.append("  "); i += 2; continue
            if c == '"' or c == "'":
                state = c
            out.append(c)
        elif state == "line":
            if c == "\n":
                state = None; out.append(c)
            else:
                out.append(" ")
        elif state == "block":
            if c == "*" and nxt == "/":
                state = None; out.append("  "); i += 2; continue
            out.append("\n" if c == "\n" else " ")
        else:  # inside a string or char literal
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if c == state or c == "\n":
                state = None
        i += 1
    return "".join(out)


def blank_strings(line):
    return STRING.sub(lambda m: '""', line)


class PPStack:
    """Tracks #if nesting so we know whether a line is Linux-only or QNX-handled."""

    def __init__(self):
        self.stack = []   # list of [condition text, in_else]

    def feed(self, kind, cond):
        if kind in ("if", "ifdef", "ifndef"):
            self.stack.append([("#" + kind + " " + cond).strip(), False])
        elif kind in ("elif",):
            if self.stack:
                self.stack[-1] = [self.stack[-1][0] + " | #elif " + cond.strip(), False]
        elif kind == "else":
            if self.stack:
                self.stack[-1][1] = True
        elif kind == "endif":
            if self.stack:
                self.stack.pop()

    def status(self):
        """'qnx' if a QNX branch already handles this, 'linux' if Linux-only,
        'feature' if guarded by a HAVE_/USE_ feature macro, else None."""
        st = None
        for cond, in_else in self.stack:
            if QNX_MACRO.search(cond):
                return "qnx"
            if LINUX_MACRO.search(cond):
                negated = bool(NOT_LINUX.search(cond))
                linux_branch = (not in_else) != negated
                if linux_branch:
                    st = "linux"
            elif st is None and not in_else and FEATURE_MACRO.search(cond):
                st = "feature"
        return st

    def describe(self):
        return " > ".join(c + (" (else)" if e else "") for c, e in self.stack)[:160]


def defined_functions(text):
    """Names of functions defined (not only declared) in this text."""
    out = set()
    for line in strip_comments(text).split("\n"):
        m = DEFN.match(line)
        if m:
            out.add(m.group(1))
    return out


def scan_text(text, rel, project_defs=frozenset(), file_platform=None):
    res = FileResult(rel)
    if file_platform == "other":
        return res  # e.g. src/unix/freebsd.c: not compiled for QNX
    own_defs = defined_functions(text)
    if re.search(r"\bstruct\s+timeval\b", strip_comments(text)) and "sys/time.h" not in {
            m.group(1) for ln_ in text.split("\n") for m in [INCLUDE.match(ln_)] if m}:
        tl = text.split("\n")
        first = next((i for i, l in enumerate(tl, 1) if re.search(r"\bstruct\s+timeval\b", l)), 1)
        # anchor the finding where the include should go: after the last #include before first use
        anchor = max([i for i, l in enumerate(tl[:first], 1) if INCLUDE.match(l)] or [first])
        res.findings.append(Finding(
            rel, anchor, kb.CHECK, "missing-include", "sys/time.h",
            "Uses struct timeval without including <sys/time.h>. glibc provides it through other "
            "headers, QNX does not; the QNX unbound and nghttp2 ports add this include.",
            kb.TIMEVAL_EVIDENCE, "", text.split("\n")[first - 1].strip()[:160]))
    includes = {m.group(1) for ln in text.split("\n") for m in [INCLUDE.match(ln)] if m}
    code = strip_comments(text)
    pp = PPStack()
    seen = set()
    chains = []
    raw_lines = text.split("\n")
    code_lines = code.split("\n")
    for ln, line in enumerate(code_lines, 1):
        m = PP.match(line)
        if m:
            cond = m.group(2)
            # gather a multi-line condition (backslash continuations)
            k = ln
            full = cond
            while full.rstrip().endswith("\\") and k < len(code_lines):
                full = full.rstrip()[:-1] + " " + code_lines[k]
                k += 1
            for name in IDENT.findall(full):
                for names, msg, ev in kb.PORT_RULES:
                    if name in names and ("port-lesson", name, ln) not in seen:
                        seen.add(("port-lesson", name, ln))
                        res.findings.append(Finding(rel, ln, kb.CHECK, "port-lesson", name, msg, ev, "",
                                                    raw_lines[ln - 1].strip()[:160], k))
            if QNX_EXCLUDE.search(full) and ("old-qnx", ln) not in seen:
                seen.add(("old-qnx", ln))
                res.findings.append(Finding(
                    rel, ln, kb.CHECK, "old-qnx", "!defined(__QNX__)",
                    "Code is switched off for QNX. Such exclusions often date from QNX 7 (io-pkt network "
                    "stack); QNX 8 uses io-sock, so the feature may now work. The QNX libuv port "
                    "re-enabled UDP source-specific multicast this way.",
                    kb.UV + "src/unix/udp.c", "", raw_lines[ln - 1].strip()[:160], k))
            kind = m.group(1)
            groups = os_groups(full)
            if kind in ("if", "ifdef", "ifndef"):
                chains.append({"oses": set(groups), "qnx": bool(QNX_MACRO.search(full)), "n": 1,
                               "start": ln, "else": 0, "neg": kind == "ifndef" or "!" in full})
            elif kind == "elif" and chains:
                c = chains[-1]
                c["oses"] |= groups
                c["qnx"] |= bool(QNX_MACRO.search(full))
                c["n"] += 1
            elif kind == "else" and chains:
                chains[-1]["else"] = ln
            elif kind == "endif" and chains:
                c = chains.pop()
                real = c["oses"] - {"UNIX"}
                # An OS detection chain (#if A #elif B #elif C ...) without a QNX case: QNX gets
                # the #else branch, or no definition at all. Anchor where a QNX case would go.
                if (c["n"] >= 3 and len(real) >= 3 and not c["qnx"] and "UNIX" not in c["oses"]
                        and not c["neg"] and pp.status() != "qnx"):
                    at = c["else"] or ln
                    res.findings.append(Finding(
                        rel, at, kb.CHECK, "platform-chain", " / ".join(sorted(real)[:4]),
                        f"Platform detection chain (#if at line {c['start']}) covers "
                        f"{', '.join(sorted(real))} but not QNX: on QNX the "
                        + ("#else branch is used." if c["else"] else "chain defines nothing.")
                        + " Add a QNX case (the QNX ports of glog and zenoh-pico add QNX to their own platform macros).",
                        kb.PLATFORM_LIST_EVIDENCE, "", raw_lines[at - 1].strip()[:160], at))
            if kind in ("if", "elif") and not QNX_MACRO.search(full):
                oses = sorted(groups - {"UNIX"})
                if len(oses) >= 2 and "UNIX" not in groups and "!" not in full and pp.status() != "qnx":
                    key = ("platform-list", ln)
                    if key not in seen:
                        seen.add(key)
                        res.findings.append(Finding(
                            rel, ln, kb.CHECK, "platform-list", "#if " + " || ".join(oses[:3]),
                            f"Platform list ({', '.join(oses)}) without QNX: QNX falls to the other "
                            "branch. If QNX supports the feature (it often does for POSIX calls), add "
                            "defined(__QNX__), as the QNX libuv port did.",
                            kb.PLATFORM_LIST_EVIDENCE, "", raw_lines[ln - 1].strip()[:160], k))
            pp.feed(m.group(1), full)
            continue
        st = pp.status()
        if st == "qnx":
            continue
        ctx = pp.describe() if st in ("linux", "feature") else ""
        if file_platform == "linux":
            ctx = "Linux-only file" + (" > " + ctx if ctx else "")
        src = raw_lines[ln - 1].strip()[:160] if ln - 1 < len(raw_lines) else ""

        def add(sev, rule, sym, msg, ev=""):
            if sev in (kb.BLOCKER, kb.LINK):
                if file_platform == "linux":
                    sev = kb.INFO
                    msg = ("Linux-only file: the QNX build must leave it out and use another "
                           "implementation. " + msg)
                elif st == "linux":
                    sev = kb.INFO
                    msg = "Linux-only branch (skipped on QNX, so the feature may be missing): " + msg
                elif st == "feature":
                    sev = kb.CHECK
                    msg = ("Guarded by a feature macro: make sure the QNX build leaves it undefined, "
                           "or this fails. " + msg)
            key = (rule, sym, ln)
            if key in seen:
                return
            seen.add(key)
            res.findings.append(Finding(rel, ln, sev, rule, sym, msg, ev, ctx, src))

        inc = INCLUDE.match(line)
        if inc:
            h = inc.group(1)
            if h in kb.LINUX_HEADERS:
                sev, msg = kb.LINUX_HEADERS[h]
                add(getattr(kb, sev), "linux-header", h, msg)
            else:
                for pre, msg in kb.LINUX_HEADER_PREFIXES.items():
                    if h.startswith(pre):
                        add(kb.BLOCKER, "linux-header", h, msg)
                        break
            continue
        if line.lstrip().startswith("#"):
            continue  # #define etc.

        for s in STRING.findall(line):
            for prefix, msg in kb.PATH_RULES:
                if s.startswith(prefix):
                    add(kb.CHECK, "linux-path", s[:60], msg)
                    break

        bare = blank_strings(line)
        for member, name in CALL.findall(bare):
            if member:
                continue  # obj.connect(), ptr->send(), ns::clone(): not the C function
            rule = API_BY_NAME.get(name)
            if rule and rule.get("need_header") and rule["need_header"] not in includes:
                rule = None  # e.g. a project's own error() function
            if rule and name in own_defs and DEFN.match(line):
                continue  # this line is the definition itself
            if rule and name in project_defs:
                add(kb.INFO, "own-impl", name,
                    f"The project defines its own {name}(); fine on QNX unless that definition is Linux-only.")
                continue
            if rule and not kb.qnx_has(name):
                alt = ", ".join(a for a in rule["qnx_alt"] if kb.qnx_has(a))
                ev = rule.get("evidence") or (kb.qnx_doc(rule["qnx_alt"][0]) if rule["qnx_alt"] and kb.qnx_has(rule["qnx_alt"][0]) else kb.INDEX_URL)
                add(kb.BLOCKER, "linux-api", name, f"{name}() is not in the QNX 8.0 C library. {rule['advice']}", ev)
                continue
            if name in SOCKET and name not in project_defs:
                add(kb.LINK, "needs-lib", "socket", f"{name}(): {kb.SOCKET_ADVICE}", kb.SOCKET_EVIDENCE)
                continue
            e = kb.qnx_index().get(name)
            if e and e["libs"] and not set(e["libs"]) & {"c", "m"}:
                lib = e["libs"][0]
                add(kb.LINK, "needs-lib", lib, f"{name}() is in lib{lib} on QNX: link with -l {lib}.", e["doc"])
        for name in IDENT.findall(bare):
            for names, msg, ev in kb.PORT_RULES:
                if name in names:
                    add(kb.CHECK, "port-lesson", name, msg, ev)
            rule = API_BY_NAME.get(name)
            if rule and rule.get("kind") == "symbol" and not kb.qnx_has(name):
                add(kb.BLOCKER, "linux-api", name, f"{name} is glibc-only. {rule['advice']}", kb.qnx_doc(rule["qnx_alt"][0]) or "")
    return res


def iter_sources(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
        for f in fns:
            if os.path.splitext(f)[1].lower() in SRC_EXT:
                yield os.path.join(dp, f)


def scan_tree(root):
    texts = {}
    for p in iter_sources(root):
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                texts[p] = fh.read()
        except OSError:
            continue
    rel = {p: os.path.relpath(p, root).replace("\\", "/") for p in texts}
    plat = {p: platform_of(rel[p]) for p in texts}
    defs = set()
    for p, t in texts.items():
        if plat[p] not in ("other", "linux"):
            defs |= defined_functions(t)
    defs = frozenset(defs)
    return [scan_text(t, rel[p], defs, plat[p]) for p, t in texts.items()]


def to_dict(f):
    return asdict(f)
