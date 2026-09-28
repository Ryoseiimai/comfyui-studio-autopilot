"""ComfyUIのAPI形式ワークフローJSONを組み立てる（ネットワークなし・純粋関数）。

`ops/executor.py` の `handle_gpu_generate` は `req["workflow"]` をそのまま
`json.dumps` してReplicate（`workflow_json`入力）に渡すだけで、ワークフロー自体の
組み立てはしない。ここで作った dict をそのまま `work/outbox/*.json` の
`gpu_generate.workflow` に入れて依頼する想定。

対応ノードはComfyUIの標準ノードのみ（`CheckpointLoaderSimple` /
`CLIPTextEncode` / `EmptyLatentImage` / `KSampler` / `VAEDecode` / `SaveImage`）。
カスタムノードは使わない（Replicate側の対応状況が不確実なため）。
"""
from __future__ import annotations

CHECKPOINT_LOADER_ID = "1"
POSITIVE_PROMPT_ID = "2"
NEGATIVE_PROMPT_ID = "3"
EMPTY_LATENT_ID = "4"
KSAMPLER_ID = "5"
VAE_DECODE_ID = "6"
SAVE_IMAGE_ID = "7"


def build_sdxl_txt2img_workflow(
    checkpoint: str,
    positive_prompt: str,
    negative_prompt: str = "",
    *,
    width: int = 1024,
    height: int = 1024,
    seed: int = 0,
    steps: int = 25,
    cfg: float = 7.0,
    sampler_name: str = "dpmpp_2m",
    scheduler: str = "karras",
    batch_size: int = 1,
    filename_prefix: str = "comfyui-studio",
) -> dict:
    """SDXL txt2img用のComfyUI API形式ワークフローJSON（ノードID→ノード定義のdict）を返す。

    `checkpoint` は倉庫内のファイル名（例: `sd_xl_base_1.0.safetensors`）を想定。
    """
    if not checkpoint:
        raise ValueError("checkpointは必須")
    if not positive_prompt:
        raise ValueError("positive_promptは必須")
    if width <= 0 or height <= 0:
        raise ValueError("width/heightは正の値のみ")
    if width % 8 != 0 or height % 8 != 0:
        raise ValueError("width/heightは8の倍数のみ（ComfyUIのVAE制約）")
    if batch_size <= 0:
        raise ValueError("batch_sizeは正の値のみ")

    return {
        CHECKPOINT_LOADER_ID: {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        POSITIVE_PROMPT_ID: {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive_prompt, "clip": [CHECKPOINT_LOADER_ID, 1]},
        },
        NEGATIVE_PROMPT_ID: {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": [CHECKPOINT_LOADER_ID, 1]},
        },
        EMPTY_LATENT_ID: {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": batch_size},
        },
        KSAMPLER_ID: {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": 1.0,
                "model": [CHECKPOINT_LOADER_ID, 0],
                "positive": [POSITIVE_PROMPT_ID, 0],
                "negative": [NEGATIVE_PROMPT_ID, 0],
                "latent_image": [EMPTY_LATENT_ID, 0],
            },
        },
        VAE_DECODE_ID: {
            "class_type": "VAEDecode",
            "inputs": {"samples": [KSAMPLER_ID, 0], "vae": [CHECKPOINT_LOADER_ID, 2]},
        },
        SAVE_IMAGE_ID: {
            "class_type": "SaveImage",
            "inputs": {"images": [VAE_DECODE_ID, 0], "filename_prefix": filename_prefix},
        },
    }
