# AI-Powered Web3 Safety Learning Assistant for Education and Public Awareness

这个仓库保存的是一个 **AI + Education 项目原型** 的工作文件、扫描流程、数据集结果和实验脚本。

这个项目本身**不叫 GPTScan**。  
更准确地说，项目后端的智能合约扫描部分使用了 GPTScan 相关能力和流程，但整体项目名称与定位是：

**AI-Powered Web3 Safety Learning Assistant for Education and Public Awareness**

从实际角度看，这个仓库包含三层内容：
- 一个面向教育和公众科普的 Web3 安全学习助手项目
- 一个以 GPTScan 为基础的智能合约扫描后端流程
- 一套本地数据集实验、失败重跑和样本整理工作流

## 项目定位

这是一个 **AI + Edu 原型项目**，不是正式上线平台。

项目的核心目标是：
- 帮助非技术用户理解 Web3 风险
- 把智能合约扫描结果转成可理解的安全提示
- 用于教育、演示、公众科普和原型验证场景

因此，扫描能力只是项目的一部分。  
更大的产品方向是一个服务于以下人群的 AI 安全学习助手：
- Web3 初学者
- 学生
- 普通公众用户
- 安全教育和科普场景

## 这个仓库当前包含什么

- 本地智能合约扫描工作流
- 数据集批量扫描脚本
- 失败项目重跑工具
- 成功样本提取目录
- 原型和实验过程中整理出的结果资产

## 整体结构说明

### 1. 产品层

产品层的目标是一个面向教育和公众认知的界面，帮助用户：
- 上传或查看合约检测结果
- 理解常见 Web3 风险
- 用更容易理解的语言学习核心概念
- 把 AI 分析当作学习辅助，而不是绝对安全保证

### 2. 分析层

当前仓库中的分析层基于 GPTScan 相关逻辑，支持：
- 单项目扫描
- 数据集批量扫描
- 失败项目重跑
- metadata 和结果导出

### 3. 数据层

仓库中也保存了本地基准输入和输出，用于实验、验证和结果整理。

## 当前工作范围

这个仓库当前反映的是一个 **实验 / 原型工作流**，主要包括：
- 对本地 Solidity 项目运行扫描
- 对工程化项目进行依赖准备
- 在修复环境问题后重跑失败项目
- 将成功结果整理成可复盘、可分析、可演示的样本目录

因此，这个仓库更适合被描述为：
- 一个研究和原型工作区

而不适合被描述为：
- 一个完整上线的平台
- 一个成熟的 SaaS 产品

## 主要可用入口

### 1. 扫描单个项目

```bash
python scan_one_project.py <project_dir> <output_json>
```

也可以显式传入 API Key：

```bash
python scan_one_project.py <project_dir> <output_json> --api-key "$OPENAI_API_KEY"
```

### 2. 批量扫描数据集

```bash
python batch_scan_demo.py \
  --dataset-dir "/path/to/dataset" \
  --output-dir "/path/to/results"
```

该流程会输出：
- 每个项目一个结果 JSON
- 每个项目一个 metadata JSON
- `summary.csv`
- `failed.csv`

### 3. 重跑失败项目

```bash
python rerun_failed_results.py \
  --dataset-dir "/path/to/dataset" \
  --results-dir "/path/to/existing_results"
```

如果要把所有失败项都重跑一遍：

```bash
python rerun_failed_results.py \
  --dataset-dir "/path/to/dataset" \
  --results-dir "/path/to/existing_results" \
  --all-failed
```

## 环境要求

- Python 3.10+
- Java 17+
- Node.js，用于 Hardhat / Truffle / Foundry 等工程项目
- 已安装好所需版本的 `solc-select`
- 通过 `OPENAI_API_KEY` 提供 OpenRouter 兼容 API Key

示例：

```bash
source .venv/bin/activate
export OPENAI_API_KEY="your_openrouter_api_key"
```

## Solidity 版本处理逻辑

当前后端不依赖单一固定 `solc` 版本。

当前行为是：
- 读取项目 pragma 表达式
- 检查本地 `solc-select` 已安装版本
- 解析兼容版本
- 扫描时使用对应本地编译器

注意：
- 所需编译器版本必须已经存在于 `~/.solc-select/artifacts`
- 混合大版本项目仍然可能被跳过

## 依赖准备逻辑

对于工程化 Solidity 项目，后端会在编译前尽量自动准备依赖。

当前流程已经覆盖了一些常见 fallback，例如：
- `npm` peer dependency 冲突
- `yarn` engine 检查问题
- git 依赖拉取失败
- 常见 Solidity 包缺失

这可以提升扫描覆盖率，但不代表所有真实项目都一定能编译成功。

## 输出文件

每个项目会生成：

- `<project>.json`
- `<project>.json.metadata.json`

批量工作流还会生成：

- `summary.csv`
- `failed.csv`

`summary.csv` 常见字段包括：
- `project_name`
- `detected_pragma`
- `status`
- `result_count`
- `token_sent`
- `token_received`
- `used_time`

## 结果状态含义

- `success` 且 `result_count > 0`：扫描成功，并且产出了 findings
- `success` 且 `result_count = 0`：扫描成功，但本次没有产出 findings
- `compile_failed`：编译阶段失败，未能形成可用结果
- `parse_failed`：预处理或依赖准备阶段失败
- `llm_api_failed`：已经进入 LLM 阶段，但 API 调用失败
- `skipped_unsupported_version`：本地没有兼容的已安装编译器版本

其中，`success` 但没有 findings，只能理解为：
- “本次未检出结果”

不能理解为：
- “绝对安全”

## 当前工作区中的本地数据资产

当前工作区已经包含本地数据集输入与输出，位于：

- [Dataset&Result](/Users/zhishixuebao/GPTScan/Dataset&Result)

当前比较重要的样本提取目录包括：
- 成功且有输出：
  - [Web3Bugs-main_success_with_output_source_only](/Users/zhishixuebao/GPTScan/Dataset&Result/Web3Bugs-main_success_with_output_source_only)
- 成功但无输出：
  - [Web3Bugs-main_success_without_output_source_only](/Users/zhishixuebao/GPTScan/Dataset&Result/Web3Bugs-main_success_without_output_source_only)

这些目录保存的是源码版项目拷贝以及对应结果文件，适合后续复盘、统计、演示和分析。

## 仓库结构

- [src](/Users/zhishixuebao/GPTScan/src)：扫描流程、依赖处理、版本解析、执行逻辑
- [tests](/Users/zhishixuebao/GPTScan/tests)：当前工作流回归测试
- [scan_one_project.py](/Users/zhishixuebao/GPTScan/scan_one_project.py)：单项目扫描入口
- [batch_scan_demo.py](/Users/zhishixuebao/GPTScan/batch_scan_demo.py)：批量扫描入口
- [rerun_failed_results.py](/Users/zhishixuebao/GPTScan/rerun_failed_results.py)：失败项目重跑工具

## 使用上的实际说明

- 某些基准项目自带很大的 `node_modules`，因此实际分析时通常更适合提取源码版目录，而不是整仓复制。
- 公开数据集未必包含完整可执行环境。
- 工程化项目通常比单文件样本更容易在依赖准备阶段失败。
- 这个仓库当前记录的是原型与实验流程，不是面向终端用户的正式发布流程。

## 后端来源说明

本项目中的智能合约扫描部分，建立在 GPTScan 论文和代码方向之上：

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
