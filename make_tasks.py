"""Export PortBench instances as agent tasks (SWE-bench-like JSONL) for harnesses such as the
Gemma 4 competition's: repo, base commit, a problem statement, and the gold hunks."""
import json

STATEMENT = ("This repository builds and runs on Linux. Port it to QNX 8.0 (POSIX, toolchain qcc, "
             "CMAKE_SYSTEM_NAME=QNX, compiler macro __QNX__). Make the smallest changes so that the "
             "library builds and behaves correctly on QNX, keeping other platforms unchanged.")

def main():
    insts = json.load(open("data/portbench.json"))
    with open("data/portbench_tasks.jsonl", "w") as out:
        for r in insts:
            gold_files = sorted({s["file"] for s in r["sites"]})
            out.write(json.dumps({
                "instance_id": r["id"], "repo": r["repo"], "base_commit": r["base_sha"],
                "reference_port": {"fork": r["fork"], "branch": r["qnx_branch"], "head": r["head_sha"]},
                "problem_statement": STATEMENT, "family": r["family"], "license": r["license"],
                "gold_files": gold_files,
                "gold_sites": [{k: s[k] for k in ("file", "old_start", "old_len", "kind")} for s in r["sites"]],
                "new_qnx_files": r["added_qnx_files"], "base_date": r["base_date"],
            }) + "\n")
    print("wrote", len(insts), "tasks")

if __name__ == "__main__":
    main()
