"""lib.comfy_workflow の単体テスト（純粋関数・ネットワークなし）。"""
from __future__ import annotations

import json

import pytest

from lib.comfy_workflow import DEFAULT_NEGATIVE_PROMPT, build_sdxl_txt2img_workflow


def test_build_sdxl_txt2img_workflow_wires_nodes_correctly():
    workflow = build_sdxl_txt2img_workflow("sd_xl_base_1.0.safetensors", "a fox in a forest, illustration")

    assert workflow["4"]["class_type"] == "CheckpointLoaderSimple"
    assert workflow["4"]["inputs"]["ckpt_name"] == "sd_xl_base_1.0.safetensors"

    assert workflow["6"]["inputs"]["text"] == "a fox in a forest, illustration"
    assert workflow["6"]["inputs"]["clip"] == ["4", 1]
    assert workflow["7"]["inputs"]["text"] == DEFAULT_NEGATIVE_PROMPT

    sampler = workflow["3"]["inputs"]
    assert sampler["model"] == ["4", 0]
    assert sampler["positive"] == ["6", 0]
    assert sampler["negative"] == ["7", 0]
    assert sampler["latent_image"] == ["5", 0]

    assert workflow["8"]["inputs"]["samples"] == ["3", 0]
    assert workflow["8"]["inputs"]["vae"] == ["4", 2]
    assert workflow["9"]["inputs"]["images"] == ["8", 0]


def test_build_sdxl_txt2img_workflow_accepts_checkpoint_url():
    url = "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors"
    workflow = build_sdxl_txt2img_workflow(url, "a fox in a forest")
    assert workflow["4"]["inputs"]["ckpt_name"] == url


def test_build_sdxl_txt2img_workflow_custom_params_pass_through():
    workflow = build_sdxl_txt2img_workflow(
        "ckpt.safetensors",
        "prompt",
        "bad quality",
        width=512,
        height=768,
        steps=8,
        cfg=2.0,
        sampler_name="dpmpp_2m",
        scheduler="karras",
        seed=42,
        filename_prefix="test_run",
    )
    assert workflow["5"]["inputs"] == {"width": 512, "height": 768, "batch_size": 1}
    assert workflow["7"]["inputs"]["text"] == "bad quality"
    sampler = workflow["3"]["inputs"]
    assert sampler["steps"] == 8
    assert sampler["cfg"] == 2.0
    assert sampler["sampler_name"] == "dpmpp_2m"
    assert sampler["scheduler"] == "karras"
    assert sampler["seed"] == 42
    assert workflow["9"]["inputs"]["filename_prefix"] == "test_run"


def test_build_sdxl_txt2img_workflow_rejects_empty_prompt():
    with pytest.raises(ValueError):
        build_sdxl_txt2img_workflow("ckpt.safetensors", "   ")


def test_build_sdxl_txt2img_workflow_rejects_empty_checkpoint():
    with pytest.raises(ValueError):
        build_sdxl_txt2img_workflow("  ", "a prompt")


def test_build_sdxl_txt2img_workflow_is_json_serializable_for_replicate():
    workflow = build_sdxl_txt2img_workflow("ckpt.safetensors", "a prompt")
    # ops.executor.handle_gpu_generate は json.dumps(workflow) して Replicate へ渡す
    json.dumps(workflow)
