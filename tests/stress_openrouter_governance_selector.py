from __future__ import annotations

import argparse
import importlib.util
import json
import random
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_FILE = ROOT / "tests" / "test_openrouter_governance_selector.py"


def load_tests():
    spec = importlib.util.spec_from_file_location("selector_regression_helpers", TEST_FILE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load selector regression helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20260805)
    args = parser.parse_args()
    if args.iterations < 1 or args.iterations > 5000:
        raise SystemExit("iterations must be between 1 and 5000")

    helper = load_tests()
    rng = random.Random(args.seed)
    fixture = helper.SelectorPipelineTests()
    started = time.monotonic()
    selections: dict[str, int] = {}

    for iteration in range(args.iterations):
        models, benchmarks = fixture.standard_fixture()

        specialized_count = rng.randint(0, 20)
        for index in range(specialized_count):
            model_id = f"stress-{iteration}/coder-pro-{index}"
            row = helper.model(
                model_id,
                prompt=0.001 + index / 10000,
                completion=0.002 + index / 10000,
            )
            models.insert(5, row)
            benchmarks.insert(5, helper.benchmark(model_id, 43 + (index % 3)))

        noise_count = rng.randint(0, 100)
        for index in range(noise_count):
            model_id = f"noise-{iteration}/free-{index}"
            models.insert(0, helper.model(model_id, prompt=0, completion=0))
            benchmarks.insert(0, helper.benchmark(model_id, 90))

        nex_index = next(
            index for index, row in enumerate(models) if row["id"] == "nex-agi/nex-n2-pro"
        )
        deep_index = next(
            index
            for index, row in enumerate(models)
            if row["id"] == "deepseek/deepseek-v4-pro"
        )
        if rng.random() < 0.5:
            deep = models.pop(deep_index)
            nex_index = next(
                index
                for index, row in enumerate(models)
                if row["id"] == "nex-agi/nex-n2-pro"
            )
            models.insert(nex_index, deep)
            expected = "deepseek/deepseek-v4-pro"
        else:
            expected = "nex-agi/nex-n2-pro"

        result = helper.run_pipeline(models, benchmarks)
        selected = result["selected_model"]["model_id"]
        if selected != expected:
            raise AssertionError(
                f"iteration {iteration}: expected {expected}, selected {selected}"
            )
        candidate_ids = [
            row["model_id"] for row in result["cheapest_paid_flagship_candidates"]
        ]
        if any("coder" in item.lower() for item in candidate_ids):
            raise AssertionError(f"iteration {iteration}: specialized model leaked")
        if result.get("model_calls") != 0 or result.get("secret_values_exposed") is not False:
            raise AssertionError(f"iteration {iteration}: safety invariant failed")

        repeated = helper.run_pipeline(models, benchmarks)
        if repeated["selected_model"]["model_id"] != selected:
            raise AssertionError(f"iteration {iteration}: non-deterministic selection")
        if repeated["cheapest_paid_flagship_candidates"] != result[
            "cheapest_paid_flagship_candidates"
        ]:
            raise AssertionError(f"iteration {iteration}: non-deterministic candidates")
        selections[selected] = selections.get(selected, 0) + 1

    elapsed = time.monotonic() - started
    receipt = {
        "status": "OPENROUTER_SELECTOR_STRESS_PASS",
        "iterations": args.iterations,
        "seed": args.seed,
        "elapsed_seconds": round(elapsed, 6),
        "selection_counts": selections,
        "model_calls": 0,
        "estimated_model_cost_usd": 0,
        "invariants": [
            "price-order winner preserved after specialized filtering",
            "free catalog noise cannot change winner",
            "domain-specialized Pro names cannot enter governance candidates",
            "same snapshot produces identical result",
            "no secret value or model call is produced",
        ],
    }
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
