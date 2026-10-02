"""lib.comfy_workflow の単体テスト（ネットワークなし・純粋ロジックのみ）。"""
from __future__ import annotations

import json

import pytest

from lib.comfy_workflow import build_sdxl_txt2img_workflow


def test_build_sdxl_txt2img_workflow_default_shape():
    workflow = build_sdxl_txt2img_workflow(
        checkpoint="sd_xl_base_1.0.safetensors",
        positive_prompt="a cat",
    )
    assert workflow["1"]["class_type"] == "CheckpointLoaderSimple"
    assert workflow["1"]["inputs"]["ckpt_name"] == "sd_xl_base_1.0.safetensors"
    assert workflow["2"]["inputs"]["text"] == "a cat"
    assert workflow["3"]["inputs"]["text"] == ""
    assert workflow["5"]["class_type"] == "KSampler"
    assert workflow["6"]["class_type"] == "VAEDecode"
    assert workflow["7"]["class_type"] == "SaveImage"


def test_build_sdxl_txt2img_workflow_links_reference_checkpoint_loader():
    workflow = build_sdxl_txt2img_workflow(
        checkpoint="sd_xl_base_1.0.safetensors",
        positive_prompt="a cat",
    )
    assert workflow["2"]["inputs"]["clip"] == ["1", 1]
    assert workflow["5"]["inputs"]["model"] == ["1", 0]
    assert workflow["6"]["inputs"]["vae"] == ["1", 2]
    assert workflow["5"]["inputs"]["positive"] == ["2", 0]
    assert workflow["5"]["inputs"]["negative"] == ["3", 0]
    assert workflow["6"]["inputs"]["samples"] == ["5", 0]
    assert workflow["7"]["inputs"]["images"] == ["6", 0]


def test_build_sdxl_txt2img_workflow_custom_params():
    workflow = build_sdxl_txt2img_workflow(
        checkpoint="sd_xl_base_1.0.safetensors",
        positive_prompt="a cat",
        negative_prompt="blurry",
        width=768,
        height=1152,
        seed=42,
        steps=30,
        cfg=6.5,
        sampler_name="euler",
        scheduler="normal",
        batch_size=2,
        filename_prefix="test-prefix",
    )
    assert workflow["3"]["inputs"]["text"] == "blurry"
    assert workflow["4"]["inputs"] == {"width": 768, "height": 1152, "batch_size": 2}
    ksampler_inputs = workflow["5"]["inputs"]
    assert ksampler_inputs["seed"] == 42
    assert ksampler_inputs["steps"] == 30
    assert ksampler_inputs["cfg"] == 6.5
    assert ksampler_inputs["sampler_name"] == "euler"
    assert ksampler_inputs["scheduler"] == "normal"
    assert workflow["7"]["inputs"]["filename_prefix"] == "test-prefix"


def test_build_sdxl_txt2img_workflow_is_json_serializable():
    workflow = build_sdxl_txt2img_workflow(
        checkpoint="sd_xl_base_1.0.safetensors",
        positive_prompt="a cat",
    )
    json.dumps(workflow)


def test_build_sdxl_txt2img_workflow_requires_checkpoint():
    with pytest.raises(ValueError):
        build_sdxl_txt2img_workflow(checkpoint="", positive_prompt="a cat")


def test_build_sdxl_txt2img_workflow_requires_positive_prompt():
    with pytest.raises(ValueError):
        build_sdxl_txt2img_workflow(checkpoint="sd_xl_base_1.0.safetensors", positive_prompt="")


def test_build_sdxl_txt2img_workflow_rejects_non_positive_dimensions():
    with pytest.raises(ValueError):
        build_sdxl_txt2img_workflow(checkpoint="ckpt.safetensors", positive_prompt="a cat", width=0)


def test_build_sdxl_txt2img_workflow_rejects_dimensions_not_multiple_of_8():
    with pytest.raises(ValueError):
        build_sdxl_txt2img_workflow(checkpoint="ckpt.safetensors", positive_prompt="a cat", width=1023)


def test_build_sdxl_txt2img_workflow_rejects_non_positive_batch_size():
    with pytest.raises(ValueError):
        build_sdxl_txt2img_workflow(checkpoint="ckpt.safetensors", positive_prompt="a cat", batch_size=0)
