#!/usr/bin/env python3
import argparse
import json
import os
import shlex
import subprocess
from pathlib import Path

import yaml


def load_env(env_path: Path) -> dict[str, str]:
    env = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        env[key] = value
    return env


def load_services(services_path: Path) -> list[dict]:
    data = yaml.safe_load(services_path.read_text())
    services = data.get("services", [])
    if len(services) != 3:
        raise ValueError("Expected exactly 3 services: vllm, whisper, bert_classification")
    return services


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    path.write_text(content)


def build_vllm_command(service: dict, env: dict) -> str:
    args = service.get("vllm_args", {})
    cmd = [
        f"CUDA_VISIBLE_DEVICES={','.join(map(str, service['gpu_ids']))}",
        shlex.quote(f"{env['STACK_ROOT']}/.venv/bin/python"),
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--host",
        env.get("VLLM_HOST", "127.0.0.1"),
        "--port",
        str(service["listen_port"]),
        "--model",
        service["model_name"],
    ]
    for key, value in args.items():
        flag = f"--{key.replace('_', '-')}"
        cmd.extend([flag, str(value)])
    return " ".join(cmd)


def build_whisper_command(service: dict, env: dict) -> str:
    whisper_args = service.get("whisper_args", {})
    cmd = [
        f"CUDA_VISIBLE_DEVICES={','.join(map(str, service['gpu_ids']))}",
        shlex.quote(f"{env['STACK_ROOT']}/.venv/bin/python"),
        shlex.quote(f"{env['STACK_ROOT']}/services/whisper_api.py"),
        "--host",
        env.get("WHISPER_HOST", "127.0.0.1"),
        "--port",
        str(service["listen_port"]),
        "--model-path",
        service["model_name"],
        "--compute-type",
        whisper_args.get("compute_type", "float16"),
        "--beam-size",
        str(whisper_args.get("beam_size", 5)),
    ]
    if whisper_args.get("vad_filter", True):
        cmd.append("--vad-filter")
    return " ".join(cmd)


def build_bert_command(service: dict, env: dict) -> str:
    bert_args = service.get("bert_args", {})
    labels = bert_args.get("labels", [])
    cmd = [
        f"CUDA_VISIBLE_DEVICES={','.join(map(str, service['gpu_ids']))}",
        shlex.quote(f"{env['STACK_ROOT']}/.venv/bin/python"),
        shlex.quote(f"{env['STACK_ROOT']}/services/bert_classifier_api.py"),
        "--host",
        env.get("BERT_HOST", "127.0.0.1"),
        "--port",
        str(service["listen_port"]),
        "--model-path",
        service["model_name"],
        "--max-length",
        str(bert_args.get("max_length", 512)),
    ]
    if bert_args.get("return_all_scores", False):
        cmd.append("--return-all-scores")
    if labels:
        cmd.extend(["--labels-json", shlex.quote(json.dumps(labels))])
    return " ".join(cmd)


def build_litellm_command(env: dict) -> str:
    return " ".join(
        [
            shlex.quote(f"{env['STACK_ROOT']}/.venv/bin/litellm"),
            "--config",
            shlex.quote(f"{env['STACK_ROOT']}/generated/litellm/config.yaml"),
            "--port",
            env.get("LITELLM_PORT", "4000"),
            "--host",
            "127.0.0.1",
        ]
    )


def build_openwebui_command(env: dict) -> str:
    return " ".join(
        [
            shlex.quote(f"{env['STACK_ROOT']}/.venv/bin/open-webui"),
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            env.get("OPENWEBUI_PORT", "3000"),
        ]
    )


def systemd_unit(name: str, command: str, env_file: str, workdir: str) -> str:
    return f"""[Unit]
Description={name}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile={env_file}
WorkingDirectory={workdir}
ExecStart=/bin/bash -lc '{command}'
Restart=always
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
"""


