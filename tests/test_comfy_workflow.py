import pytest
from lib.comfy_workflow import build_sdxl_txt2img_workflow as b


def test_graph_links_valid():
    wf = b("a calm lake", "text")
    for node in wf.values():
        for v in node["inputs"].values():
            if isinstance(v, list):
                assert v[0] in wf
    assert wf["1"]["inputs"]["ckpt_name"] == "sd_xl_base_1.0.safetensors"
    assert wf["7"]["class_type"] == "SaveImage"


def test_params():
    wf = b("x", width=768, height=512, seed=7, steps=10)
    assert wf["4"]["inputs"]["width"] == 768 and wf["5"]["inputs"]["seed"] == 7


@pytest.mark.parametrize("kw", [{"prompt": " "}, {"prompt": "x", "width": 100}, {"prompt": "x", "steps": 0}])
def test_invalid(kw):
    with pytest.raises(ValueError):
        b(**kw)
