"""lib.license の単体テスト（ネットワークなし・純粋ロジック部分のみ）。

x-model-harvester (`~/dev/2026-09-25-x-model-harvester/tests/test_license.py`) の
移植元と同じテスト内容（判定ロジックが同一のため）。
"""
from __future__ import annotations

from lib.license import (
    CATEGORY_NG,
    CATEGORY_OK,
    CATEGORY_PAID,
    CATEGORY_UNKNOWN,
    classify_civitai_commercial_use,
    classify_license_id,
)


def test_apache_is_commercial_ok():
    result = classify_license_id("apache-2.0")
    assert result["category"] == CATEGORY_OK
    assert result["note"] is None


def test_mit_is_commercial_ok():
    assert classify_license_id("mit")["category"] == CATEGORY_OK


def test_cc0_is_commercial_ok():
    assert classify_license_id("cc0")["category"] == CATEGORY_OK


def test_cc_by_4_is_commercial_ok():
    assert classify_license_id("cc-by-4.0")["category"] == CATEGORY_OK


def test_openrail_is_ok_with_note():
    result = classify_license_id("creativeml-openrail-m")
    assert result["category"] == CATEGORY_OK
    assert "制限" in result["note"]


def test_cc_by_nc_is_non_commercial():
    assert classify_license_id("cc-by-nc-4.0")["category"] == CATEGORY_NG


def test_non_commercial_keyword_is_non_commercial():
    assert classify_license_id("some-non-commercial-license")["category"] == CATEGORY_NG


def test_flux_dev_non_commercial_is_paid():
    result = classify_license_id("flux-1-dev-non-commercial-license")
    assert result["category"] == CATEGORY_PAID
    assert result["note"] == "購入先: https://bfl.ai/licensing"


def test_stabilityai_community_is_conditional_ok():
    result = classify_license_id("stabilityai-ai-community")
    assert result["category"] == CATEGORY_OK
    assert "年商" in result["note"]


def test_other_is_unknown():
    assert classify_license_id("other")["category"] == CATEGORY_UNKNOWN


def test_none_is_unknown():
    assert classify_license_id(None)["category"] == CATEGORY_UNKNOWN


def test_unknown_id_is_unknown_with_note():
    result = classify_license_id("some-brand-new-license-nobody-knows")
    assert result["category"] == CATEGORY_UNKNOWN
    assert result["note"] == "未知のライセンス識別子"


def test_civitai_allow_commercial_use_list_ok():
    result = classify_civitai_commercial_use(["Image", "Sell"])
    assert result["category"] == CATEGORY_OK


def test_civitai_allow_commercial_use_empty_list_ng():
    assert classify_civitai_commercial_use([])["category"] == CATEGORY_NG


def test_civitai_allow_commercial_use_none_unknown():
    assert classify_civitai_commercial_use(None)["category"] == CATEGORY_UNKNOWN


def test_civitai_allow_commercial_use_bool_true_ok():
    assert classify_civitai_commercial_use(True)["category"] == CATEGORY_OK


def test_civitai_allow_commercial_use_bool_false_ng():
    assert classify_civitai_commercial_use(False)["category"] == CATEGORY_NG
