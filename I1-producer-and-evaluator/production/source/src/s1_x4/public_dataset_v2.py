from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from src.s1_x4.generation_spec import (
    PUBLIC_GENERATION_SPEC_SCHEMA_VERSION,
    episode_scientific_fingerprint,
    validate_public_generation_spec,
    validate_generation_spec,
)
from src.s1_x4.renderer import render_s1_step, render_x4_step
from src.s1_x4.state_machine import DynamicEpisodeState


TASKS = ("S1", "X4")
PUBLIC_CASE_KEYS = frozenset(
    {
        "schema_version",
        "case_id",
        "task_type",
        "topology_id",
        "condition_id",
        "episode_length",
        "pairing_id",
        "generation_spec_ref",
        "episode_ref",
        "experiment_summary",
        "first_step_views",
        "reference_summary",
        "reference_ref",
    }
)
PUBLIC_RUN_CONFIG_KEYS = frozenset(
    {"schema_version", "task_type", "topology_id", "condition_id", "generation_spec_ref"}
)
EXPECTED_PROMPT_SHA256 = {
    "S1/llm": "e0cbb0a844eef28d45c4c1d85c8bebdac1b8b6b7a196263b9f5f702c54cfa797",
    "X4/llm": "8dbb48faa3a99f185fb9b58f2dba3d0e217459a00752ca52fc67d5ab47847afe",
}

_PUBLIC_README = """# S1/X4 动态 RSA 代表性数据集

本数据集用于智能化光网络 Benchmark 7.7 的 S1/X4 动态 RSA 任务示例。

- 9 张拓扑 × 3 个条件 = 27 条 underlying Episode
- 每条 Episode 为 H=512
- 27 个 S1 Case、27 个 X4 Case，共 54 个 task Case

## 目录怎么看

- `benchmark_case/generation_specs/`：记录一条实验如何生成，包括资源、请求、动态条件和 seed。
- `benchmark_case/S1|X4/episodes/`：实际冻结的完整 H=512 Episode。
- `benchmark_case/S1|X4/cases/`：便于阅读的 Case 概览、第一个 Step 示例和 Reference 摘要。
- `evaluation_case/`：LLM 和 Algorithm 的评测入口及当前 Step 示例。
- `reference/`：冻结 Reference 策略结果，用于比较，不是唯一答案。

Algorithm 和 LLM 都采用在线逐 Step 方式。后续网络状态取决于前一步决策，因此不会预先生成 512 份固定 Step 输入。正式评测时，evaluator 逐步提供当前公共状态，未来请求保持隐藏。
"""

_BENCHMARK_CASE_README = """# benchmark_case

这里保存两类公开内容：

- `generation_specs/`：说明实验条件和可复现参数；
- `S1/`、`X4/`：每个任务的 `cases/` 概览和 `episodes/` 完整动态 Episode。

`cases/` 适合先读，`episodes/` 用于查看完整请求序列和网络状态基础数据。正式 Algorithm 运行由 `evaluation_case/algorithm/` 启动。
"""

_GENERATION_SPECS_README = """# generation_specs

每个文件描述一个 `topology_id × condition_id` 实验如何生成。

| 字段 | 含义 |
| --- | --- |
| `generation_spec_id` | 生成规格标识 |
| `topology_id` | 使用的拓扑 |
| `condition_id` | 冻结条件 |
| `resource_config` | `episode_length`、`slot_count`、`guard_band_slots` |
| `initial_state_generation` | 初始负载、状态策略、候选路径 K 和状态到达率 |
| `request_generation` | OD 分布、payload/required 槽位值及概率 |
| `dynamic_generation` | 动态到达率模式、倍数、到达率和保持时间率 |
| `seed_block` | `state_seed`、`request_seed`、`dynamic_seed`、`confirmation_seed` |

`MATCH_STATE`：动态测试阶段使用与生成初始网络状态时相同的请求到达率，即 `lambda_dynamic = lambda_state`。

`MULTIPLIER_OF_STATE`：动态阶段到达率为 `lambda_dynamic = arrival_rate_multiplier × lambda_state`。例如 `C_HIGH_X1P2` 的 `arrival_rate_multiplier = 1.2`。
"""

