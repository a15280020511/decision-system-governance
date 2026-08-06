#!/usr/bin/env python3
from __future__ import annotations
import base64
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def unpack(data: str) -> str:
    return zlib.decompress(base64.b64decode(data)).decode("utf-8")

(ROOT / "governance-copilot/top50_reasoning_pool_extension.py").write_text(
    unpack("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"), encoding="utf-8"
)
(ROOT / "tests/test_top50_reasoning_pool_extension.py").write_text(
    unpack("eNrlV99vIjcQfuevsPy0RLABeknvkKhatVfppF4b9fKGkOXsDuDitfdsbxIu4n/vjHeB5W7JJQ996j7AYs+M58f3zZilswUTYlmFyoEQTBWldYFJY2yQQVnje71mrf7S6i6tgtK9JWmWMqxxZa92gz/34pVRIYAPvV4vhyUT2spcFDavNCT9aY/hQ9psFrUS9EFp9KCfOvBW36NQWkoHJvj5eMEuGV/Ze3BGmgyGmS2VtoHTcrDl1Ug4kN4aZVaitFYLeAxgPLqfllsez/IlZHjWaRAprQqKpD5d2ywGnXRbpXD4ILrdj0al94ChRtvKM8wZ+9MawPTlcTGloMG196JenYZv3anXa4dIP6GP/sH/xlwKj+h1k8r6q5ZxgFU0jfV93p19SJTJ4XHKlAl9NvyJ5SoLdQXsg0H3ZmzJM1uU0myfouiOt+09xR/0cJXzKQo/Rb3dJZ4EerjXGRzljCwgSn4kCdYhkUmDmc2kFl5Xq5dZzawJWFmhwazCGnV+mPx4/bYl4KuS8gm5QOigCwGcR7E5PxSSL1ri0mVrFSAj7KPYE1emrAJlVmoVFNS6dCSqMW6rcHZ71zKL2BGls/cKaxXNFvJRUH41ELhEsBsEJ+68Gb27biuWTmXkI+mggaIM+MpH6YieMSKPH620dia8bQQeS+UiikUuA8VFsKsFdgiKTCNq2S3h++99Vm4Q3e/3lLlFlPtkT9+Ufv4qPTScJUzRunDyoWbFBqD0yJ9l2IoHgI3etngTa+kTD3oZoUe+TA/OHnhw2h0O+4hdj7vzI4j7bGmRT/SKn8xJs4JkPGBX1/1F76BXx/i73MAn0Fhf645n0vPxr9/e//FJ/HLzAa3zdQiln15ewqOk7KbK3GOB8xqHnvdOVH/21BczxNba5ic7kW1LCNla/IPRJ5XTU+aDG7BY8PjeP/UjEhtTk9aN5AM2Ho/4nRXWh2Fpy0pLh2VHS/3v6nVAf3aE/Rkje4ZzhIpEqFDCd8eAqb4DJjBJdWnSY9VJMmlneEDAxzj58ZSWi+8/V1InSNyEtPtYsNEzciQzHy3mvMmBQmhhqTdEw/H39IbjbsUzJ966ChKpdYIRneiV4JTN+YLNECMEbB6xh2KEvBhGv3fKCZwMWH3lhcxz7BD3gFzHWaR8iDNES/O/YcJdpXReh4xCGwgNDWacd5DggEMNK5ltMW3lZCQK6TaxhVKNEF9kTfi1nFxdU/uzOue7/5idaolDD6eO1moFdPVYq9V6GOxQ2wdOeSc732h1UWv+VE/PCDN8W+zacKL6Lnav5ecLQnbwuVIO28J+eNbTpynK+VK8Hb+bvOog3L3Du0uEilB5sn85fwRV9VVHEMfVcivw7pArGm7J4a0p44B9He8zYOss28XF0WanAK+9UNRpmyGPZ1WGZvXkjAqYvLQII4GEwhutddsWjCVnF+z6zRnVM/UjLHy1c8ZAoYwqqqLzAjIeTTrObQGsaft1X/NNBzlp+8cWRezEJtLeTFtd4Gn3/ISIfZgk551NYPFc249anVd2r77AM82/NZY6bTSNb9F/pQW8hOFek7HIiwOqXmCtbammEe6qlSkQO0JWSA4aUPFOWh80JG3vaX+Y4Qe4Id4FMH6PucY/cMgdQVdy/INHw0xgUpURgtfcOFz1aBVnzr8DulJy"), encoding="utf-8"
)

