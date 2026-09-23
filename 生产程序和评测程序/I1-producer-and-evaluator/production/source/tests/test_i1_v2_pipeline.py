from __future__ import annotations
import json
from pathlib import Path
from src.i1.pipeline import derive_i1_dataset
from src.i1.dataset_validator import verify_i1_dataset

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / "tests" / "fixtures" / "public_environment_gabriel10"


def test_i1_small_batch_exports_llm_only_public_cases(tmp_path):
    out = tmp_path / "i1"
    summary = derive_i1_dataset(ENV, ROOT / "configs" / "i1_representative.json", out)
    assert summary["case_count"] == 6
    assert summary["task_counts"] == {"I1-S":2,"I1-C":2,"I1-D":2}
    for task in ("I1-S","I1-C","I1-D"):
        p = sorted((out / "benchmark_case" / task / "cases").glob("*.json"))[0]
        case = json.loads(p.read_text(encoding="utf-8"))
        assert set(case) == {"case_id","llm_prompt","answer"}
        ep = out / "evaluation_case" / task / "cases" / p.name
        e = json.loads(ep.read_text(encoding="utf-8"))
        assert set(e) == {"case_id","prompt"}
        assert e["prompt"] == case["llm_prompt"]
        assert "answer" not in e
    report = verify_i1_dataset(out)
    assert report["valid"], report["errors"]


def test_i1_concurrent_batch_can_expand_beyond_prebuilt_request_sets(tmp_path):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({
        "profile":"concurrent_expand",
        "seed":20260910,
        "case_counts":{"I1-S":0,"I1-C":5,"I1-D":0},
        "objective_profiles":{
            "I1-S":["MIN-HOP-COUNT","MIN-FRAGMENTATION"],
            "I1-C":["MIN-TOTAL-SLOT-USAGE","MIN-FRAGMENTATION"],
            "I1-D":["MAX-ACCEPTED-REQUESTS","MIN-EXTERNAL-FRAGMENTATION"]
        },
        "rewrite":{"enabled":False,"mode":"identity","max_attempts":3},
        "allow_shortfall":False
    }), encoding="utf-8")
    out = tmp_path / "expanded"
    summary = derive_i1_dataset(ENV, cfg, out)
    assert summary["task_counts"]["I1-C"] == 5


class _RetryingRewriteClient:
    def __init__(self):
        self.rewrite_calls = 0
        self.last_prompt = None

    def rewrite(self, base_prompt, answer):
        self.rewrite_calls += 1
        if self.rewrite_calls == 1:
            return base_prompt.replace("节点", "节点", 1).replace("9到", "8到", 1)
        self.last_prompt = base_prompt.replace("请为", "请协助为", 1)
        return self.last_prompt

    def parse_intent(self, prompt, answer_hint=None):
        if prompt == self.last_prompt:
            return answer_hint
        bad = dict(answer_hint)
        if bad.get("intent_type") == "SINGLE":
            bad["source_node_id"] = 8
        return bad


def test_llm_rewrite_retry_and_model_lineage_are_recorded(tmp_path):
    cfg = tmp_path / "rewrite_cfg.json"
    cfg.write_text(json.dumps({
        "profile":"rewrite_test",
        "seed":20260910,
        "case_counts":{"I1-S":1,"I1-C":0,"I1-D":0},
        "objective_profiles":{
            "I1-S":["MIN-HOP-COUNT","MIN-FRAGMENTATION"],
            "I1-C":["MIN-TOTAL-SLOT-USAGE","MIN-FRAGMENTATION"],
            "I1-D":["MAX-ACCEPTED-REQUESTS","MIN-EXTERNAL-FRAGMENTATION"]
        },
        "rewrite":{
            "enabled":True,"mode":"openai_compatible","provider":"TestProvider",
            "base_url":"https://example.invalid/v1","api_key_env":"TEST_KEY",
            "model":"fake-rewriter","temperature":0.7,"max_attempts":3
        },
        "allow_shortfall":False
    }), encoding="utf-8")
    out = tmp_path / "rewritten"
    client = _RetryingRewriteClient()
    derive_i1_dataset(ENV, cfg, out, rewrite_client=client)
    rec = json.loads((out / "internal" / "cases" / "I1-S" / "I1_S_000001" / "rewrite.json").read_text(encoding="utf-8"))
    lineage = json.loads((out / "internal" / "cases" / "I1-S" / "I1_S_000001" / "lineage.json").read_text(encoding="utf-8"))
    assert len(rec["attempts"]) == 2
    assert rec["provider"] == "TestProvider"
    assert rec["model"] == "fake-rewriter"
    assert lineage["rewrite_model"] == "fake-rewriter"


