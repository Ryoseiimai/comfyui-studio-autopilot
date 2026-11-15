"""SDXL txt2img の ComfyUI API形式ワークフローを組み立てる純粋関数（標準ノードのみ）。"""


def build_sdxl_txt2img_workflow(prompt, negative="", ckpt_name="sd_xl_base_1.0.safetensors",
                                width=1024, height=1024, steps=25, cfg=7.0, seed=0):
    if not prompt or not prompt.strip():
        raise ValueError("prompt is empty")
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt_name}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
            "latent_image": ["4", 0], "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "studio"}},
    }
