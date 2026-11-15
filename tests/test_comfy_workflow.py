import pytest
from lib.comfy_workflow import build_sdxl_txt2img_workflow as b


def test_graph_links_valid():
    w = b("a quiet forest")
    for n in w.values():
        for v in n["inputs"].values():
            if isinstance(v, list):
                assert v[0] in w
    assert w["2"]["inputs"]["text"] == "a quiet forest"
    assert w["1"]["inputs"]["ckpt_name"] == "sd_xl_base_1.0.safetensors"


def test_empty_prompt():
    with pytest.raises(ValueError):
        b("  ")
