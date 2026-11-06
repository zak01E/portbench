"""Compare qport findings on upstream code with the hunks QNX engineers changed in their port."""
import json, os, re, subprocess, sys
S = sys.argv[1]
total = hit_all = 0
for up, q in [("up-libuv", "qnx-libuv"), ("up-libevent", "qnx-libevent")]:
    fs = json.load(open(f"reports/{up}.json"))["findings"]
    diff = subprocess.run(["git", "diff", "--no-index", "-U0", up, q], cwd=S, capture_output=True,
                          text=True, errors="replace").stdout
    hunks, cur = [], None
    for l in diff.split("\n"):
        m = re.match(r"^--- a/(.*)", l)
        if m:
            cur = m.group(1)[len(up) + 1:]
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? ", l)
        if m and cur and not cur.startswith((".git", "test")):
            hunks.append((cur, int(m.group(1)), int(m.group(2) or 1)))
    # merge hunks of the same file that are close together into one "fix site"
    sites = []
    for f, a, n in sorted(hunks):
        if sites and sites[-1][0] == f and a - sites[-1][2] <= 25:
            sites[-1][2] = a + max(n, 1)
        else:
            sites.append([f, a, a + max(n, 1)])
    hit = scored = 0
    for f, a, b in sites:
        kind = "qnx-file" if "qnx" in f.lower() else ("packaging" if f.endswith("CMakeLists.txt") else "")
        near = [x for x in fs if x["file"] == f and x["line"] - 3 <= b and max(x.get("end_line") or 0, x["line"]) + 3 >= a]
        tag = ("FLAGGED " + str([(x["severity"], x["symbol"][:28]) for x in near][:2])) if near else "missed"
        print(f"  {up} {f}:{a}-{b} {kind or ''} -> {tag}")
        if kind:
            continue
        scored += 1
        hit += bool(near)
    print(f"{up}: {hit}/{scored} fix sites flagged (QNX-only files and packaging excluded)")
    total += scored; hit_all += hit
print(f"TOTAL {hit_all}/{total}")
