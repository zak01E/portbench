# PortBench: 1,619 real operating-system porting fixes for testing code localization

*A benchmark built from the public QNX port branches, with a file-localization task and baselines that show where simple heuristics stop working*

## Abstract
Agent benchmarks for software engineering start from an issue text and a failing test. Porting has neither. The code works on Linux, and the agent has to find the few files that must change for another operating system. We present PortBench, built from every fork in the public `qnx-ports` GitHub organisation, where QNX engineers port open-source projects to QNX 8.0. From 450 branches we keep 150 projects, one instance each, with 1,619 fix hunks. 127 of these projects are in C/C++ and hold 1,296 hunks. Every hunk has a fix type, and every instance points to an upstream base commit, so the task can be rebuilt exactly.

We define a file-localization task scored with Recall@k against the files the engineers actually changed. On 114 C/C++ instances (median 172 candidate files, 2 gold files), random ranking finds 11% of the gold files in its top 10. Counting platform macros in each file finds 55%. A rule-based porting scanner finds 46%. The benchmark splits in two. Gold files that already mention a platform are easy: 73% reach the top 10. Half of the instances (57 of 114) also need changes in files with no platform token at all, and there keyword counting does worse than random (7% against 14%). Propagating scanner findings over the `#include` graph with personalized PageRank raises this to 17%, at a cost on the easy files. Localizing these platform-neutral files is the open problem PortBench measures, and a natural target for code graphs and small fine-tuned models.

## 1. Introduction
SWE-bench and its variants measure whether an agent can resolve a GitHub issue, checked by a failing test that passes. Porting a library to a new operating system, common in embedded and automotive work, looks different. There is no issue, no failing test until the toolchain is set up, and the code is correct on the platforms it already supports. The first and hardest step is **localization**: which of the hundreds of files depend on the platform?

Localization is also where small local models struggle. A model that fits on one accelerator cannot read a whole repository. It has to search and decide what to open. This competition provides graph tools for exactly that (`get_code_neighbors`, `search_similar_code`). PortBench gives a way to measure whether they help, on a kind of task the existing benchmarks do not cover.

QNX keeps its ports public. The `qnx-ports` organisation holds forks of 194 open-source projects, from small libraries (cJSON, libyaml) to large systems (OpenCV, protobuf, PyTorch). Each fork has one or more QNX branches. Their commits are small, real, written by engineers who know the target OS, and already separated from upstream history. We turn them into a benchmark.

**Contributions**
1. **PortBench**: 150 instances (127 C/C++, 12 Rust, 11 other), 1,619 fix hunks, each with a fix type. We also release the 443 branches in raw form, including older versions of the same project.
2. **A localization task** with an evaluation script, plus the same instances as agent tasks in JSONL (repository, base commit, problem statement, gold files and hunks).
3. **Baselines, including a code-graph baseline, and an analysis by fix type.** Fixes next to existing platform code are easy to find with keyword counts. Files with no visible platform marker are found less often than by chance; graph propagation helps but does not solve them.

## 2. Related work
- **Issue-driven repair benchmarks.** SWE-bench [1] and its Verified and multilingual variants start from an issue and check with tests.
- **Localization as a separate step.** Agentless [2] showed that localization can be separated from repair and done hierarchically. LocAgent [3] builds a code graph and lets an LLM agent search it. PortBench offers a localization target that does not depend on issue text.
- **Preprocessor variability.** Platform code tends to collect in `#ifdef` regions. Liebig et al. [4] studied preprocessor variability in 40 C product lines. Our data confirms this pattern for ports: 85.5% of the code fixes add or edit a preprocessor guard. We know of no public benchmark built from real porting commits.

## 3. Building the dataset
**Source.** We listed every repository in `github.com/qnx-ports`: 232 repositories, of which 194 are forks with a known upstream. Of these, 182 have at least one branch whose name contains `qnx` or `nto`, for 450 branches in total.

**Diff.** For each branch we called the GitHub compare API from the upstream default branch to the QNX branch. The diff therefore runs from the merge base to the branch head, so it contains only commits that upstream does not have. 443 comparisons succeeded. The other 7 failed: 5 upstreams no longer exist, and 2 branches share no history with upstream. Branches are short: the median instance is 3.5 commits ahead of its merge base. 27 of the 150 diffs hit API limits and are marked `truncated`.

