"""Gemma 4 localization baseline for PortBench. Run in a Kaggle notebook with a GPU (T4 x2 or L4).

Input: llm_inputs.json (from export_llm_inputs.py), attached as a Kaggle dataset.
Two prompts per instance:
  tree   - the model sees only the list of file paths;
  rerank - the model also sees platform-specific lines of the 60 most platform-heavy files.
The model returns up to 20 paths; Recall@k is computed against the files the QNX port changed.
"""
import json, re, sys, statistics as st

MODEL = sys.argv[2] if len(sys.argv) > 2 else "/kaggle/input/gemma-4/transformers/gemma-4-e4b-it/1"
INPUT = sys.argv[1] if len(sys.argv) > 1 else "/kaggle/input/portbench/llm_inputs.json"
MAX_PATHS = 400

ASK = ("You are porting the C/C++ project {repo} from Linux to QNX 8.0 (POSIX; compiler macro "
       "__QNX__; CMake sets CMAKE_SYSTEM_NAME=QNX; networking is in libsocket). List the files that "
       "most likely need changes for this port, most likely first, at most 20, one path per line, "
       "copied exactly from the list. Output only paths.\n\n")


def prompt(inst, mode):
    paths = inst["candidates"]
    if len(paths) > MAX_PATHS:  # keep platform-heavy files and build files first
        keep = list(inst["snippets"]) + [p for p in paths if not re.search(r"\.(c|h|cc|cpp|cxx|hpp|hh|hxx|ipp|inl|inc)$", p)]
        keep += [p for p in paths if p not in keep]
        paths = keep[:MAX_PATHS]
    text = ASK.format(repo=inst["repo"]) + "Files:\n" + "\n".join(paths)
    if mode == "rerank":
        text += "\n\nPlatform-specific lines in some files:\n"
        for f, lines in inst["snippets"].items():
            text += f"## {f}\n" + "\n".join(lines) + "\n"
    return text


def parse(out, cands):
    cset, got = set(cands), []
    for line in out.split("\n"):
        p = line.strip().strip("`*-• ").split(" ")[0]
        p = re.sub(r"^\d+[.)]\s*", "", p)
        if p in cset and p not in got:
            got.append(p)
    return got


def main():
    import torch
    from transformers import AutoProcessor, AutoModelForCausalLM
    proc = AutoProcessor.from_pretrained(MODEL)
    model = AutoModelForCausalLM.from_pretrained(MODEL, torch_dtype=torch.bfloat16, device_map="auto")
    data = json.load(open(INPUT))
    res = []
    for inst in data:
        row = {"id": inst["id"], "n_gold": len(inst["gold"])}
        for mode in ("tree", "rerank"):
            msgs = [{"role": "user", "content": prompt(inst, mode)}]
            ids = proc.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt",
                                           return_dict=True).to(model.device)
            with torch.no_grad():
                gen = model.generate(**ids, max_new_tokens=600, do_sample=False)
            out = proc.decode(gen[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
            rank = parse(out, inst["candidates"])
            for k in (1, 5, 10, 20):
                row[f"{mode}@{k}"] = len(set(rank[:k]) & set(inst["gold"])) / len(inst["gold"])
            row[f"{mode}_raw"] = out[:2000]
        res.append(row)
        print(inst["id"], {k: round(v, 2) for k, v in row.items() if "@10" in k}, flush=True)
    json.dump(res, open("gemma_results.json", "w"), indent=1)
    for mode in ("tree", "rerank"):
        print(mode, "  ".join(f"R@{k}={st.mean(r[f'{mode}@{k}'] for r in res):.3f}" for k in (1, 5, 10, 20)))


if __name__ == "__main__":
    main()
