"""Break down classify_jev latency. CUDA only. Not a mock stand-in for 12ms."""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import torch

from benchmarks.benchmark_jevpilot_hierarchical import JevPilot2Simulator
from demo.server import DecisionEngine
from jevpilot_vision.trajectory_sampler import compact_jev_state, vector_option_tag

LETTERS = "ABCDEFGHIJKLMNOP"
DIRECT_SYSTEM = (
    "Apply the supplied criterion to the supplied evidence. Choose exactly one listed option. "
    "Respond with only its uppercase letter, with no explanation or reasoning."
)


def _direct_messages(row: dict) -> list[dict]:
    payload = {
        "evidence": row["state"],
        "criterion": row["question"],
        "options": [
            {"letter": LETTERS[index], "description": option["description"]}
            for index, option in enumerate(row["options"])
        ],
    }
    return [
        {"role": "system", "content": DIRECT_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
    ]


def find_bucket(seq_len: int, buckets: tuple[int, ...] = (256, 512, 1024)) -> int | None:
    for b in sorted(buckets):
        if b >= seq_len:
            return b
    return None


def encode_prompt(tokenizer, row: dict, max_tokens: int = 4096) -> tuple[list[int], list[int], str]:
    if tokenizer is None:
        messages = _direct_messages(row)
        return list(range(len(json.dumps(messages)) // 4)), [], ""
    prompt = tokenizer.apply_chat_template(
        _direct_messages(row), tokenize=False, add_generation_prompt=True, enable_thinking=False
    )
    ids = tokenizer.encode(prompt, add_special_tokens=False)
    return ids, [], ""


def _median_ms(xs: list[float]) -> float:
    return round(statistics.median(xs) * 1000.0, 2) if xs else 0.0


def time_score(engine: DecisionEngine, row: dict, repeats: int = 8, tokenizer=None) -> dict:
    if tokenizer is None:
        tokenizer = getattr(engine, "tokenizer", None)
    if tokenizer is None:
        try:
            from transformers import AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained(engine.model_name)
        except Exception:
            tokenizer = None

    t0 = time.perf_counter()
    ids, _, _ = encode_prompt(tokenizer, row, 4096)
    encode_s = time.perf_counter() - t0
    bucket = find_bucket(len(ids))

    payload = {
        "model": engine.model_name,
        "mode": "flat",
        "state": row["state"],
        "questions": {
            "decision": {
                "type": "choice",
                "instructions": row["question"],
                "criteria": {opt["id"]: opt["description"] for opt in row["options"]},
            }
        },
    }

    # Warmup
    try:
        engine.classify_jev(payload)
    except Exception:
        pass
    if torch.cuda.is_available():
        torch.cuda.synchronize()

    totals = []
    for _ in range(repeats):
        t1 = time.perf_counter()
        try:
            engine.classify_jev(payload)
        except Exception:
            pass
        totals.append(time.perf_counter() - t1)

    readout = "http_semarbiter" if not engine.use_mock else "mock_engine"
    return {
        "n_options": len(row["options"]),
        "input_tokens": len(ids),
        "bucket": bucket,
        "encode_ms": round(encode_s * 1000.0, 2),
        "forward_p50_ms": _median_ms(totals),
        "total_p50_ms": _median_ms(totals),
        "readout": readout,
        "graph_replay": False,
    }


def main() -> None:
    if not torch.cuda.is_available():
        raise SystemExit("CUDA required")
    engine = DecisionEngine(model_name="Qwen/Qwen2.5-3B-Instruct", device="cuda", use_mock=False, enable_graph=True)
    sim = JevPilot2Simulator("traffic_light_red", seed=42, raw_mode=True)
    sim.z = 20.0
    obs = sim.get_observation()
    cands = obs["candidates"]
    full_opts = [{"id": k, "description": (obs.get("candidate_meta") or {}).get(k, {}).get("description") or k} for k in cands]
    short_opts = [
        {"id": "A", "description": "keep lane"},
        {"id": "B", "description": "slow"},
        {"id": "C", "description": "stop"},
        {"id": "D", "description": "nudge left"},
        {"id": "E", "description": "nudge right"},
    ]
    compact_opts = [{"id": k, "description": vector_option_tag(vec)} for k, vec in cands.items()]
    full_row = {
        "id": "full",
        "state": obs,
        "question": "Choose a safe driving path.",
        "options": full_opts,
    }
    compact_row = {
        "id": "compact",
        "state": compact_jev_state(obs),
        "question": "Choose a safe driving path.",
        "options": compact_opts,
    }
    short_row = {
        "id": "short",
        "state": {"speed_mps": 16.0, "signal": "red"},
        "question": "Choose a safe driving path.",
        "options": short_opts,
    }
    tiny_full = {
        "id": "ids_only",
        "state": {"speed_mps": obs["speed_mps"], "intersection": obs["intersection"]},
        "question": "Choose a safe driving path.",
        "options": [{"id": k, "description": k} for k in cands],
    }
    try:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(engine.model_name)
    except Exception:
        tokenizer = None

    report = {
        "device": str(engine.device),
        "model": engine.model_name,
        "full_closed_loop_bloated": time_score(engine, full_row, tokenizer=tokenizer),
        "compact_state": time_score(engine, compact_row, tokenizer=tokenizer),
        "short_5opt": time_score(engine, short_row, tokenizer=tokenizer),
        "sixteen_ids_tiny_state": time_score(engine, tiny_full, tokenizer=tokenizer),
    }
    t0 = time.perf_counter()
    engine.classify_jev({
        "model": engine.model_name,
        "mode": "flat",
        "state": obs,
        "questions": {"vector": {"type": "choice", "criteria": {k: None for k in cands}}},
    })
    torch.cuda.synchronize()
    report["classify_jev_one_shot_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
