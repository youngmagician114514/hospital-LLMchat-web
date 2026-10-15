"""Start one Qwen checkpoint on a single GPU through vLLM."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


def main() -> None:
    profiles = json.loads(Path(__file__).with_name("vllm_profiles.json").read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=profiles)
    parser.add_argument("--model-root", type=Path, help="Directory containing one subdirectory per profile")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--max-model-len", type=int)
    parser.add_argument("--max-num-seqs", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    profile = profiles[args.profile]
    model = profile["repo"]
    if args.model_root:
        model = str((args.model_root / args.profile).resolve())
        if not args.dry_run and not (Path(model) / "config.json").is_file():
            parser.error(f"Model files not found: {model}")
    max_len = args.max_model_len if args.max_model_len is not None else profile["max_model_len"]
    max_seqs = args.max_num_seqs if args.max_num_seqs is not None else profile["max_num_seqs"]
    if max_len < 1 or max_seqs < 1 or not 1 <= args.port <= 65535:
        parser.error("Context length, sequence count and port must be positive and valid")
    command = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", model,
        "--served-model-name", args.profile,
        "--host", args.host, "--port", str(args.port),
        "--tensor-parallel-size", "1",
        "--gpu-memory-utilization", str(profile["gpu_memory_utilization"]),
        "--max-model-len", str(max_len), "--max-num-seqs", str(max_seqs),
        "--max-num-batched-tokens", "2048",
        "--dtype", profile["dtype"],
        "--reasoning-parser", "qwen3",
        "--enforce-eager",
    ]
    if profile["text_only"]:
        command.append("--language-model-only")
    if args.dry_run:
        print(json.dumps(command, ensure_ascii=False))
        return
    env = dict(os.environ)
    if not args.model_root:
        env.setdefault("VLLM_USE_MODELSCOPE", "true")
    os.execvpe(command[0], command, env)


if __name__ == "__main__":
    main()
