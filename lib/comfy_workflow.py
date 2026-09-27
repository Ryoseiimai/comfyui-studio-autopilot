"""ComfyUI API形式ワークフローJSONの組み立て（純粋関数・ネットワークなし）。

BACKLOG#3（GPU実行コードの下ごしらえ）向け。`ops/executor.py` の `handle_gpu_generate` は
任意のワークフローJSON（dict）をそのままReplicateへ渡す作りなので、ここでは「SDXLの
標準チェックポイント1枚でtxt2imgする」という最小構成のAPI形式グラフを組み立てる関数を
用意する。ノード構成はComfyUIの標準txt2imgワークフロー（CheckpointLoaderSimple→
CLIPTextEncode×2→EmptyLatentImage→KSampler→VAEDecode→SaveImage）と同じ形。

`checkpoint` には倉庫内のファイル名（Replicateコンテナ側に事前配置済みの場合）、または
HuggingFaceの直ファイルURLをそのまま渡せる。Replicateの `fofr/any-comfyui-workflow`
（= `comfyui/any-comfyui-workflow`）は「API JSON中のckpt_name等をURLに書き換えると
実行時にダウンロードする」という挙動を持つとドキュメントで案内されている（2026-09-27
WebFetch調査・実トークンでの動作確認はまだ・要検証の前提）。
"""
from __future__ import annotations

DEFAULT_NEGATIVE_PROMPT = "worst quality, low quality, nsfw, real photo, realistic human, text, watermark"


def build_sdxl_txt2img_workflow(
    checkpoint: str,
    positive_prompt: str,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    *,
    width: int = 1024,
    height: int = 1024,
    steps: int = 25,
    cfg: float = 7.0,
    sampler_name: str = "euler",
    scheduler: str = "normal",
    seed: int = 0,
    filename_prefix: str = "comfyui_studio",
) -> dict:
    """SDXL標準チェックポイント1枚でのtxt2imgをComfyUI API形式JSONで返す。

    `checkpoint` はComfyUIの `CheckpointLoaderSimple` ノードの `ckpt_name` にそのまま入る
    （倉庫内のファイル名、またはReplicate側がURLからダウンロードできる直ファイルURL）。
    """
    if not positive_prompt.strip():
        raise ValueError("positive_prompt is required")
    if not checkpoint.strip():
        raise ValueError("checkpoint is required")

    return {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive_prompt, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["4", 1]},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": sampler_name,
                "scheduler": scheduler,
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": filename_prefix, "images": ["8", 0]},
        },
    }
