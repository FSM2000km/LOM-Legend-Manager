from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "tags_catalog.json"
OUTPUT_PATH = ROOT / "TAGS.md"


def main() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8-sig"))
    category_labels = {item["id"]: item["label"] for item in catalog["categories"]}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for tag in catalog["tags"]:
        grouped[tag["category"]].append(tag)

    lines = [
        "# タグ一覧",
        "",
        f"プリセット: `{catalog['preset_version']}`",
        f"有効タグ: `{len(catalog['tags'])}`件",
        "",
        "ED名はゲーム内IDまたは手動確定から付与します。結縁相手は伝説に実際に保存された成立済みStory keyから判定し、想い人IDからは推測しません。生存、唐門加入、金烏討伐成功だけを通常の追加候補に表示し、その他のルート候補は`ネタバレタグを追加`を押すまで隠します。自動判定は、伝説に実際に保存されたStory keyと完全一致した肯定条件だけを使います。",
        "",
    ]

    for category in catalog["categories"]:
        category_id = category["id"]
        if category_id == "manual" or category_id not in grouped:
            continue
        tags = sorted(grouped[category_id], key=lambda item: (item["order"], item["label"]))
        lines.extend((f"## {category_labels[category_id]} ({len(tags)}件)", ""))
        for tag in tags:
            visibility = "通常候補" if tag["default_visible"] else "明示操作後"
            if category_id in ("ending", "heroine"):
                visibility = "確定情報"
            rule = ""
            if tag.get("story_keys_any"):
                rule = " / Story key: " + ", ".join(f"`{key}`" for key in tag["story_keys_any"])
            lines.append(f"- `{tag['label']}` ({visibility}){rule}")
        lines.append("")

    lines.extend(("## システム状態", ""))
    lines.extend(f"- `{label}`" for label in catalog["system_states"])
    lines.extend(
        (
            "",
            "これらはED・結縁・品質状態であり、自由タグとしては扱いません。",
            "",
            "## 将来の死亡タグ",
            "",
            "死亡エクスポートは初期版の対象外です。次は将来用候補であり、現在のDB・UIには登録しません。",
            "",
        )
    )
    lines.extend(f"- `{label}`" for label in catalog["future_death_tags"])
    lines.append("")

    OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"Generated {OUTPUT_PATH} ({len(catalog['tags'])} active tags)")


if __name__ == "__main__":
    main()
