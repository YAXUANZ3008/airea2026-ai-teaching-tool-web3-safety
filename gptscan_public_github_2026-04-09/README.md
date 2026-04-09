# AI-Powered Web3 Safety Learning Assistant for Education and Public Awareness

This repository contains the working files, scanning pipeline, dataset artifacts, and experiment scripts for an AI+Education project focused on Web3 safety learning and public awareness.

The project itself is **not named GPTScan**.  
Instead, it uses the GPTScan pipeline as part of the backend scanning workflow for smart contract analysis.

In practical terms, this repo combines:
- an education-oriented Web3 safety project concept
- a smart contract scanning backend built on top of GPTScan-related components
- local dataset experiments for validating scan coverage and result quality

## Project Positioning

This project was built as an **AI + Education prototype** rather than a production platform.

Its core idea is:
- help non-technical users understand Web3 risks
- translate smart contract scan results into understandable safety signals
- support education, demonstration, and public-awareness use cases

The scanning layer is only one part of the project. The broader product direction is an AI-powered safety learning assistant for:
- Web3 beginners
- students
- general public users
- safety education scenarios

## What This Repo Includes

- local smart contract scanning workflows
- dataset-level batch experiments
- failed-project rerun utilities
- extracted successful sample sets
- project materials generated during prototyping and evaluation

## Architecture Overview

### Product Layer

The intended product layer is an education-oriented interface that helps users:
- upload or inspect contract-related scan results
- understand common Web3 risks
- learn core concepts in plain language
- treat AI analysis as a learning aid, not a guarantee of safety

### Analysis Layer

The analysis layer in this repo is based on GPTScan-related logic and currently supports:
- single-project scanning
- dataset batch scanning
- failed-result reruns
- metadata and result export

### Data Layer

The repository also stores local benchmark inputs and outputs used during experimentation and review.

## Current Working Scope

This repository currently reflects an **experiment and prototype workflow**, including:
- running scans over local Solidity projects
- handling framework-based projects with dependency bootstrap logic
- rerunning failed scans after environment fixes
- organizing successful outputs for later analysis and demo use

It should be described as:
- a research/prototyping workspace

It should **not** be described as:
- a fully launched public platform
- a production-ready SaaS product

## Main Entry Points

### 1. Scan One Project

```bash
python scan_one_project.py <project_dir> <output_json>
```

Optional API key:

```bash
python scan_one_project.py <project_dir> <output_json> --api-key "$OPENAI_API_KEY"
```

### 2. Batch Scan a Dataset

```bash
python batch_scan_demo.py \
  --dataset-dir "/path/to/dataset" \
  --output-dir "/path/to/results"
```

This writes:
- one result JSON per project
- one metadata JSON per project
- `summary.csv`
- `failed.csv`

### 3. Rerun Failed Projects

```bash
python rerun_failed_results.py \
  --dataset-dir "/path/to/dataset" \
  --results-dir "/path/to/existing_results"
```

To rerun every failed project:

```bash
python rerun_failed_results.py \
  --dataset-dir "/path/to/dataset" \
  --results-dir "/path/to/existing_results" \
  --all-failed
```

## Environment Requirements

- Python 3.10+
- Java 17+
- Node.js for framework-based Solidity projects
- `solc-select` with required compiler versions already installed
- OpenRouter-compatible API access via `OPENAI_API_KEY`

Example:

```bash
source .venv/bin/activate
export OPENAI_API_KEY="your_openrouter_api_key"
```

## Solidity Version Handling

The backend does not rely on one fixed compiler version.

Current behavior:
- detect project pragma expressions
- inspect locally installed `solc-select` versions
- resolve a compatible compiler
- compile and scan with that local version

Important:
- required compiler versions must already exist under `~/.solc-select/artifacts`
- mixed-major-version projects may still be skipped

## Dependency Bootstrap Behavior

For framework-style Solidity projects, the backend attempts to prepare dependencies before compile.

Current fallback handling covers cases such as:
- `npm` peer dependency conflicts
- `yarn` engine issues
- git dependency fetch failures
- missing common Solidity package dependencies

This improves practical scan coverage, but does not guarantee that every real-world project will compile successfully.

## Output Files

Each scanned project produces:

- `<project>.json`
- `<project>.json.metadata.json`

Batch workflows also produce:

- `summary.csv`
- `failed.csv`

Common fields in `summary.csv`:
- `project_name`
- `detected_pragma`
- `status`
- `result_count`
- `token_sent`
- `token_received`
- `used_time`

## Result Semantics

- `success` with `result_count > 0`: scan succeeded and produced findings
- `success` with `result_count = 0`: scan succeeded but produced no findings in this run
- `compile_failed`: compile stage failed before a usable result was produced
- `parse_failed`: preprocessing or dependency/bootstrap stage failed
- `llm_api_failed`: scan reached the LLM stage but the API call failed
- `skipped_unsupported_version`: no compatible installed compiler was available

`success` with zero findings should be interpreted as:
- “no finding produced in this run”

It should **not** be interpreted as:
- “guaranteed safe”

## Local Dataset Artifacts

This workspace includes local benchmark inputs and outputs under:

- [Dataset&Result](/Users/zhishixuebao/GPTScan/Dataset&Result)

Important extracted sample sets:
- successful projects with findings:
  - [Web3Bugs-main_success_with_output_source_only](/Users/zhishixuebao/GPTScan/Dataset&Result/Web3Bugs-main_success_with_output_source_only)
- successful projects without findings:
  - [Web3Bugs-main_success_without_output_source_only](/Users/zhishixuebao/GPTScan/Dataset&Result/Web3Bugs-main_success_without_output_source_only)

These are source-only project copies plus corresponding result files for review, demo preparation, and analysis.

## Repository Structure

- [src](/Users/zhishixuebao/GPTScan/src): scanning pipeline, dependency handling, version resolution, execution logic
- [tests](/Users/zhishixuebao/GPTScan/tests): workflow regression tests
- [scan_one_project.py](/Users/zhishixuebao/GPTScan/scan_one_project.py): single-project scan entry
- [batch_scan_demo.py](/Users/zhishixuebao/GPTScan/batch_scan_demo.py): batch scan entry
- [rerun_failed_results.py](/Users/zhishixuebao/GPTScan/rerun_failed_results.py): failed-project rerun tool

## Practical Notes

- Some benchmark projects include very large `node_modules` trees; source-only extraction is often more useful than copying the full project.
- Public benchmark repositories do not always include a complete runnable environment.
- Framework-based projects are more likely to fail during dependency bootstrap than single-file samples.
- The repository currently documents a prototype/research workflow, not a public release workflow.

## Backend Acknowledgement

The contract-scanning portion of this project is built on top of the GPTScan paper and codebase direction:

```bibtex
@inproceedings{sun2024gptscan,
    author = {Sun, Yuqiang and Wu, Daoyuan and Xue, Yue and Liu, Han and Wang, Haijun and Xu, Zhengzi and Xie, Xiaofei and Liu, Yang},
    title = {{GPTScan}: Detecting Logic Vulnerabilities in Smart Contracts by Combining GPT with Program Analysis},
    year = {2024},
    isbn = {9798400702174},
    publisher = {Association for Computing Machinery},
    address = {New York, NY, USA},
    url = {https://doi.org/10.1145/3597503.3639117},
    doi = {10.1145/3597503.3639117},
    booktitle = {Proceedings of the IEEE/ACM 46th International Conference on Software Engineering},
    articleno = {166},
    numpages = {13},
    series = {ICSE '24}
}
```