**Keeping only porting changes.** A hunk is kept if at least one changed line that is not a comment mentions QNX (`qnx`, `__QNXNTO__`, `__nto`). This removes unrelated upstream commits that some branches carry. We then drop:
- hunks in tests (306), documentation and CI (25), and files whose name contains `qnx` (21);
- hunks where QNX appears only in comments (71).

New files that exist only on the QNX branch are listed separately (27 C/C++ instances have some), because they cannot be located in the upstream tree.

**One instance per project.** When a project has several QNX branches, we keep the one with the most recent merge base. We skip branches named `broken`, `do_not_use`, `wip` or `test`. This gives 150 instances with at least one fix hunk.

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
- **First sample (before the last two rules were added).** 36 hunks were real porting changes. The others (a copyright line, debug logging, test files) led us to add the comment-only filter and a test-file pattern.
- **Second sample.** 38 of 40 hunks were real porting changes; the other two were a debug `printf` tagged `//QNX` and a commented-out compiler test. In 5 of the 40 the type label was wrong: all 5 were edits to continuation lines of a multi-line `#if`. We added a rule for these, which moved 20 hunks to `guard-edit` (19 of them from `edit`). We did not re-audit after this change.

## 4. What porting fixes look like
- **Small.** A C/C++ port touches a median of 3 upstream files (mean 5.5) and 4 hunks. 36 of 127 instances change a single file.
- **Mostly preprocessor.** Of the 941 hunks in C/C++ source files, 805 (85.5%) add a QNX guard, edit an existing one, or switch code off for QNX. Porting is mostly about deciding *where* to branch. The code written inside the branch is usually short: a different header, a constant, a POSIX call instead of a Linux one.
- **Build files matter.** 23% of gold files are build files: CMake platform lists, explicit `-lpthread` links (QNX has threads in libc), and `-lsocket` (QNX keeps sockets in a separate library).
- **Recent.** 73 of 150 instances have a merge base after June 2025, which lets users pick instances newer than a model's training data.

Typical hunks: adding `|| defined(__QNX__)` next to `__APPLE__` or `__FreeBSD__`; `#ifdef __QNX__ #include <sys/time.h>` (glibc pulls it in indirectly, QNX does not); `if(QNX) target_link_libraries(... socket)`; and `#ifndef __QNX__` around a Linux-only feature such as `prctl` or `/proc` parsing.

## 5. Task and metrics
**File localization.** The input is the upstream repository at `base_commit` and the target "QNX 8.0". The candidates are C/C++ sources and build files, excluding tests, docs, CI and paths that already mention QNX. The output is a ranking of candidates. **Recall@k** is the share of gold files in the top k, averaged over instances, for k = 1, 5, 10 and 20. Gold files are the upstream files changed by the QNX branch.

**Why only localization for now.** A patch cannot be checked without the QNX SDP. The SDP is free for non-commercial use, but each user needs a QNX account and a licence. Localization, by contrast, can be scored exactly and offline. Each instance also carries the gold hunks, so patch similarity can be measured. A build check inside QNX's public build container is planned future work.

## 6. Baselines
None of these needs a GPU.
- **Random**: random order with a fixed seed.
- **OS-mentions**: counts platform tokens in each file after removing comments. Tokens include `__linux__`, `_WIN32`, `__APPLE__`, `__FreeBSD__`, `CMAKE_SYSTEM_NAME`, `host_machine.system`, and project macros such as `GLOG_OS_LINUX`. This baseline knows nothing about QNX.
- **Unix-peers**: counts only tokens of the Unix systems QNX most often joins (Apple, BSDs, Solaris, AIX, Haiku).
- **Top-build + peers**: puts top-level build files first, then ranks by Unix-peers.
- **qport**: a rule-based QNX porting scanner that we wrote. It knows the 1,967 functions of the QNX 8.0 C library reference, a list of Linux-only APIs with QNX replacements, platform lists without QNX, and Linux assumptions in build files. Files are scored by findings weighted by severity. Its rules were written while looking at 29 of these projects, so we also report results without them ("unseen").
- **qport + OS-mentions**: the sum of the two scores.
- **Include-graph baselines.** We build a file graph per instance: an edge for each `#include` that resolves to a candidate (path-suffix match) and between `foo.c` and `foo.h`. The median graph has 442 edges and 10% isolated files. *Neighbours* breaks OS-mentions ties by the tokens of adjacent files. *PPR* runs personalized PageRank (restart 0.3) seeded by token counts, or by tokens plus qport scores. *Interleave* alternates the OS-mentions and PPR(OS + qport) rankings.

