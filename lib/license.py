"""商用利用可否の判定（4区分）。

区分: 「商用可」/「商用不可」/「有料ライセンスで可」/「要確認」
本人ルール: 商用利用はライセンスで許可されたものだけ。有料ライセンスで可になるなら使う時に買う。

判定の入口:
- `classify_license_id(license_id)` … ライセンス識別子（cardData.license や tags の
  "license:xxx" から取り出した文字列）を4区分に純粋変換する（ネットワークなし・テスト対象）。
- `resolve_hf_license(repo_id)` … HF API から cardData.license / tags を取得して判定する。
  license が無い/other のときは cardData.base_model（派生モデル）を最大2段まで辿り、
  元モデルのライセンスを継承して「元モデル基準: <ライセンスID>」として返す（ネットワークあり）。

出自: `~/dev/2026-09-25-x-model-harvester/lib/license.py` を移植（判定ロジックは同一）。
このrepo（ops/executor.py の hf_fetch）は「商用可」「有料ライセンスで可」以外を拒否する
ゲートとして使う。harvesterと違い、Civitai対応（classify_civitai_commercial_use）は
このスタジオでは使わない可能性が高いが、移植元との差分を減らすため残してある。
"""
from __future__ import annotations

import requests

HF_API_BASE = "https://huggingface.co/api/models"
MAX_BASE_MODEL_HOPS = 2

CATEGORY_OK = "商用可"
CATEGORY_NG = "商用不可"
CATEGORY_PAID = "有料ライセンスで可"
CATEGORY_UNKNOWN = "要確認"

# そのまま商用可（追加の注記なし）
COMMERCIAL_OK_PLAIN = {
    "apache-2.0",
    "mit",
    "bsd",
    "bsd-2-clause",
    "bsd-3-clause",
    "cc-by-4.0",
    "cc0-1.0",
    "cc0",
}

# openrail系は「利用制限条項あり」の注記付きで商用可扱い
OPENRAIL_LICENSES = {
    "openrail",
    "openrail++",
    "creativeml-openrail-m",
    "bigscience-openrail-m",
    "bigscience-bloom-rail-1.0",
}

# 明確に商用不可（部分一致で判定するキーワード）
NON_COMMERCIAL_MARKERS = ("cc-by-nc", "non-commercial", "noncommercial")

# 有料ライセンスで可（購入先URL付き）
PAID_LICENSES = {
    "flux-1-dev-non-commercial-license": "https://bfl.ai/licensing",
}

# 条件付き商用可（注記付きで商用可扱い）
CONDITIONAL_OK = {
    "stabilityai-ai-community": "条件付き商用可（年商$1M未満）",
}


def classify_license_id(license_id: str | None) -> dict:
    """ライセンス識別子1つを4区分に変換する（純粋関数・ネットワークなし）。

    戻り値: {"category": str, "basis": str, "note": str | None}
    """
    if not license_id:
        return {"category": CATEGORY_UNKNOWN, "basis": "-", "note": None}

    lower = license_id.strip().lower()

    if lower in PAID_LICENSES:
        return {
            "category": CATEGORY_PAID,
            "basis": license_id,
            "note": f"購入先: {PAID_LICENSES[lower]}",
        }

    if lower in CONDITIONAL_OK:
        return {"category": CATEGORY_OK, "basis": license_id, "note": CONDITIONAL_OK[lower]}

    if lower in OPENRAIL_LICENSES:
        return {"category": CATEGORY_OK, "basis": license_id, "note": "利用制限条項あり（用途制限に注意）"}

    if lower in COMMERCIAL_OK_PLAIN:
        return {"category": CATEGORY_OK, "basis": license_id, "note": None}

    if any(marker in lower for marker in NON_COMMERCIAL_MARKERS):
        return {"category": CATEGORY_NG, "basis": license_id, "note": None}

    if lower in ("other", "unknown", "unlicense-unknown"):
        return {"category": CATEGORY_UNKNOWN, "basis": license_id, "note": None}

    return {"category": CATEGORY_UNKNOWN, "basis": license_id, "note": "未知のライセンス識別子"}


def _extract_license_id(data: dict) -> str | None:
    """HF APIレスポンスから license 識別子を取り出す（cardData優先、次にtags）。"""
    card_data = data.get("cardData") or {}
    license_id = card_data.get("license")
    if license_id:
        return license_id
    for tag in data.get("tags", []) or []:
        if isinstance(tag, str) and tag.startswith("license:"):
            return tag.split(":", 1)[1]
    return None


def _extract_base_models(data: dict) -> list[str]:
    """cardData.base_model（str または list）を正規化してrepo_idのリストで返す。"""
    card_data = data.get("cardData") or {}
    base_model = card_data.get("base_model")
    if not base_model:
        return []
    if isinstance(base_model, str):
        return [base_model]
    if isinstance(base_model, list):
        return [b for b in base_model if isinstance(b, str)]
    return []


def resolve_hf_license(repo_id: str) -> dict:
    """HF repoの商用利用可否を判定する（ネットワークあり）。

    license が無い/other の場合は base_model を最大 MAX_BASE_MODEL_HOPS 段まで辿り、
    元モデルのライセンスを「元モデル基準: <ライセンスID>」として返す。
    どこにも辿り着けなければ「要確認」。
    """
    current_repo_id = repo_id
    for hop in range(MAX_BASE_MODEL_HOPS + 1):
        try:
            resp = requests.get(f"{HF_API_BASE}/{current_repo_id}", timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException:
            return {"category": CATEGORY_UNKNOWN, "basis": "-", "note": "HF API取得失敗"}

        license_id = _extract_license_id(data)
        if license_id and license_id.strip().lower() not in ("other", "unknown"):
            result = classify_license_id(license_id)
            if hop > 0:
                result["basis"] = f"元モデル基準: {result['basis']}（{current_repo_id}）"
            return result

        if hop >= MAX_BASE_MODEL_HOPS:
            break

        base_models = _extract_base_models(data)
        if not base_models:
            break
        current_repo_id = base_models[0]

    return {"category": CATEGORY_UNKNOWN, "basis": "-", "note": None}


def classify_civitai_commercial_use(allow_commercial_use) -> dict:
    """Civitaiの allowCommercialUse から4区分を判定する（純粋関数）。

    allowCommercialUse は Civitai API では文字列配列（例: ["Image","Sell"]）または
    真偽値で返ってくることがある。空/Noneは商用不可、何らかの許可種別が入っていれば商用可、
    型が想定外なら要確認。
    """
    if allow_commercial_use is None:
        return {"category": CATEGORY_UNKNOWN, "basis": "-", "note": None}
    if isinstance(allow_commercial_use, bool):
        category = CATEGORY_OK if allow_commercial_use else CATEGORY_NG
        return {"category": category, "basis": "allowCommercialUse", "note": None}
    if isinstance(allow_commercial_use, list):
        if len(allow_commercial_use) == 0:
            return {"category": CATEGORY_NG, "basis": "allowCommercialUse", "note": None}
        return {
            "category": CATEGORY_OK,
            "basis": f"allowCommercialUse: {', '.join(allow_commercial_use)}",
            "note": None,
        }
    return {"category": CATEGORY_UNKNOWN, "basis": "-", "note": "想定外のallowCommercialUse形式"}
