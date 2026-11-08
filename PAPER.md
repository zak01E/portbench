# PortBench: 1,619 real operating-system porting fixes for testing code localization

*A benchmark built from the public QNX port branches, with a file-localization task and baselines that show where simple heuristics stop working*

## Abstract
Agent benchmarks for software engineering start from an issue text and a failing test. Porting has neither. The code works on Linux, and the agent has to find the few files that must change for another operating system. We present PortBench, built from every fork in the public `qnx-ports` GitHub organisation, where QNX engineers port open-source projects to QNX 8.0: 150 projects (127 in C/C++) with 1,619 typed fix hunks, each tied to an upstream base commit so the task can be rebuilt exactly.

We define a file-localization task scored with Recall@k against the files the engineers actually changed. On 114 C/C++ instances (median 172 candidate files, 2 gold files), random ranking finds 11% of the gold files in its top 10. Counting platform macros in each file finds 55%. A rule-based porting scanner finds 46%. The benchmark splits in two. Gold files that already mention a platform are easy: 73% reach the top 10. Half of the instances (57 of 114) also need changes in files with no platform token at all, and there keyword counting does worse than random (7% against 14%). Propagating scanner findings over the `#include` graph with personalized PageRank raises this to 17%. Gemma 4 E2B, run on a laptop CPU, reaches 24% from the file paths alone, but so does ranking files by directory depth: hidden fixes sit in shallow, central files. The larger Gemma 4 E4B does no better. Localizing platform-neutral files is the open problem PortBench measures, and a natural target for code graphs and fine-tuned small models.

## 1. Introduction
SWE-bench measures whether an agent can resolve a GitHub issue, checked by tests. Porting a library to a new operating system, common in embedded and automotive work, looks different. There is no issue, no failing test until the toolchain is set up, and the code is correct on the platforms it already supports. The first and hardest step is **localization**: which of the hundreds of files depend on the platform?

Small local models cannot read a whole repository, so they must decide what to open. This competition provides graph tools for exactly that (`get_code_neighbors`, `search_similar_code`). PortBench gives a way to measure whether they help, on a kind of task the existing benchmarks do not cover.

QNX keeps its ports public. The `qnx-ports` organisation holds forks of 194 open-source projects, from small libraries (cJSON, libyaml) to large systems (OpenCV, protobuf, PyTorch). Their QNX branches are small, real commits by engineers who know the target OS, already separated from upstream history.

**Contributions**
1. **PortBench**: 150 instances (127 C/C++, 12 Rust, 11 other), 1,619 fix hunks, each with a fix type. We also release the 443 branches in raw form, including older versions of the same project.
2. **A localization task** with an evaluation script, plus the same instances as agent tasks in JSONL (repository, base commit, problem statement, gold files and hunks).
3. **Baselines, including a code-graph baseline and Gemma 4 E2B and E4B, and an analysis by fix type.** Fixes next to existing platform code are easy to find with keyword counts. Files with no visible platform marker are found less often than by chance; graph propagation helps, and Gemma 4 (E2B, E4B) does no better than ranking by directory depth.

## 2. Related work
- **Issue-driven repair benchmarks.** SWE-bench [1] and its variants start from an issue and check with tests.
- **Localization as a separate step.** Agentless [2] showed that localization can be separated from repair and done hierarchically. LocAgent [3] builds a code graph and lets an LLM agent search it. PortBench offers a localization target that does not depend on issue text.
- **Preprocessor variability.** Liebig et al. [4] studied preprocessor variability in 40 C product lines; in our ports, 85.5% of code fixes add or edit a guard. We know of no public benchmark built from real porting commits.

## 3. Building the dataset
**Source.** We listed every repository in `github.com/qnx-ports`: 232 repositories, of which 194 are forks with a known upstream. Of these, 182 have at least one branch whose name contains `qnx` or `nto`, for 450 branches in total.

**Diff.** For each branch, the GitHub compare API from the upstream default branch gives the diff from the merge base to the branch head: only commits upstream does not have. 443 comparisons succeeded (7 failed: deleted upstreams or no shared history). The median instance is 3.5 commits ahead of its merge base; 27 diffs hit API limits and are marked `truncated`.

