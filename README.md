# OptiRSA-Bench

The standalone G1/G2/G3/X1 dataset and Inspect AI evaluator are in [G-X1-cases](G-X1-cases/README.md).

**中文说明和全部拓扑分布：[G-X1-cases/README_中文.md](G-X1-cases/README_中文.md)。**

This module contains the frozen English V3.1 pool: 563 topology source IDs and 8,619 case records. Its default evaluation queue contains 8,618 records; one G3 case with documented ambiguity is retained for review. Public-question duplicates are documented separately.

The dataset is expanded into topology → task → case folders. Public prompts, private answers, provenance and a portable Inspect AI evaluation directory are included. Model platform configuration and credentials are supplied by the evaluator.

On Windows, enable long paths for the clone because some historical program paths are long:

```shell
git -c core.longpaths=true clone https://github.com/Z-Ziang/OptiRSA-Bench.git
cd OptiRSA-Bench/G-X1-cases
```

Follow the module README to install Python 3.12 dependencies, run offline acceptance, and configure your own model endpoint. No dataset ZIP or Git LFS download is required for this GX1 module. Repository access still follows the repository's visibility and permissions.

The separate `生产程序和评测程序` directory contains historical program releases. Use the GX1 module's included V5 R1 scientific validator and Inspect entry point for this dataset. Each module's version and scope must be checked before combining results.
