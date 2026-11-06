"""Export compact inputs for an LLM localization baseline (to run where a GPU is available, e.g. a
Kaggle notebook with Gemma 4). For each instance: the candidate file paths, and for the 60 files
with the most platform tokens, up to 6 lines that mention a platform."""
import json, re
from evaluate import candidates, read, OS_TOKENS, strip_comments

def main():
    insts = {i["id"]: i for i in json.load(open("data/portbench.json"))}
    srcs = json.load(open("data/sources.json"))
    out = []
    for iid, s in sorted(srcs.items()):
        if s["status"] != "ok":
            continue
        root = s["dir"]
        cands = candidates(root)
        gold = sorted({x["file"] for x in insts[iid]["sites"]} & set(cands))
        if not gold:
            continue
        texts = {f: strip_comments(read(root, f)) for f in cands}
        score = {f: len(OS_TOKENS.findall(texts[f])) for f in cands}
        top = sorted(cands, key=lambda f: -score[f])[:60]
        snippets = {}
        for f in top:
            if score[f] == 0:
                break
            lines = [l.strip()[:140] for l in texts[f].split("\n") if OS_TOKENS.search(l)]
            snippets[f] = lines[:6]
        out.append({"id": iid, "repo": insts[iid]["repo"], "candidates": cands, "snippets": snippets, "gold": gold})
    json.dump(out, open("data/llm_inputs.json", "w"))
    print(len(out), "instances")

if __name__ == "__main__":
    main()