**Keeping only porting changes.** A hunk is kept if at least one changed line that is not a comment mentions QNX (`qnx`, `__QNXNTO__`, `__nto`). We then drop:
- hunks in tests (306), documentation and CI (25), and files whose name contains `qnx` (21);
- hunks where QNX appears only in comments (71).

New QNX-only files are listed separately (27 C/C++ instances), since they cannot be located upstream.

**One instance per project.** We keep the branch with the most recent merge base, skipping branches named `broken`, `do_not_use`, `wip` or `test`: 150 instances.

**Fix types.** Each hunk gets one label from deterministic rules on its added and removed lines.

| Type | Rule | C/C++ hunks |
|---|---|---|
| guarded-subst | adds a `#if`/`#ifdef` that mentions QNX, with replacement code | 548 |
| build | CMake, Autotools, Make, Meson, Bazel or GN file | 226 |
| guard-edit | only preprocessor conditions change (QNX added to an existing list) | 192 |
| other | another file type (scripts, `.in` templates, Lua build files) | 89 |
| include | only `#include` and guard lines added | 65 |
| disable | existing code wrapped in `#ifndef __QNX__` | 65 |
| edit | code changed without a new guard | 56 |
| packaging | build change that installs or switches off tests | 40 |
| qnx-code | more than 25 net new lines (a QNX implementation) | 15 |

Rust instances (252 hunks) are labelled `rust` and kept out of the C/C++ task.

**Audit.** We read two random samples of 40 C/C++ hunks.
- **First sample.** 36 were real porting changes; the misses (a copyright line, debug logging, test files) led to the comment-only filter and a test-file pattern.
- **Second sample.** 38 were real (the others: a debug `printf`, a commented-out test). 5 labels were wrong, all on continuation lines of a multi-line `#if`; a new rule moved 20 hunks to `guard-edit`, without a re-audit.

## 4. What porting fixes look like
- **Small.** A C/C++ port touches a median of 3 upstream files (mean 5.5) and 4 hunks. 36 of 127 instances change a single file.
- **Mostly preprocessor.** Of the 941 hunks in C/C++ source files, 805 (85.5%) add a QNX guard, edit an existing one, or switch code off for QNX. Porting is mostly about deciding *where* to branch.
- **Build files matter.** 23% of gold files are build files: CMake platform lists, `-lpthread` (QNX has threads in libc) and `-lsocket`.
- **Recent.** 73 of 150 instances have a merge base after June 2025, which lets users pick instances newer than a model's training data.

## 5. Task and metrics
**File localization.** The input is the upstream repository at `base_commit` and the target "QNX 8.0". The candidates are C/C++ sources and build files, excluding tests, docs, CI and paths that already mention QNX. The output is a ranking of candidates. **Recall@k** is the share of gold files in the top k, averaged over instances, for k = 1, 5, 10 and 20. Gold files are the upstream files changed by the QNX branch.

**Why only localization for now.** Checking a patch needs the QNX SDP, which requires a QNX account and licence. Localization can be scored exactly and offline. The gold hunks also allow patch-similarity scoring; a build check in QNX's build container is future work.