def test_i1_static_profiles_cover_fragmentation_only_and_integrated_objectives(tmp_path):
    out = tmp_path / "objective_coverage"
    derive_i1_dataset(ENV, ROOT / "configs" / "i1_small_batch.json", out)
    single_objectives = {
        tuple(json.loads(p.read_text(encoding="utf-8"))["answer"]["objectives"])
        for p in (out / "benchmark_case" / "I1-S" / "cases").glob("*.json")
    }
    concurrent_objectives = {
        tuple(json.loads(p.read_text(encoding="utf-8"))["answer"]["objectives"])
        for p in (out / "benchmark_case" / "I1-C" / "cases").glob("*.json")
    }
    assert ("MIN-FRAGMENTATION",) in single_objectives
    assert ("MIN-HOP-COUNT", "MIN-FRAGMENTATION") in single_objectives
    assert ("MIN-FRAGMENTATION",) in concurrent_objectives
    assert ("MIN-TOTAL-SLOT-USAGE", "MIN-FRAGMENTATION") in concurrent_objectives


def test_i1_internal_features_record_serialization_metrics(tmp_path):
    out = tmp_path / "metrics"
    derive_i1_dataset(ENV, ROOT / "configs" / "i1_representative.json", out)
    features_path = out / "internal" / "cases" / "I1-S" / "I1_S_000001" / "features.json"
    features = json.loads(features_path.read_text(encoding="utf-8"))
    metrics = features["serialization_metrics"]
    assert "prompt_char_count" in metrics
    assert "prompt_utf8_bytes" in metrics
    assert "prompt_token_count" in metrics
    assert metrics["canonical_tokenizer"]["encoding"] == "o200k_base"


def test_i1_explicit_base_stage_exports_inspectable_templates(tmp_path):
    from src.i1.pipeline import derive_i1_base_dataset
    from src.i1.base_dataset import verify_i1_base_dataset

    out = tmp_path / "base"
    summary = derive_i1_base_dataset(ENV, ROOT / "configs" / "i1_representative.json", out)
    assert summary["case_count"] == 6
    assert not (out / "benchmark_case").exists()
    assert not (out / "evaluation_case").exists()
    for task in ("I1-S", "I1-C", "I1-D"):
        case_path = sorted((out / "base_case" / task / "cases").glob("*.json"))[0]
        case = json.loads(case_path.read_text(encoding="utf-8"))
        assert set(case) == {"case_id", "llm_prompt", "answer"}
        assert (out / "base_case" / task / "llm_system_prompt.txt").is_file()
    report = verify_i1_base_dataset(out)
    assert report["valid"], report["errors"]


def test_i1_rewrite_stage_consumes_base_dataset_and_exports_final_cases(tmp_path):
    from src.i1.pipeline import derive_i1_base_dataset, rewrite_i1_base_dataset

    base = tmp_path / "base"
    final = tmp_path / "final"
    derive_i1_base_dataset(ENV, ROOT / "configs" / "i1_representative.json", base)

    cfg = tmp_path / "rewrite_cfg.json"
    cfg.write_text(json.dumps({
        "profile":"rewrite_stage_test",
        "seed":20260910,
        "case_counts":{"I1-S":0,"I1-C":0,"I1-D":0},
        "objective_profiles":{
            "I1-S":["MIN-HOP-COUNT","MIN-FRAGMENTATION"],
            "I1-C":["MIN-TOTAL-SLOT-USAGE","MIN-FRAGMENTATION"],
            "I1-D":["MAX-ACCEPTED-REQUESTS","MIN-EXTERNAL-FRAGMENTATION"]
        },
        "rewrite":{
            "enabled":True,"mode":"openai_compatible","provider":"TestProvider",
            "base_url":"https://example.invalid/v1","api_key_env":"TEST_KEY",
            "model":"fake-rewriter","temperature":0.7,"max_attempts":3
        },
        "allow_shortfall":False,
        "require_canonical_tokenizer":False
    }), encoding="utf-8")

    class _Client:
        def rewrite(self, base_prompt, answer):
            return base_prompt.replace("请为", "请协助为", 1)
        def parse_intent(self, prompt, answer_hint=None):
            return answer_hint

    summary = rewrite_i1_base_dataset(base, cfg, final, rewrite_client=_Client())
    assert summary["case_count"] == 6
    report = verify_i1_dataset(final)
    assert report["valid"], report["errors"]
    for task in ("I1-S", "I1-C", "I1-D"):
        base_case = json.loads(sorted((base / "base_case" / task / "cases").glob("*.json"))[0].read_text(encoding="utf-8"))
        final_case = json.loads(sorted((final / "benchmark_case" / task / "cases").glob("*.json"))[0].read_text(encoding="utf-8"))
        assert final_case["answer"] == base_case["answer"]
        assert final_case["llm_prompt"] != base_case["llm_prompt"]