def render_litellm_config(vllm_service: dict, env: dict) -> str:
    alias = vllm_service["alias"]
    api_base = f"http://127.0.0.1:{vllm_service['listen_port']}/v1"
    data = {
        "general_settings": {
            "master_key": env["LITELLM_MASTER_KEY"],
        },
        "model_list": [
            {
                "model_name": alias,
                "litellm_params": {
                    "model": "openai/" + alias,
                    "api_base": api_base,
                    "api_key": "not-needed",
                },
            }
        ],
    }
    return yaml.safe_dump(data, sort_keys=False)


def render_runtime_env(env: dict, vllm_service: dict, whisper_service: dict) -> str:
    runtime = {
        **env,
        "OPENAI_API_BASE_URL": f"http://127.0.0.1:{env.get('LITELLM_PORT', '4000')}/v1",
        "OPENAI_API_KEY": env["LITELLM_MASTER_KEY"],
        "WEBUI_SECRET_KEY": env["OPENWEBUI_SECRET"],
        "WHISPER_BASE_URL": f"http://127.0.0.1:{whisper_service['listen_port']}",
        "QWEN_MODEL_ALIAS": vllm_service["alias"],
    }
    return "".join(f"{key}={value}\n" for key, value in runtime.items())


def render(env_path: Path, services_path: Path, output_path: Path) -> None:
    env = load_env(env_path)
    services = load_services(services_path)
    output_path = output_path.resolve()
    ensure_dir(output_path)
    ensure_dir(output_path / "systemd")
    ensure_dir(output_path / "litellm")

    service_by_type = {service["type"]: service for service in services}
    vllm_service = service_by_type["vllm"]
    whisper_service = service_by_type["whisper"]
    bert_service = service_by_type["bert_classification"]

    env_file = output_path / "runtime.env"
    write_text(env_file, render_runtime_env(env, vllm_service, whisper_service))
    write_text(output_path / "litellm" / "config.yaml", render_litellm_config(vllm_service, env))

    write_text(
        output_path / "systemd" / "vllm-qwen.service",
        systemd_unit(
            "vLLM Qwen",
            build_vllm_command(vllm_service, env),
            str(env_file),
            env["STACK_ROOT"],
        ),
    )
    write_text(
        output_path / "systemd" / "whisper-api.service",
        systemd_unit(
            "Whisper API",
            build_whisper_command(whisper_service, env),
            str(env_file),
            env["STACK_ROOT"],
        ),
    )
    write_text(
        output_path / "systemd" / "bert-classifier.service",
        systemd_unit(
            "BERT Classifier API",
            build_bert_command(bert_service, env),
            str(env_file),
            env["STACK_ROOT"],
        ),
    )
    write_text(
        output_path / "systemd" / "litellm.service",
        systemd_unit(
            "LiteLLM Proxy",
            build_litellm_command(env),
            str(env_file),
            env["STACK_ROOT"],
        ),
    )
    write_text(
        output_path / "systemd" / "open-webui.service",
        systemd_unit(
            "Open WebUI",
            build_openwebui_command(env),
            str(env_file),
            env["STACK_ROOT"],
        ),
    )


def sync_models(env_path: Path, services_path: Path) -> None:
    env = load_env(env_path)
    services = load_services(services_path)
    bucket = env["S3_BUCKET"]
    region = env["AWS_REGION"]
    for service in services:
        local_dir = Path(service["local_dir"])
        ensure_dir(local_dir)
        s3_uri = f"s3://{bucket}/{service['s3_prefix']}"
        subprocess.run(
            ["aws", "s3", "sync", s3_uri, str(local_dir), "--region", region],
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    render_parser = subparsers.add_parser("render")
    render_parser.add_argument("--env", required=True)
    render_parser.add_argument("--services", required=True)
    render_parser.add_argument("--output", required=True)

    sync_parser = subparsers.add_parser("sync-models")
    sync_parser.add_argument("--env", required=True)
    sync_parser.add_argument("--services", required=True)

    args = parser.parse_args()

    if args.command == "render":
        render(Path(args.env), Path(args.services), Path(args.output))
    elif args.command == "sync-models":
        sync_models(Path(args.env), Path(args.services))


if __name__ == "__main__":
    main()