## 6. Baselines
Only the E4B run needs a GPU.
- **Random**: random order with a fixed seed. **Shallow-first**: files by directory depth, top level first.
- **OS-mentions**: counts platform tokens in each file after removing comments. Tokens include `__linux__`, `_WIN32`, `__APPLE__`, `__FreeBSD__`, `CMAKE_SYSTEM_NAME`, `host_machine.system`, and project macros such as `GLOG_OS_LINUX`. This baseline knows nothing about QNX.
- **Unix-peers**: counts only tokens of the Unix systems QNX most often joins (Apple, BSDs, Solaris, AIX, Haiku).
- **Top-build + peers**: puts top-level build files first, then ranks by Unix-peers.
- **qport**: a rule-based QNX porting scanner that we wrote. It knows the 1,967 functions of the QNX 8.0 C library reference, a list of Linux-only APIs with QNX replacements, platform lists without QNX, and Linux assumptions in build files. Files are scored by findings weighted by severity. Its rules were written while looking at 29 of these projects, so we also report results without them ("unseen").
- **qport + OS-mentions**: the sum of the two scores.
- **Include-graph baselines.** We build a file graph per instance: an edge for each `#include` that resolves to a candidate (path-suffix match) and between `foo.c` and `foo.h`. The median graph has 442 edges and 10% isolated files. *Neighbours* breaks OS-mentions ties by the tokens of adjacent files. *PPR* runs personalized PageRank (restart 0.3) seeded by token counts, or by tokens plus qport scores. *Interleave* alternates the OS-mentions and PPR(OS + qport) rankings.
- **Gemma 4 E2B** (instruction-tuned, Q4_0 GGUF, llama.cpp on an 8-core laptop CPU, greedy decoding, thinking off). The prompt names the target (QNX 8.0, `__QNX__`, libsocket) and asks for at most 20 paths. *Paths* gives the candidate list (capped at 400 paths); *Paths + lines* adds up to 6 platform lines from each of the 60 most token-heavy files. Median time is 45 s per prompt. **Gemma 4 E4B** uses the same prompts and decoding with 4-bit NF4 weights (transformers, one Kaggle T4; long prompts are read in 2,048-token chunks): 29 s per prompt, no failed prompt ([public notebook](https://www.kaggle.com/code/zakariako/portbench-gemma-4-e4b-localization-baseline)).

## 7. Results
We fetched sources for 118 of the 127 C/C++ instances. Nine repositories whose GitHub size exceeds 800 MB were skipped (LLVM, PyTorch, TensorFlow, Bazel and others). In 4 instances every gold file was outside the candidate set. That leaves **114 instances**, with a median of 172 candidate files and 2 gold files.

| Method | R@1 | R@5 | R@10 | R@20 |
|---|---|---|---|---|
| Random | 0.012 | 0.076 | 0.107 | 0.193 |
| OS-mentions | 0.159 | 0.413 | 0.548 | 0.660 |
| Unix-peers | 0.131 | 0.404 | 0.534 | 0.649 |
| Top-build + peers | **0.174** | **0.413** | **0.570** | 0.676 |
| qport | 0.090 | 0.377 | 0.463 | 0.539 |
| qport + OS-mentions | 0.137 | 0.401 | 0.545 | **0.692** |

On the 89 instances qport never saw, the ranking is the same. OS-mentions gets R@10 = 0.529, top-build + peers 0.542, qport 0.454, and qport + OS-mentions 0.543 (R@20 = 0.681).

**The split.** A gold file is *visible* if it contains a platform token, *hidden* otherwise. 96 instances have visible gold files and 57 have hidden ones; 18 have only hidden ones. Pooled over files, 270 of 524 gold files are hidden, but four projects supply 173 of them (SuiteSparse alone 87, the same `#undef` in many files), so we average per instance. Table 2 gives recall restricted to each group.

| Method | visible R@10 | hidden R@10 | hidden R@20 | all R@10 | all R@20 |
|---|---|---|---|---|---|
| Random (expected) | – | 0.135 | – | 0.107 | 0.193 |
| Shallow-first | 0.333 | **0.240** | 0.283 | 0.314 | 0.398 |
| OS-mentions | 0.727 | 0.071 | 0.139 | 0.548 | 0.660 |
| Neighbours | 0.729 | 0.079 | 0.153 | 0.555 | 0.664 |
| PPR (tokens) | 0.650 | 0.097 | 0.189 | 0.509 | 0.634 |
| PPR (tokens + qport) | 0.594 | 0.173 | **0.363** | 0.500 | 0.658 |
| Interleave | 0.677 | 0.139 | 0.284 | 0.534 | **0.683** |
| Gemma 4 E2B, paths | 0.434 | 0.238 | 0.353 | 0.397 | 0.474 |
| Gemma 4 E2B, paths + lines | 0.497 | 0.236 | 0.286 | 0.443 | 0.505 |
| Gemma 4 E4B, paths | 0.429 | 0.140 | 0.183 | 0.362 | 0.429 |
| Gemma 4 E4B, paths + lines | 0.542 | 0.117 | 0.152 | 0.429 | 0.488 |

Keyword counting ranks hidden files *below* chance, because visible files fill the top of the list. The graph helps: half of the hidden gold files (135/270) have a token-bearing neighbour, against 37% of all hidden candidates, and 12% carry a qport finding against 2%. Seeding PageRank with both signals more than doubles hidden recall. But it pulls visible files down, and no ranking wins on both groups.

**Gemma 4.** E2B finds hidden files at R@10 = 0.238 from paths alone, three times OS-mentions, but shallow-first reaches 0.240. Of the 21 hidden files E2B puts in a top 10, 10 are build files and most others are central sources of small projects (`dump1090.c`, `tinyxml2.h`): the files a person opens first. In 46 of 114 answers E2B returns paths in input order, where top-level files come first; on its other answers its hidden recall is 0.277. E4B copies less (12 of 114) but is worse: 0.362 overall and 0.140 on hidden files. Adding platform lines helps both models on visible files only. Neither model beats keyword counting overall, and reciprocal-rank fusion with OS-mentions raises R@1 (0.189 for E2B) but not R@10.

Pooled by fix type, with the OS-mentions ranking:

| Type | n files | in top 10 | no-token share |
|---|---|---|---|
| guard-edit | 72 | 62% | 3% |
| build | 89 | 55% | 18% |
| include | 50 | 34% | 36% |
| edit | 26 | 35% | 50% |
| disable | 36 | 28% | 67% |
| packaging | 37 | 27% | 73% |
| guarded-subst | 277 | 22% | 68% |

## 8. Discussion
**Visible and hidden fixes.** When the upstream code already has a list such as `#if defined(__APPLE__) || defined(__FreeBSD__)`, the fix usually goes into that list, and counting platform tokens finds the file. The hidden files are different. We sorted the 183 hidden gold files outside SuiteSparse by their added lines: replacement code inside a QNX branch (55), build or install rules (43), a clash with a macro the QNX headers define, such as `MIN`, `MAX` or `_INT32` (31), a missing type or constant such as `cpu_set_t` (22), code switched off (20), and a missing `#include` such as `<sys/time.h>` (12).

Only 12% of hidden files get any scanner finding. Most hidden fixes depend on facts about QNX's headers (which names they define, what they include) rather than on missing functions. A system has to connect a file to such a fact, and the include graph is where that link lives: a file that includes a clashing header, or uses a type its includes do not provide. Our PageRank baseline uses the graph only to spread scores. Code graphs with symbol-level edges, as provided in this competition, together with a model that knows the target headers, are the natural next step.

**Why the scanner does worse than counting.** qport flags many harmless findings (socket calls that only need `-lsocket`), and its findings point to lines, not to files.

**How an agent would use this.** An agent can take the top of the token ranking first, which is cheap, then look at shallow files and the files the graph flags. A model is only useful if it beats directory depth on hidden files, which neither Gemma model does. PortBench scores visible and hidden files separately, so progress on the hard group is not masked by the easy one.

## 9. Limitations
- **One reference port.** Another valid port might touch other files, so recall is a lower bound.
- **Rule-based filtering.** Some noise remains: about 2 in 40 hunks in our audit were not porting changes. Some QNX-specific features also count as fixes (the c-ares resolver reload, for example).
- **One target OS.** QNX is the only large public collection of port branches we found; the scripts take any organisation name.
- **Uneven instances.** A few projects repeat one fix across many files (SuiteSparse: 87 gold files). We report per-instance averages; pooled file counts overweight these projects.
- **Possible contamination.** These branches are public, so a model may have seen them. We give `base_date` so users can keep only recent instances.
- **No executable evaluation, two small models.** We ran Gemma 4 E2B and E4B (4-bit, different runtimes), without tools or fine-tuning. The JSONL tasks are ready for an agent harness.

## 10. Availability
Scripts (collection, labelling, evaluation, baselines), the dataset, the JSONL tasks and the per-instance results are at https://github.com/zak01E/portbench under the MIT licence for the code. Hunks are short excerpts of each project under its own licence, which is listed per instance. Everything can be rebuilt from public GitHub data with the scripts provided.

**Use of AI tools.** An AI assistant (Claude) wrote most of the collection and evaluation code and helped draft this text. The author checked the audits, the numbers and the claims against the released data.

## References
[1] C. E. Jimenez et al. SWE-bench: Can Language Models Resolve Real-World GitHub Issues? ICLR 2024.
[2] C. S. Xia et al. Agentless: Demystifying LLM-based Software Engineering Agents. arXiv:2407.01489, 2024.
[3] Z. Chen et al. LocAgent: Graph-Guided LLM Agents for Code Localization. ACL 2025.
[4] J. Liebig et al. An Analysis of the Variability in Forty Preprocessor-Based Software Product Lines. ICSE 2010.
[5] QNX. qnx-ports GitHub organisation. https://github.com/qnx-ports (accessed 6 November 2026).
