"""ComfyUI API形式ワークフローを組み立てる純粋関数（標準ノードのみ・ネットワークなし）。"""
from __future__ import annotations

DEFAULT_CKPT = "sd_xl_base_1.0.safetensors"  # openrail++（商用可）


def build_sdxl_txt2img_workflow(
    prompt: str,
    negative: str = "",
    *,
    ckpt_name: str = DEFAULT_CKPT,
    width: int = 1024,
    height: int = 1024,
    steps: int = 25,
    cfg: float = 7.0,
    seed: int = 0,
    filename_prefix: str = "studio",
) -> dict:
    if not prompt or not prompt.strip():
        raise ValueError("prompt is empty")
    if width % 8 or height % 8 or width <= 0 or height <= 0:
        raise ValueError("width/height must be positive multiples of 8")
    if steps < 1:
        raise ValueError("steps must be >= 1")
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt_name}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1}},
        "5": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                         "latent_image": ["4", 0], "seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage",
              "inputs": {"images": ["6", 0], "filename_prefix": filename_prefix}},
    }
