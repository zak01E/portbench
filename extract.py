"""Step 2: for every QNX branch, take the diff from its merge base with upstream to the branch
head (GitHub compare API) and keep the hunks that mention QNX."""
import json, subprocess, re, os, concurrent.futures as cf

QNX = re.compile(r"qnx|__nto|\bnto\b|QNXNTO", re.I)

def gh(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        return {"_error": (r.stderr or r.stdout)[:200]}
    return json.loads(r.stdout)

def hunks(patch):
    out, cur = [], None
    for line in (patch or "").split("\n"):
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if m:
            cur = {"old_start": int(m.group(1)), "old_len": int(m.group(2) or 1),
                   "new_start": int(m.group(3)), "new_len": int(m.group(4) or 1), "minus": [], "plus": [], "text": []}
            out.append(cur)
        elif cur is not None:
            cur["text"].append(line)
            if line.startswith("-"):
                cur["minus"].append(line[1:])
            elif line.startswith("+"):
                cur["plus"].append(line[1:])
    return out

def one(job):
    fork, branch = job
    up = fork["upstream"]
    info = gh(f"repos/{up}")
    if "_error" in info:
        return {"fork": fork["name"], "branch": branch, "error": info["_error"]}
    default = info["default_branch"]
    owner = up.split("/")[0]
    cmp = gh(f"repos/{up}/compare/{default}...qnx-ports:{fork['name']}:{branch}")
    if "_error" in cmp:
        return {"fork": fork["name"], "branch": branch, "error": cmp["_error"]}
    files = []
    for f in cmp.get("files", []):
        hs = hunks(f.get("patch"))
        keep = [h for h in hs if any(QNX.search(x) for x in h["minus"] + h["plus"])]
        files.append({"path": f["filename"], "status": f["status"], "additions": f["additions"],
                      "deletions": f["deletions"], "has_patch": "patch" in f, "qnx_hunks": keep,
                      "n_hunks": len(hs)})
    return {"fork": fork["name"], "branch": branch, "upstream": up, "upstream_default": default,
            "base_sha": cmp["merge_base_commit"]["sha"], "base_date": cmp["merge_base_commit"]["commit"]["committer"]["date"],
            "head_sha": (cmp.get("commits") or [{}])[-1].get("sha"), "ahead_by": cmp["ahead_by"],
            "behind_by": cmp["behind_by"], "n_files": len(cmp.get("files", [])),
            "license": fork["license"], "language": fork["language"],
            "commit_messages": [c["commit"]["message"][:300] for c in cmp.get("commits", [])][-60:],
            "files": files}

forks = json.load(open("data/forks.json"))
jobs = [(f, b) for f in forks for b in f["qnx_branches"] if f["upstream"]]
os.makedirs("data/raw", exist_ok=True)
done = 0
with cf.ThreadPoolExecutor(8) as ex:
    for r in ex.map(one, jobs):
        fn = f"data/raw/{r['fork']}__{re.sub(r'[^A-Za-z0-9._-]', '_', r['branch'])}.json"
        json.dump(r, open(fn, "w"), indent=0)
        done += 1
        if done % 50 == 0:
            print(done, flush=True)
print("done", done)
