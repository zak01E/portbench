"""Command line: python -m qport scan <project dir> [--json out.json] [--md out.md]"""
import argparse
import json
import sys
from collections import Counter, defaultdict

from . import kb
from .buildsys import detect, scan_build_files
from .scan import scan_tree, to_dict

ORDER = [kb.BLOCKER, kb.LINK, kb.CHECK, kb.INFO]
LABEL = {kb.BLOCKER: "Will not build", kb.LINK: "Needs an extra library",
         kb.CHECK: "Builds, but check behaviour", kb.INFO: "For information"}


def run_scan(root):
    files = scan_tree(root)
    findings = [f for r in files for f in r.findings] + scan_build_files(root)
    primary, build = detect(root)
    return {"root": root, "files_scanned": len(files), "build_system": primary, "build_files": build,
            "findings": findings}


def summary(res):
    c = Counter(f.severity for f in res["findings"])
    libs = sorted({f.symbol for f in res["findings"] if f.rule == "needs-lib" and f.severity == kb.LINK})
    return c, libs


def to_markdown(res, name):
    c, libs = summary(res)
    out = [f"# QNX 8.0 porting report: {name}", "",
           f"- Files scanned: {res['files_scanned']}",
           f"- Build system: {res['build_system'] or 'unknown'}",
           f"- Will not build: **{c[kb.BLOCKER]}** · needs a library: **{c[kb.LINK]}** · "
           f"check: **{c[kb.CHECK]}** · info: {c[kb.INFO]}"]
    if libs:
        out.append(f"- Add to the link line: `{' '.join('-l' + l for l in libs)}`")
    out.append("")
    for sev in ORDER:
        fs = [f for f in res["findings"] if f.severity == sev]
        if not fs:
            continue
        out.append(f"## {LABEL[sev]} ({len(fs)})")
        groups = defaultdict(list)
        for f in fs:
            key_msg = f.message if f.rule != "needs-lib" else f.message.split(": ", 1)[-1]
            groups[(f.rule, f.symbol, key_msg)].append(f)
        for (rule, sym, msg), items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            ev = next((i.evidence for i in items if i.evidence), "")
            title = sym
            if rule == "needs-lib":
                calls = sorted({i.message.split("()")[0] for i in items})
                title = f"-l{sym}"
                msg = f"Used by: {', '.join(c + '()' for c in calls[:12])}. " + msg
            out.append(f"### `{title}` ({len(items)}x)")
            out.append(msg + (f" [source]({ev})" if ev else ""))
            for i in items[:8]:
                ctx = f" — {i.context}" if i.context else ""
                out.append(f"- `{i.file}:{i.line}`{ctx}: `{i.code}`")
            if len(items) > 8:
                out.append(f"- ... and {len(items) - 8} more")
            out.append("")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="qport", description="Find what stops a C/C++ project from building on QNX 8.0.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="scan a source tree")
    s.add_argument("root")
    s.add_argument("--json")
    s.add_argument("--md")
    s.add_argument("--name")
    a = ap.parse_args(argv)
    res = run_scan(a.root)
    name = a.name or a.root.rstrip("/\\").split("/")[-1].split("\\")[-1]
    md = to_markdown(res, name)
    if a.md:
        open(a.md, "w", encoding="utf-8").write(md)
    if a.json:
        json.dump({**res, "findings": [to_dict(f) for f in res["findings"]]}, open(a.json, "w", encoding="utf-8"), indent=1)
    c, libs = summary(res)
    print(f"{name}: {res['files_scanned']} files, build={res['build_system']}, "
          f"blockers={c[kb.BLOCKER]} link={c[kb.LINK]} check={c[kb.CHECK]} info={c[kb.INFO]} libs={libs}")
    return 1 if c[kb.BLOCKER] else 0


if __name__ == "__main__":
    sys.exit(main())
