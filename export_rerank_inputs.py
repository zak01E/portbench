"""Inputs for the Gemma re-ranking stage: for each instance, the top 30 files of the learned ranker
(project-level cross-validation, so no test project was seen in training) with a short excerpt of each
file: its #include lines and the lines that mention a platform, at most 10 lines.
Writes data/rerank_inputs.json.
"""
import json, re
from evaluate import read, strip_comments, OS_TOKENS

INC = re.compile(r"^\s*#\s*include\b")
PP = re.compile(r"^\s*#\s*(if|ifdef|ifndef|elif)\b")


def excerpt(root, f, n=10):
    text = strip_comments(read(root, f))
    lines = [l.rstrip() for l in text.split("\n")]
    keep = [l for l in lines if OS_TOKENS.search(l) or (PP.match(l) and len(l) < 120)]
    keep += [l for l in lines if INC.match(l)]
    out, seen = [], set()
    for l in keep:
        l = l.strip()[:120]
        if l and l not in seen:
            seen.add(l); out.append(l)
        if len(out) >= n:
            break
    return out


def main():
    top = json.load(open("data/learned_ranks.json"))
    srcs = json.load(open("data/sources.json"))
    insts = {i["id"]: i for i in json.load(open("data/portbench.json"))}
    feats = {json.loads(l)["id"]: json.loads(l) for l in open("data/features.jsonl")}
    out = []
    for iid, files in sorted(top.items()):
        root = srcs[iid]["dir"]
        gold = sorted({r["file"] for r in feats[iid]["rows"] if r["gold"]})
        out.append({"id": iid, "repo": insts[iid]["repo"], "shortlist": files,
                    "excerpts": {f: excerpt(root, f) for f in files}, "gold": gold,
                    "hidden": sorted({r["file"] for r in feats[iid]["rows"] if r["hidden"]}),
                    "n_files": feats[iid]["n_files"]})
    json.dump(out, open("data/rerank_inputs.json", "w"))
    print(len(out), "instances")


if __name__ == "__main__":
    main()
