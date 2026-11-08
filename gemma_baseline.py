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


def make_generator():
    """MODEL is either a local transformers checkpoint or the URL of a llama.cpp server
    (llama-server -m gemma-4-E2B-it-Q4_K_M.gguf), which lets the baseline run on a CPU."""
    if MODEL.startswith("http"):
        import urllib.request

        def gen_http(text):
            body = json.dumps({"messages": [{"role": "user", "content": text}], "temperature": 0,
                               "max_tokens": 350,
                               "chat_template_kwargs": {"enable_thinking": False}}).encode()
            req = urllib.request.Request(MODEL.rstrip("/") + "/v1/chat/completions", body,
                                         {"Content-Type": "application/json"})
            import time
            for attempt in range(60):  # survive a server restart: retry for up to an hour
                try:
                    with urllib.request.urlopen(req, timeout=3600) as r:
                        return json.load(r)["choices"][0]["message"]["content"]
                except OSError as e:
                    print("server error, retrying in 60 s:", e, flush=True)
                    time.sleep(60)
            raise RuntimeError("llama.cpp server unreachable")
        return gen_http
    import torch
    from transformers import AutoProcessor, AutoModelForCausalLM
    proc = AutoProcessor.from_pretrained(MODEL)
    # 4-bit NF4 weights (the CPU run of E2B used a 4-bit GGUF too): leaves room on two 16 GB T4s
    # for the activations of the longest prompts
    from transformers import BitsAndBytesConfig
    q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                           bnb_4bit_compute_dtype=torch.float16)
    # memory-efficient attention for the text model only (eager attention builds an n x n matrix,
    # 4.6 GB for a 12k-token prompt); the audio tower does not support sdpa
    try:
        model = AutoModelForCausalLM.from_pretrained(
            MODEL, quantization_config=q, device_map="auto",
            attn_implementation={"text_config": "sdpa", "vision_config": "eager", "audio_config": "eager"})
    except Exception as e:  # noqa: BLE001
        print("per-tower attention not accepted:", str(e)[:150], flush=True)
        model = AutoModelForCausalLM.from_pretrained(MODEL, quantization_config=q, device_map="auto")
        model.config.text_config._attn_implementation = "sdpa"
    print("text attention:", model.config.text_config._attn_implementation, flush=True)
    placed = set(getattr(model, "hf_device_map", {}).values())
    print("device map:", sorted(map(str, placed)), flush=True)
    assert not placed & {"cpu", "disk"}, "model does not fit on the GPUs"

    def gen_hf(text):
        # same settings as the llama.cpp run: greedy, thinking off, at most 350 new tokens
        msgs = [{"role": "user", "content": [{"type": "text", "text": text}]}]
        ids = proc.apply_chat_template(msgs, add_generation_prompt=True, tokenize=True,
                                       return_tensors="pt", return_dict=True,
                                       enable_thinking=False).to(model.device)
        # greedy decoding by hand: run the decoder without its head and apply lm_head to the last
        # position only. The full model computes logits for every prompt token (vocabulary 262k),
        # several GB on long prompts. Final logit soft-capping is monotonic, so argmax is unchanged.
        eos = model.generation_config.eos_token_id
        eos = set(eos if isinstance(eos, (list, tuple)) else [eos])
        out_ids = []
        with torch.no_grad():
            # chunked prefill: the attention of a 12k-token prompt in one pass needs a 4.6 GB matrix
            n, out = ids["input_ids"].shape[1], None
            for s0 in range(0, n, 2048):
                e = min(n, s0 + 2048)
                out = model.model(input_ids=ids["input_ids"][:, s0:e], attention_mask=ids["attention_mask"][:, :e],
                                  past_key_values=out.past_key_values if out is not None else None, use_cache=True)
            attn = ids["attention_mask"]
            for _ in range(350):
                h = out.last_hidden_state[:, -1:]
                nxt = model.lm_head(h.to(model.lm_head.weight.device))[:, -1].argmax(-1, keepdim=True)
                if nxt.item() in eos:
                    break
                out_ids.append(nxt.item())
                attn = torch.cat([attn, attn.new_ones((1, 1))], dim=1)
                out = model.model(input_ids=nxt.to(attn.device), attention_mask=attn,
                                  past_key_values=out.past_key_values, use_cache=True)
        del out
        return proc.decode(out_ids, skip_special_tokens=True)
    return gen_hf


def safe_generate(gen, text):
    """A prompt that fails (for example CUDA out of memory on the longest inputs) counts as an empty answer."""
    try:
        return gen(text)
    except Exception as e:  # noqa: BLE001
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001
            pass
        print("generation failed:", str(e)[:120], flush=True)
        if not FAILED:
            import traceback
            print(traceback.format_exc()[-1500:], flush=True)
        FAILED.append(str(e)[:120])
        if len(FAILED) > 10:  # stop early instead of producing meaningless numbers
            raise RuntimeError("more than 10 prompts failed") from e
        return ""


FAILED = []


def main():
    generate = make_generator()
    import os, time
    data = json.load(open(INPUT))
    out_path = os.environ.get("GEMMA_OUT", "gemma_results.json")
    res = json.load(open(out_path)) if os.path.exists(out_path) else []  # resume
    done = {r["id"] for r in res}
    for inst in data:
        if inst["id"] in done:
            continue
        row = {"id": inst["id"], "n_gold": len(inst["gold"])}
        for mode in ("tree", "rerank"):
            t0 = time.time()
            out = safe_generate(generate, prompt(inst, mode))
            rank = parse(out, inst["candidates"])
            for k in (1, 5, 10, 20):
                row[f"{mode}@{k}"] = len(set(rank[:k]) & set(inst["gold"])) / len(inst["gold"])
            row[f"{mode}_rank"] = rank
            row[f"{mode}_raw"] = out[:2000]
            row[f"{mode}_sec"] = round(time.time() - t0, 1)
        res.append(row)
        json.dump(res, open(out_path, "w"), indent=1)
        print(inst["id"], {k: v for k, v in row.items() if "@10" in k or "_sec" in k}, flush=True)
    for mode in ("tree", "rerank"):
        print(mode, "  ".join(f"R@{k}={st.mean(r[f'{mode}@{k}'] for r in res):.3f}" for k in (1, 5, 10, 20)))


if __name__ == "__main__":
    main()
