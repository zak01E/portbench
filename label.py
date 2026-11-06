"""Step 3: turn raw compare data into benchmark instances with labelled fix sites."""
import json, glob, re, os
from collections import Counter

QNX = re.compile(r"qnx|__nto|\bnto\b|QNXNTO", re.I)
NOISE = re.compile(r"(^|/)(\.github|\.gitlab|\.circleci|\.ci|ci|docs?|doc|examples?|samples?|README|CHANGELOG|ChangeLog|NEWS|LICENSE)(/|$|\.|\b)", re.I)
TEST = re.compile(r"(^|/)(tests?|testing|unittests?|testsuite|t|spec|benchmarks?|bench|fuzz\w*)(/|$)|[_-]test\.|test_|[_-]tests?\.", re.I)
BUILD = re.compile(r"(CMakeLists\.txt|\.cmake|configure\.ac|configure\.in|\.m4|Makefile(\.am|\.in)?|GNUmakefile|\.mk|\.gmk|meson\.build|configure|meson_options\.txt|\.pro|\.pri|SConstruct|SConscript|BUILD(\.bazel)?|\.gn|\.gni|build\.sh|\.bzl|setup\.py|Kconfig)$", re.I)
SRC = re.compile(r"\.(c|h|cc|cpp|cxx|c\+\+|hpp|hh|hxx|ipp|inl|inc|tcc|s|S|asm)$")
PP = re.compile(r"^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b")
INC = re.compile(r"^\s*#\s*include\b")
COMMENT = re.compile(r"^\s*(//|/\*|\*|#(?!\s*(if|ifdef|ifndef|elif|else|endif|define|undef|include|error|pragma))|--|;)")
PACKAGING = re.compile(r"install\s*\(|INSTALL_TESTS|_tests?\b", re.I)
BAD_BRANCH = re.compile(r"broken|do_not_use|(^|[-_])(wip|tmp|test)([-_]|$)", re.I)


def is_cond(l):
    """A preprocessor line, or a continuation line of a multi-line #if condition."""
    return bool(PP.match(l)) or (bool(re.search(r"\bdefined\b|__\w+__\s*(>=|<|==)", l)) and ";" not in l)


def site_kind(path, h):
    plus = [l for l in h["plus"] if l.strip()]
    minus = [l for l in h["minus"] if l.strip()]
    if path.endswith(".rs"):
        return "rust"
    if BUILD.search(path):
        return "packaging" if PACKAGING.search("\n".join(plus)) else "build"
    if not SRC.search(path):
        return "other"
    pp_plus = [l for l in plus if is_cond(l)]
    pp_minus = [l for l in minus if is_cond(l)]
    if plus and not minus and all(PP.match(l) for l in plus) and any(QNX.search(l) for l in plus):
        return "disable"              # existing code wrapped in #ifndef __QNX__ (switched off on QNX)
    if minus and pp_minus and len(pp_minus) == len(minus) and pp_plus and len(pp_plus) == len(plus):
        return "guard-edit"           # an existing #if condition changed (usually QNX added to a list)
    if plus and all(INC.match(l) or PP.match(l) for l in plus) and any(INC.match(l) for l in plus) and not minus:
        return "include"              # headers added (often under #ifdef __QNX__)
    if len(plus) - len(minus) > 25:
        return "qnx-code"             # a sizeable QNX-specific implementation
    if any(PP.match(l) and QNX.search(l) for l in plus):
        return "guarded-subst"        # new #ifdef __QNX__ branch with replacement code
    return "edit"                     # code changed without a new guard


def instance(raw):
    sites, added, skipped = [], [], Counter()
    for f in raw["files"]:
        p = f["path"]
        if f["status"] == "added":
            if f["qnx_hunks"] or QNX.search(p):
                added.append(p)
            continue
        if f["status"] not in ("modified", "renamed"):
            continue
        for h in f["qnx_hunks"]:
            code_lines = [l for l in h["minus"] + h["plus"] if l.strip() and not COMMENT.match(l)]
            if not any(QNX.search(l) for l in code_lines):
                skipped["comment-only"] += 1; continue
            if NOISE.search(p):
                skipped["docs/ci"] += 1; continue
            if TEST.search(p):
                skipped["tests"] += 1; continue
            if QNX.search(os.path.basename(p)) or re.search(r"(^|/)(qnx|nto)[^/]*/", p, re.I):
                skipped["qnx-named-file"] += 1; continue
            sites.append({"file": p, "old_start": h["old_start"], "old_len": h["old_len"],
                          "kind": site_kind(p, h),
                          "minus": h["minus"][:80], "plus": h["plus"][:80]})
    return {"id": f"{raw['fork']}@{raw['branch']}", "repo": raw["upstream"], "fork": f"qnx-ports/{raw['fork']}",
            "qnx_branch": raw["branch"], "base_sha": raw["base_sha"], "base_date": raw["base_date"],
            "head_sha": raw["head_sha"], "license": raw["license"], "language": raw["language"],
            "behind_by": raw["behind_by"], "ahead_by": raw["ahead_by"], "compare_files": raw["n_files"],
            "truncated": raw["n_files"] >= 300 or any(not f["has_patch"] and f["status"] == "modified" for f in raw["files"]),
            "sites": sites, "added_qnx_files": added, "skipped": dict(skipped)}


def main():
    rows, errors = [], []
    for fn in sorted(glob.glob("data/raw/*.json")):
        raw = json.load(open(fn))
        if "error" in raw:
            errors.append((raw["fork"], raw["branch"], raw["error"][:120])); continue
        rows.append(instance(raw))
    # one instance per repository: the QNX branch with the most recent base (others kept as extra)
    best = {}
    for r in rows:
        if BAD_BRANCH.search(r["qnx_branch"]):
            continue
        if r["sites"] and (r["fork"] not in best or r["base_date"] > best[r["fork"]]["base_date"]):
            best[r["fork"]] = r
    main_set = sorted(best.values(), key=lambda r: r["id"].lower())
    for r in main_set:
        ex = Counter(os.path.splitext(x["file"])[1].lower() for x in r["sites"])
        rs, cc = ex[".rs"], sum(v for k, v in ex.items() if SRC.search("a" + k) or k in ("", ".txt", ".cmake", ".am", ".ac", ".mk"))
        r["family"] = "rust" if rs > cc else ("c/c++" if cc else "other")
    json.dump(main_set, open("data/portbench.json", "w"), indent=1)
    json.dump(rows, open("data/all_branches.json", "w"))
    json.dump(errors, open("data/errors.json", "w"), indent=1)
    k = Counter(s["kind"] for r in main_set for s in r["sites"])
    print(f"branches ok {len(rows)}, errors {len(errors)}; instances (1 per repo, >=1 site) {len(main_set)}; "
          f"sites {sum(len(r['sites']) for r in main_set)}; kinds {dict(k)}; "
          f"families {dict(Counter(r['family'] for r in main_set))}")


if __name__ == "__main__":
    main()