_ALGORITHM_API_README = """# Algorithm 动态接口

Algorithm 从 `evaluation_case/S1|X4/algorithm/run_configs/` 中的 run config 启动。run config 只说明启动哪个实验，不是算法直接求解的完整数据。

真实流程为：

`run_config → official evaluator/environment → 读取 generation spec → 加载对应冻结 Episode → 初始化 DynamicEpisodeState → 编译 static_context → 编译当前 Step observation → Algorithm callback → validation → commit → 下一 Step → H=512 结束`

算法本体只处理 `static_context + current observation`。它不解析完整 Episode、LLM prompt、future requests、generation seeds、difficulty context 或 Reference 输出。

- S1 observation：当前请求、当前频谱、K=3 当前候选路径和全部可行动作；
- X4 observation：当前请求、当前频谱和拓扑，不包含 candidate paths、candidate actions、`path_rank` 或其他 oracle。

由于后续网络状态取决于 DUT 前序动作，S1/X4 不预先生成 512 个固定 Step NPZ。
"""

_ALGORITHM_API_INIT = """from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .compiler import compile_observation, compile_spectrum, compile_static_context


def load_run_config(path: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding=\"utf-8\")) if isinstance(path, (str, Path)) else dict(path)
    required = {\"schema_version\", \"task_type\", \"topology_id\", \"condition_id\", \"generation_spec_ref\"}
    missing = sorted(required - set(value))
    if missing:
        raise ValueError(f\"run config missing fields: {missing}\")
    if value[\"schema_version\"] != \"S1_X4_ALGORITHM_RUN_CONFIG_V2_0\":
        raise ValueError(\"unsupported run config schema\")
    if value[\"task_type\"] not in {\"S1\", \"X4\"}:
        raise ValueError(\"task_type must be S1 or X4\")
    return value


def run_algorithm_benchmark(run_config, algorithm, *, task_type=None, dataset_root=None, output_dir=None):
    # The official source runtime is the evaluator implementation. Keeping
    # this forwarding wrapper makes the public import stable without placing
    # a private registry or canonical Episode resolver in the public dataset.
    from src.s1_x4.algorithm_api.runner import run_algorithm_benchmark as official_runner

    return official_runner(
        run_config,
        algorithm,
        task_type=task_type,
        dataset_root=dataset_root,
        output_dir=output_dir,
    )


__all__ = [\"compile_observation\", \"compile_spectrum\", \"compile_static_context\", \"load_run_config\", \"run_algorithm_benchmark\"]
"""


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _public_generation_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Project a verified canonical spec to the compact public science schema."""

    condition = spec.get("condition") if isinstance(spec.get("condition"), Mapping) else {}
    episode = spec.get("episode") if isinstance(spec.get("episode"), Mapping) else {}
    arrival = spec.get("arrival_rate") if isinstance(spec.get("arrival_rate"), Mapping) else {}
    distribution = spec.get("required_slots_distribution") if isinstance(spec.get("required_slots_distribution"), Mapping) else {}
    state_generation = spec.get("state_generation") if isinstance(spec.get("state_generation"), Mapping) else {}
    return {
        "schema_version": PUBLIC_GENERATION_SPEC_SCHEMA_VERSION,
        "generation_spec_id": str(spec["generation_spec_id"]),
        "topology_id": str(spec["topology_id"]),
        "condition_id": str(spec["condition_id"]),
        "resource_config": {
            "episode_length": int(episode["episode_length"]),
            "slot_count": int(episode["slot_count"]),
            "guard_band_slots": int(distribution["guard_band_slots"]),
        },
        "initial_state_generation": {
            "load_band": condition.get("load_band"),
            "policy": str(state_generation["policy"]),
            "candidate_path_k": int(state_generation["candidate_path_k"]),
            "state_arrival_rate_lambda": arrival.get("state_arrival_rate_lambda"),
        },
        "request_generation": {
            "od_distribution": str(distribution.get("od_distribution", "UNIFORM")),
            "payload_slot_values": [int(value) for value in distribution["payload_slot_values"]],
            "required_slot_values": [int(value) for value in distribution["required_slot_values"]],
            "slot_probabilities": [float(value) for value in distribution["payload_slot_probabilities"]],
        },
        "dynamic_generation": {
            "arrival_rate_mode": condition.get("arrival_rate_mode"),
            "arrival_rate_multiplier": condition.get("arrival_rate_multiplier"),
            "dynamic_arrival_rate_lambda": arrival.get("dynamic_arrival_rate_lambda"),
            "holding_time_rate_mu": float(episode["holding_time_rate_mu"]),
        },
        "seed_block": {str(key): int(value) for key, value in spec["seed_block"].items()},
    }


def _public_reference(panel: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "POLICY_PANEL",
        "episode_length": int(panel.get("episode_length", 0)),
        "primary_metric": "RBR",
        "secondary_metric": "MEAN_NETWORK_EFM",
        "policy_results": [
            {
                key: result[key]
                for key in ("policy_name", "episode_length", "established_count", "blocked_count", "rbr", "mean_network_efm")
                if key in result
            }
            for result in panel.get("policy_results", [])
        ],
    }


def _first_step_views(episode: Mapping[str, Any]) -> dict[str, str]:
    state = DynamicEpisodeState(dict(episode))
    context = state.prepare_current_step()
    if episode["task_type"] == "S1":
        return {"llm_prompt": render_s1_step(episode, context, "llm")}
    return {"llm_prompt": render_x4_step(episode, context, "llm")}


def build_case_overview(
    episode: Mapping[str, Any],
    spec: Mapping[str, Any],
    panel: Mapping[str, Any],
    *,
    task: str,
) -> dict[str, Any]:
    if task not in TASKS:
        raise ValueError("task must be S1 or X4")
    topology = str(spec["topology_id"])
    condition = str(spec["condition_id"])
    return {
        "schema_version": "S1_X4_CASE_OVERVIEW_V2_0",
        "case_id": episode["case_id"],
        "task_type": task,
        "topology_id": topology,
        "condition_id": condition,
        "episode_length": int(episode["episode_length"]),
        "pairing_id": episode["pairing_id"],
        "generation_spec_ref": f"benchmark_case/generation_specs/{topology}/{condition}.json",
        "episode_ref": f"benchmark_case/{task}/episodes/{topology}/{condition}.json",
        "reference_ref": f"reference/{task}/{topology}/{condition}/reference_output.json",
        "experiment_summary": {
            "primary_metric": "RBR",
            "secondary_metric": "MEAN_NETWORK_EFM",
        },
        "first_step_views": _first_step_views(episode),
        "reference_summary": _public_reference(panel),
    }


def _spec_for_episode(episode: Mapping[str, Any], specs: list[Mapping[str, Any]]) -> Mapping[str, Any]:
    for spec in specs:
        pairing = spec.get("pairing", {})
        if episode.get("case_id") in {pairing.get("s1_case_id"), pairing.get("x4_case_id")}:
            return spec
    matches = [spec for spec in specs if spec.get("topology_id") == episode.get("topology_id")]
    if len(matches) == 1:
        return matches[0]
    raise ValueError(f"no unique generation spec for Episode {episode.get('case_id')}")


def _panel_for(reference_panels: Mapping[str, Any], task: str, episode: Mapping[str, Any], index: int) -> Mapping[str, Any]:
    values = reference_panels.get(task, [])
    if isinstance(values, Mapping) and "policy_results" in values:
        return values
    if isinstance(values, Mapping) and episode.get("case_id") in values:
        return values[episode["case_id"]]
    if isinstance(values, list) and index < len(values):
        return values[index]
    return {"type": "POLICY_PANEL", "episode_length": episode["episode_length"], "policy_results": []}


def _episode_source(source_paths: Mapping[Any, Path] | None, task: str, episode: Mapping[str, Any], topology: str, condition: str) -> Path | None:
    if not source_paths:
        return None
    for key in ((task, topology, condition), (task, episode.get("case_id")), episode.get("case_id")):
        if key in source_paths:
            return Path(source_paths[key])
    return None


def export_public_dataset_v2(
    output_root: Path | str,
    *,
    specs: list[Mapping[str, Any]],
    episodes_by_task: Mapping[str, list[Mapping[str, Any]]],
    reference_panels: Mapping[str, Any],
    contracts_root: Path | str,
    source_runtime_root: Path | str | None = None,
    episode_source_paths: Mapping[Any, Path] | None = None,
    reference_source_paths: Mapping[Any, Path] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(output_root).resolve()
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"public V2 output must be new or empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    contract_root = Path(contracts_root).resolve()
    spec_list = [dict(spec) for spec in specs]
    for spec in spec_list:
        errors = validate_generation_spec(spec)
        if errors:
            raise ValueError(f"invalid generation spec {spec.get('generation_spec_id')}: {errors}")
        public_spec = _public_generation_spec(spec)
        _write_json(root / "benchmark_case" / "generation_specs" / spec["topology_id"] / f"{spec['condition_id']}.json", public_spec)

    for task in TASKS:
        episodes = list(episodes_by_task.get(task, []))
        for index, episode in enumerate(episodes):
            spec = _spec_for_episode(episode, spec_list)
            topology = str(spec["topology_id"])
            condition = str(spec["condition_id"])
            panel = _panel_for(reference_panels, task, episode, index)
            overview = build_case_overview(episode, spec, panel, task=task)
            episode_path = root / "benchmark_case" / task / "episodes" / topology / f"{condition}.json"
            source_episode = _episode_source(episode_source_paths, task, episode, topology, condition)
            episode_path.parent.mkdir(parents=True, exist_ok=True)
            if source_episode is not None:
                shutil.copy2(source_episode, episode_path)
            else:
                _write_json(episode_path, episode)
            _write_json(root / "benchmark_case" / task / "cases" / topology / f"{condition}.json", overview)

            task_eval = root / "evaluation_case" / task
            llm_prompt_path = task_eval / "llm" / "system_prompt.txt"
            llm_prompt_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(contract_root / task / "llm_system_prompt.txt", llm_prompt_path)
            views = overview["first_step_views"]
            _write_json(task_eval / "llm" / topology / f"{condition}.json", {"case_id": episode["case_id"], "prompt": views["llm_prompt"]})
            run_config = {
                "schema_version": "S1_X4_ALGORITHM_RUN_CONFIG_V2_0",
                "task_type": task,
                "topology_id": topology,
                "condition_id": condition,
                "generation_spec_ref": f"benchmark_case/generation_specs/{topology}/{condition}.json",
            }
            _write_json(task_eval / "algorithm" / "run_configs" / topology / f"{condition}.json", run_config)

            public_reference = _public_reference(panel)
            reference_dir = root / "reference" / task / topology / condition
            _write_json(reference_dir / "reference_output.json", public_reference)
            for result in panel.get("policy_results", []):
                policy = str(result["policy_name"])
                trajectory = result.get("trajectory", [])
                source_trajectory = None
                if reference_source_paths:
                    for key in ((task, episode.get("case_id"), policy), (task, topology, condition, policy)):
                        if key in reference_source_paths:
                            source_trajectory = Path(reference_source_paths[key])
                            break
                target = reference_dir / "reference_trajectories" / f"{policy}.jsonl"
                target.parent.mkdir(parents=True, exist_ok=True)
                if source_trajectory is not None:
                    shutil.copy2(source_trajectory, target)
                else:
                    target.write_text(
                        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in trajectory),
                        encoding="utf-8",
                    )

    api_root = root / "evaluation_case" / "algorithm_api"
    api_root.mkdir(parents=True, exist_ok=True)
    (api_root / "README.md").write_text(_ALGORITHM_API_README, encoding="utf-8")
    (api_root / "__init__.py").write_text(_ALGORITHM_API_INIT, encoding="utf-8")
    if source_runtime_root is not None:
        source_api = Path(source_runtime_root) / "src" / "s1_x4" / "algorithm_api"
        for name in ("types.py", "bitset.py", "compiler.py", "timing.py"):
            shutil.copy2(source_api / name, api_root / name)
    else:
        raise ValueError("source_runtime_root is required to publish the typed Algorithm API")
    (root / "README.md").write_text(_PUBLIC_README, encoding="utf-8")
    (root / "benchmark_case" / "README.md").write_text(_BENCHMARK_CASE_README, encoding="utf-8")
    (root / "benchmark_case" / "generation_specs" / "README.md").write_text(_GENERATION_SPECS_README, encoding="utf-8")
    return {
        "schema_version": "S1_X4_PUBLIC_DATASET_V2_0",
        "generation_spec_count": len(spec_list),
        "s1_case_count": len(episodes_by_task.get("S1", [])),
        "x4_case_count": len(episodes_by_task.get("X4", [])),
        "provenance": dict(provenance or {}),
    }


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _episode_matches_public_spec(episode: Mapping[str, Any], spec: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    resource = spec["resource_config"]
    dynamic = spec["dynamic_generation"]
    if episode.get("topology_id") != spec.get("topology_id"):
        errors.append("topology_id")
    if episode.get("episode_length") != resource.get("episode_length"):
        errors.append("episode_length")
    if episode.get("slot_count") != resource.get("slot_count"):
        errors.append("slot_count")
    if episode.get("holding_time_rate_mu") != dynamic.get("holding_time_rate_mu"):
        errors.append("holding_time_rate_mu")
    if len(episode.get("request_events", [])) != resource.get("episode_length"):
        errors.append("request_events.length")
    return errors


def verify_public_dataset_v2(dataset_root: Path | str) -> dict[str, Any]:
    root = Path(dataset_root).resolve()
    errors: list[str] = []
    if not root.is_dir():
        return {"valid": False, "errors": [f"dataset not found: {root}"]}
    expected_top = {"README.md", "benchmark_case", "evaluation_case", "reference"}
    actual_top = {path.name for path in root.iterdir()}
    if actual_top != expected_top:
        errors.append(f"top_level_exact:false:{sorted(actual_top)}")
    readme_paths = sorted(root.rglob("README.md"))
    expected_readmes = {
        root / "README.md",
        root / "benchmark_case" / "README.md",
        root / "benchmark_case" / "generation_specs" / "README.md",
        root / "evaluation_case" / "algorithm_api" / "README.md",
    }
    if set(readme_paths) != expected_readmes:
        errors.append(
            "readme_count_or_location:" + str([path.relative_to(root).as_posix() for path in readme_paths])
        )
    required_readme_terms = {
        root / "README.md": ("9 张拓扑", "H=512", "generation_specs"),
        root / "benchmark_case" / "README.md": ("cases/", "episodes/"),
        root / "benchmark_case" / "generation_specs" / "README.md": ("MATCH_STATE", "seed_block"),
        root / "evaluation_case" / "algorithm_api" / "README.md": ("run_config", "current observation", "H=512"),
    }
    for path, terms in required_readme_terms.items():
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            if any(term not in text for term in terms):
                errors.append(f"readme_content:{path.relative_to(root)}")
    forbidden_components = {
        "endpoint_view",
        "dataset_index.json",
        "dataset_index.csv",
        "case_index.jsonl",
        "contracts",
        "internal",
        "sha256sums.txt",
        "__pycache__",
        ".pytest_cache",
    }
    forbidden_hits = []
    for path in root.rglob("*"):
        rel_parts = [part.lower() for part in path.relative_to(root).parts]
        if any(part in forbidden_components for part in rel_parts):
            forbidden_hits.append(path.relative_to(root).as_posix())
        if path.is_file() and path.suffix.lower() in {".pyc", ".pyo"}:
            forbidden_hits.append(path.relative_to(root).as_posix())
    if forbidden_hits:
        errors.append(f"forbidden_public_paths:{forbidden_hits[:10]}")
    spec_paths = sorted((root / "benchmark_case" / "generation_specs").glob("*/*.json"))
    strict = len(spec_paths) == 27
    specs: dict[tuple[str, str], dict[str, Any]] = {}
    for path in spec_paths:
        try:
            spec = _load(path)
            spec_errors = validate_public_generation_spec(spec, strict_matrix=strict)
            if spec_errors:
                errors.append(f"spec:{path.relative_to(root)}:{spec_errors}")
            key = (str(spec.get("topology_id")), str(spec.get("condition_id")))
            if key in specs:
                errors.append(f"duplicate_spec:{key}")
            specs[key] = spec
        except Exception as exc:
            errors.append(f"spec_read:{path.relative_to(root)}:{type(exc).__name__}:{exc}")
    counts = {"generation_specs": len(spec_paths), "S1_cases": 0, "S1_episodes": 0, "X4_cases": 0, "X4_episodes": 0, "S1_run_configs": 0, "X4_run_configs": 0, "S1_llm": 0, "X4_llm": 0, "reference_trajectories": 0}
    for task in TASKS:
        for (topology, condition), spec in specs.items():
            case_path = root / "benchmark_case" / task / "cases" / topology / f"{condition}.json"
            episode_path = root / "benchmark_case" / task / "episodes" / topology / f"{condition}.json"
            llm_path = root / "evaluation_case" / task / "llm" / topology / f"{condition}.json"
            config_path = root / "evaluation_case" / task / "algorithm" / "run_configs" / topology / f"{condition}.json"
            reference_dir = root / "reference" / task / topology / condition
            if case_path.is_file(): counts[f"{task}_cases"] += 1
            else: errors.append(f"missing_case:{case_path.relative_to(root)}")
            if episode_path.is_file(): counts[f"{task}_episodes"] += 1
            else: errors.append(f"missing_episode:{episode_path.relative_to(root)}")
            if llm_path.is_file(): counts[f"{task}_llm"] += 1
            else: errors.append(f"missing_llm:{llm_path.relative_to(root)}")
            if config_path.is_file(): counts[f"{task}_run_configs"] += 1
            else: errors.append(f"missing_run_config:{config_path.relative_to(root)}")
            if not reference_dir.joinpath("reference_output.json").is_file():
                errors.append(f"missing_reference:{reference_dir.relative_to(root)}")
            if case_path.is_file() and episode_path.is_file() and llm_path.is_file() and config_path.is_file():
                try:
                    case = _load(case_path); episode = _load(episode_path); llm = _load(llm_path); config = _load(config_path)
                    if case.get("case_id") != episode.get("case_id") or case.get("task_type") != task:
                        errors.append(f"identity:{task}/{topology}/{condition}")
                    episode_errors = _episode_matches_public_spec(episode, spec)
                    if episode_errors:
                        errors.append(f"episode_spec_mismatch:{task}/{topology}/{condition}:{episode_errors}")
                    if set(case) != PUBLIC_CASE_KEYS:
                        errors.append(f"case_overview_fields:{task}/{topology}/{condition}")
                    for ref_key in ("generation_spec_ref", "episode_ref", "reference_ref"):
                        ref = case.get(ref_key)
                        if not isinstance(ref, str) or not (root / ref).is_file():
                            errors.append(f"bad_ref:{task}/{topology}/{condition}:{ref_key}")
                    if set(llm) != {"case_id", "prompt"} or llm.get("case_id") != episode.get("case_id"):
                        errors.append(f"llm_entry_shape:{task}/{topology}/{condition}")
                    future_ids = [str(event["request_id"]) for event in episode.get("request_events", [])[1:]]
                    if any(future in str(llm.get("prompt", "")) for future in future_ids):
                        errors.append(f"future_prompt_leak:{task}/{topology}/{condition}:llm")
                    if task == "X4":
                        visible = json.dumps({"case": case, "llm": llm}, ensure_ascii=False)
                        if any(token in visible for token in ("candidate_paths", "candidate_actions", "feasible_paths", "feasible_actions", "path_rank")):
                            errors.append(f"x4_oracle_leak:{topology}/{condition}")
                    if set(config) != PUBLIC_RUN_CONFIG_KEYS:
                        errors.append(f"run_config_extra_fields:{task}/{topology}/{condition}")
                    if config.get("generation_spec_ref") != f"benchmark_case/generation_specs/{topology}/{condition}.json":
                        errors.append(f"run_config_ref:{task}/{topology}/{condition}")
                except Exception as exc:
                    errors.append(f"case_read:{task}/{topology}/{condition}:{type(exc).__name__}:{exc}")
            for path in reference_dir.glob("reference_trajectories/*.jsonl"):
                counts["reference_trajectories"] += 1
                try:
                    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
                    if strict and len(lines) != 512:
                        errors.append(f"reference_length:{path.relative_to(root)}:{len(lines)}")
                except Exception as exc:
                    errors.append(f"reference_read:{path.relative_to(root)}:{type(exc).__name__}:{exc}")
    prompt_hashes: dict[str, str] = {}
    for task in TASKS:
        path = root / "evaluation_case" / task / "llm" / "system_prompt.txt"
        if path.is_file():
            prompt_hashes[f"{task}/llm"] = _sha256(path)
            if strict and prompt_hashes[f"{task}/llm"] != EXPECTED_PROMPT_SHA256[f"{task}/llm"]:
                errors.append(f"prompt_hash:{task}/llm")
        else:
            errors.append(f"missing_system_prompt:{task}/llm")
    for path in root.rglob("*"):
        if path.is_file() and path.relative_to(root).as_posix().lower().find("step_") >= 0 and path.is_relative_to(root / "evaluation_case"):
            errors.append(f"fixed_step_file:{path.relative_to(root)}")
    if strict:
        expected_counts = {
            "generation_specs": 27, "S1_cases": 27, "S1_episodes": 27, "X4_cases": 27, "X4_episodes": 27,
            "S1_run_configs": 27, "X4_run_configs": 27, "S1_llm": 27, "X4_llm": 27,
            "reference_trajectories": 378,
        }
        for key, expected in expected_counts.items():
            if counts[key] != expected:
                errors.append(f"count:{key}:{counts[key]}!={expected}")
    return {
        "valid": not errors,
        "strict_27_matrix": strict,
        "counts": counts,
        "prompt_hashes": prompt_hashes,
        "forbidden_path_hits": forbidden_hits,
        "errors": errors,
    }