path = ROOT / "tools/sign_expert_plan.py"
text = path.read_text(encoding="utf-8")
text = text.replace(
    'TOP20_POOL_PATH = ROOT / "governance-copilot" / "top20_reasoning_pool.py"\n',
    'TOP20_POOL_PATH = ROOT / "governance-copilot" / "top20_reasoning_pool.py"\n'
    'TOP50_POOL_PATH = ROOT / "governance-copilot" / "top50_reasoning_pool_extension.py"\n',
)
text = text.replace(
    'TOP20_POOL = _load_module(\n    "governance_plan_preview_top20_pool",\n    TOP20_POOL_PATH,\n)\nTASK_ENVELOPE.patch_selector(SELECTOR)\nTOP20_POOL.patch_selector(SELECTOR)\n',
    'TOP20_POOL = _load_module(\n    "governance_plan_preview_top20_pool",\n    TOP20_POOL_PATH,\n)\n'
    'TOP50_POOL = _load_module(\n    "governance_plan_preview_top50_pool",\n    TOP50_POOL_PATH,\n)\n'
    'TASK_ENVELOPE.patch_selector(SELECTOR)\n'
    'TOP20_POOL.patch_selector(SELECTOR)\n'
    'TOP50_POOL.patch_selector(SELECTOR)\n',
)
needle = '''    if plan.get("old_flagship_filter_applied_to_top20_pool") is not False:
        raise ExpertPlanSigningError("old flagship filter must not alter the top-20 pool")
'''
insert = needle + '''    if plan.get("top50_reasoning_pool_size") != 50:
        raise ExpertPlanSigningError("top-50 reasoning pool is incomplete")
    if plan.get("top50_reasoning_pool_period") != "week":
        raise ExpertPlanSigningError("top-50 popularity period must be week")
    if plan.get("top50_candidate_pool_authority") != "decision-system-governance":
        raise ExpertPlanSigningError("top-50 candidate-pool authority is invalid")
    if plan.get("top50_model_assignment_authority") != "expert-assessment-center-ortools":
        raise ExpertPlanSigningError("top-50 assignment authority is invalid")
    top50_raw = plan.get("top50_reasoning_models")
    top50_eligible = plan.get("top50_expert_selectable_candidates")
    if not isinstance(top50_raw, list) or len(top50_raw) != 50:
        raise ExpertPlanSigningError("top-50 reasoning rows are invalid")
    top50_companies = _distinct_candidate_companies(top50_eligible)
    if len(top50_companies) < 8:
        raise ExpertPlanSigningError("top-50 pool has fewer than eight executable companies")
    if plan.get("top50_expert_selectable_distinct_company_count") != len(top50_companies):
        raise ExpertPlanSigningError("top-50 distinct-company count is inconsistent")
'''
if needle not in text:
    raise SystemExit("signer validation insertion point not found")
text = text.replace(needle, insert, 1)
receipt_needle = '''        "top20_reasoning_pool_sha256": plan["top20_reasoning_pool_sha256"],
        "expert_selectable_candidate_count": plan[
'''
receipt_insert = '''        "top20_reasoning_pool_sha256": plan["top20_reasoning_pool_sha256"],
        "top50_reasoning_pool_size": plan["top50_reasoning_pool_size"],
        "top50_reasoning_pool_period": plan["top50_reasoning_pool_period"],
        "top50_reasoning_pool_sha256": plan["top50_reasoning_pool_sha256"],
        "top50_expert_selectable_candidate_count": plan[
            "top50_expert_selectable_candidate_count"
        ],
        "top50_expert_selectable_distinct_company_count": plan[
            "top50_expert_selectable_distinct_company_count"
        ],
        "expert_selectable_candidate_count": plan[
'''
if receipt_needle not in text:
    raise SystemExit("signer receipt insertion point not found")
text = text.replace(receipt_needle, receipt_insert, 1)
path.write_text(text, encoding="utf-8")

(ROOT / "tools/apply_top50_pool_upgrade.py").unlink(missing_ok=True)
(ROOT / ".github/workflows/apply-top50-pool-upgrade.yml").unlink(missing_ok=True)
