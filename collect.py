"""Step 1: list qnx-ports forks, their upstream, and their QNX branches."""
import json, subprocess, sys, re, concurrent.futures as cf

def gh(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        return None
    return json.loads(r.stdout)

def gh_pages(path):
    r = subprocess.run(["gh", "api", "--paginate", path, "--jq", ".[].name"], capture_output=True, text=True, encoding="utf-8")
    return r.stdout.split() if r.returncode == 0 else []

def one(name):
    info = gh(f"repos/qnx-ports/{name}")
    if not info or not info.get("fork"):
        return None
    parent = (info.get("parent") or {}).get("full_name")
    branches = [b for b in gh_pages(f"repos/qnx-ports/{name}/branches?per_page=100") if re.search(r"qnx|nto", b, re.I)]
    return {"name": name, "upstream": parent, "license": (info.get("license") or {}).get("spdx_id"),
            "language": info.get("language"), "qnx_branches": branches}

names = [l.split("\t")[0] for l in open(sys.argv[1], encoding="utf-8") if l.split("\t")[1] == "true"]
with cf.ThreadPoolExecutor(8) as ex:
    rows = [r for r in ex.map(one, names) if r]
json.dump(rows, open("data/forks.json", "w"), indent=1)
print(len(rows), "forks;", sum(1 for r in rows if r["qnx_branches"]), "with QNX branches;",
      sum(len(r["qnx_branches"]) for r in rows), "branches")
