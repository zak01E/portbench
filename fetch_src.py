"""Step 4: fetch each instance's upstream source at its base commit (shallow, by SHA)."""
import json, os, subprocess, sys, concurrent.futures as cf

WORK = sys.argv[1]
MAX_KB = int(sys.argv[2]) if len(sys.argv) > 2 else 150_000

def sh(*a, cwd=None):
    return subprocess.run(a, cwd=cwd, capture_output=True, text=True, errors="replace")

def size_kb(repo):
    r = sh("gh", "api", f"repos/{repo}", "--jq", ".size")
    return int(r.stdout.strip() or 0) if r.returncode == 0 else -1

def one(inst):
    d = os.path.join(WORK, inst["id"].replace("@", "__").replace("/", "_"))
    if os.path.isdir(os.path.join(d, ".git")) and sh("git", "rev-parse", "HEAD", cwd=d).stdout.strip() == inst["base_sha"]:
        return inst["id"], "ok", d
    kb = size_kb(inst["repo"])
    if kb > MAX_KB:
        return inst["id"], f"too big ({kb} KB)", None
    os.makedirs(d, exist_ok=True)
    sh("git", "init", "-q", cwd=d)
    sh("git", "remote", "add", "origin", f"https://github.com/{inst['repo']}.git", cwd=d)
    r = sh("git", "fetch", "-q", "--depth", "1", "origin", inst["base_sha"], cwd=d)
    if r.returncode:
        return inst["id"], "fetch failed: " + r.stderr.strip()[:100], None
    sh("git", "-c", "core.longpaths=true", "checkout", "-q", "FETCH_HEAD", cwd=d)
    return inst["id"], "ok", d

insts = [i for i in json.load(open("data/portbench.json")) if i["family"] == "c/c++"]
out = {}
with cf.ThreadPoolExecutor(6) as ex:
    for i, st, d in ex.map(one, insts):
        out[i] = {"status": st, "dir": d}
        if st != "ok":
            print(i, st, flush=True)
json.dump(out, open("data/sources.json", "w"), indent=1)
print("ok", sum(v["status"] == "ok" for v in out.values()), "of", len(out))