We also provide `gemma_baseline.py`, a Gemma 4 baseline for Kaggle notebooks. It ranks files from the file list alone, or from the file list plus platform lines. We did not have a GPU while writing this paper, so this paper reports no Gemma results.

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

**The split.** We call a gold file *visible* if it contains a platform token and *hidden* otherwise. 96 instances have visible gold files and 57 have hidden ones; 18 have only hidden ones. Pooled over files, 270 of 524 gold files are hidden, but four projects supply 173 of them (SuiteSparse alone 87, the same `#undef` in many files), so we average per instance. Table 2 gives recall restricted to each group.

| Method | visible R@10 | hidden R@10 | hidden R@20 | all R@10 | all R@20 |
|---|---|---|---|---|---|
| Random (expected) | – | 0.135 | – | 0.107 | 0.193 |
| OS-mentions | 0.727 | 0.071 | 0.139 | 0.548 | 0.660 |
| Neighbours | 0.729 | 0.079 | 0.153 | 0.555 | 0.664 |
| PPR (tokens) | 0.650 | 0.097 | 0.189 | 0.509 | 0.634 |
| PPR (tokens + qport) | 0.594 | **0.173** | **0.363** | 0.500 | 0.658 |
| Interleave | 0.677 | 0.139 | 0.284 | 0.534 | **0.683** |

Keyword counting ranks hidden files *below* chance, because visible files fill the top of the list. The graph helps: half of the hidden gold files (135/270) have a token-bearing neighbour, against 37% of all hidden candidates, and 12% carry a qport finding against 2%. Seeding PageRank with both signals more than doubles hidden recall. But it pulls visible files down, and no ranking wins on both groups.

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

**Why the scanner does worse than counting.** qport flags many real but harmless findings, such as socket calls that only need `-lsocket` at link time. Its findings point to individual lines, not to files a person would edit. Adding it to OS-mentions improves R@20 (0.692 against 0.660) but not R@10. Turning API-level knowledge into a file ranking is not trivial, and PortBench measures it.

**How an agent would use this.** A porting agent can take the top of the token ranking first, which is cheap, and spend its remaining context on graph-ranked, platform-neutral files. Interleaving the two rankings gives the best R@20 (0.683). PortBench scores the visible and hidden groups separately, so progress on the hard group is not masked by the easy one.

## 9. Limitations
- **One reference port.** The ground truth is one engineer's port, and a different valid port might touch other files. Recall against a single reference is a lower bound.
- **Rule-based filtering.** Some noise remains: about 2 in 40 hunks in our audit were not porting changes. Some QNX-specific features also count as fixes (the c-ares resolver reload, for example).
- **One target OS.** The method needs public port branches. QNX is the only large collection we found. The scripts take any organisation name.
- **Uneven instances.** A few projects repeat one fix across many files (SuiteSparse: 87 gold files). We report per-instance averages; pooled file counts overweight these projects.
- **Possible contamination.** These branches are public, so a model may have seen them. We give `base_date` so users can keep only recent instances.
- **No executable evaluation and no LLM numbers yet.** Both are planned. The JSONL tasks are ready for an agent harness.

## 10. Availability
Scripts (collection, labelling, evaluation, baselines), the dataset, the JSONL tasks and the per-instance results are at https://github.com/zak01E/portbench under the MIT licence for the code. Hunks are short excerpts of each project under its own licence, which is listed per instance. Everything can be rebuilt from public GitHub data with the scripts provided.

**Use of AI tools.** An AI assistant (Claude) wrote most of the collection and evaluation code and helped draft this text. The author checked the audits, the numbers and the claims against the released data.

## References
[1] C. E. Jimenez et al. SWE-bench: Can Language Models Resolve Real-World GitHub Issues? ICLR 2024.
[2] C. S. Xia et al. Agentless: Demystifying LLM-based Software Engineering Agents. arXiv:2407.01489, 2024.
[3] Z. Chen et al. LocAgent: Graph-Guided LLM Agents for Code Localization. ACL 2025.
[4] J. Liebig et al. An Analysis of the Variability in Forty Preprocessor-Based Software Product Lines. ICSE 2010.
[5] QNX. qnx-ports GitHub organisation. https://github.com/qnx-ports (accessed 6 November 2026).
