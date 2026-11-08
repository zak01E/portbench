"""Two-stage localization: the learned ranker proposes 30 files, Gemma 4 re-ranks them.

Input: data/rerank_inputs.json (export_rerank_inputs.py). For each instance the model sees the target,
the 30 shortlisted paths in the ranker's order, and a short excerpt of each file (#include lines and
platform-specific lines). It returns the files that need changes, most likely first.
Usage: python gemma_rerank.py rerank_inputs.json <model dir or llama.cpp URL>
Same decoding as gemma_baseline.py (greedy, thinking off, at most 350 new tokens).
"""
import json, os, sys, time

from gemma_baseline import make_generator, safe_generate, parse

ASK = ("You are porting the C/C++ project {repo} from Linux to QNX 8.0 (POSIX; compiler macro __QNX__; "
       "CMake sets CMAKE_SYSTEM_NAME=QNX; networking is in libsocket; no Linux-only APIs such as epoll, "
       "inotify, prctl or /proc). A ranking tool shortlisted the files below, best first, with their "
       "#include lines and platform-specific lines. List the files that most likely need changes for this "
       "port, most likely first, one path per line, copied exactly. Output only paths.\n\n")


def prompt(inst):
    text = ASK.format(repo=inst["repo"])
    for i, f in enumerate(inst["shortlist"], 1):
        text += f"## {i}. {f}\n" + "\n".join(inst["excerpts"][f]) + "\n"
    return text


def main():
    generate = make_generator()
    data = json.load(open(sys.argv[1]))
    out_path = os.environ.get("GEMMA_OUT", "gemma_rerank_results.json")
    res = json.load(open(out_path)) if os.path.exists(out_path) else []
    done = {r["id"] for r in res}
    for inst in data:
        if inst["id"] in done:
            continue
        t0 = time.time()
        out = safe_generate(generate, prompt(inst))
        rank = parse(out, inst["shortlist"], numbered=inst["shortlist"])
        res.append({"id": inst["id"], "rank": rank, "raw": out[:2000], "sec": round(time.time() - t0, 1)})
        json.dump(res, open(out_path, "w"), indent=1)
        print(inst["id"], len(rank), res[-1]["sec"], flush=True)


if __name__ == "__main__":
    main()
