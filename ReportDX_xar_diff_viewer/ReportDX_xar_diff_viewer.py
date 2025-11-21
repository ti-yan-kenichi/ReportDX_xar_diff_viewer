
import io
import zipfile
import json
import difflib
from typing import Any, Dict, List, Tuple

import streamlit as st
import pandas as pd

st.set_page_config(page_title="帳票DX テンプレート差分ビューア（MD & Excelレポート版）", layout="wide")

st.title("📄 帳票DX テンプレート差分ビューア（MD & Excelレポート版）")
st.write(
    "オプロの帳票DXテンプレート（.xar）ファイル同士の差分を、できるだけ詳細に比較し、MarkdownレポートとExcelレポートをダウンロードできます。"
)

# --- ファイルアップロード UI -------------------------------------------------

col1, col2 = st.columns(2)
with col1:
    old_file = st.file_uploader("旧テンプレート (.xar)", type=["xar"], key="old")
with col2:
    new_file = st.file_uploader("新テンプレート (.xar)", type=["xar"], key="new")


# --- ユーティリティ ----------------------------------------------------------


def load_xar_from_bytes(bytes_data: bytes) -> Tuple[Dict[str, Any], str]:
    # Uploadされた .xar (ZIP) から .xat JSON と元テキストを返す
    with zipfile.ZipFile(io.BytesIO(bytes_data)) as z:
        xat_name = None
        for name in z.namelist():
            if name.lower().endswith(".xat"):
                xat_name = name
                break
        if not xat_name:
            raise ValueError(".xar 内に .xat ファイルが見つかりませんでした。")
        data = z.read(xat_name)
        txt = data.decode("utf-8")
        return json.loads(txt), txt


def index_objects(tpl_json: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    # objects配列をidで引けるdictに変換
    return {
        o.get("id"): o
        for o in tpl_json.get("objects", [])
        if o.get("id") is not None
    }


def summarize_object(o: Dict[str, Any]) -> Dict[str, Any]:
    # オブジェクトの概略を取り出す（一覧表示用）
    impl_uri = o.get("impl_uri")
    rect = o.get("rect", {}) or {}
    base = {
        "id": o.get("id"),
        "name": o.get("name"),
        "type": impl_uri,
        "x": rect.get("x"),
        "y": rect.get("y"),
        "width": rect.get("width"),
        "height": rect.get("height"),
        "show": o.get("show"),
        "lock": o.get("lock"),
        "enabled": o.get("enabled"),
    }

    impl = o.get("impl", {}) or {}

    if impl_uri == "oxa:text":
        data = impl.get("data", {}) or {}
        font = impl.get("font", {}) or {}
        base.update(
            {
                "kind": "text",
                "text": data.get("value"),
                "font_name": font.get("name"),
                "font_size": font.get("size"),
                "font_color": font.get("color"),
                "align": font.get("align"),
            }
        )
    elif impl_uri == "oxa:rect":
        stroke = impl.get("stroke", {}) or {}
        fill = stroke.get("fill", {}) or {}
        base.update(
            {
                "kind": "rect",
                "stroke_size": stroke.get("size"),
                "stroke_color": fill.get("color"),
            }
        )
    elif impl_uri == "oxa:tableregion":
        tables = impl.get("tables", []) or []
        table = tables[0] if tables else {}
        drive_ds = table.get("drive_dataset", {}) or {}
        details = table.get("details", []) or []
        col_count = 0
        if details:
            first_detail = details[0]
            frames = first_detail.get("frames", []) or []
            col_count = len(frames)
        base.update(
            {
                "kind": "tableregion",
                "dataset_ref": drive_ds.get("ref"),
                "column_count": col_count,
            }
        )
    else:
        base.update({"kind": "other"})

    return base


def deep_diff(a: Any, b: Any, path: str = "") -> List[Dict[str, Any]]:
    # JSONの一部（dict/list/値）同士を比較して、差分のリストを返す。
    # 各要素は {path, old, new} を持つ。
    diffs: List[Dict[str, Any]] = []

    # 型が違う場合は即差分
    if type(a) is not type(b):
        if a != b:
            diffs.append({"path": path or "(root)", "old": a, "new": b})
        return diffs

    # dict
    if isinstance(a, dict):
        keys = set(a.keys()) | set(b.keys())
        for k in sorted(keys):
            sub_path = f"{path}.{k}" if path else k
            if k not in a:
                diffs.append({"path": sub_path, "old": None, "new": b.get(k)})
            elif k not in b:
                diffs.append({"path": sub_path, "old": a.get(k), "new": None})
            else:
                diffs.extend(deep_diff(a.get(k), b.get(k), sub_path))
        return diffs

    # list
    if isinstance(a, list):
        max_len = max(len(a), len(b))
        for i in range(max_len):
            sub_path = f"{path}[{i}]"
            if i >= len(a):
                diffs.append({"path": sub_path, "old": None, "new": b[i]})
            elif i >= len(b):
                diffs.append({"path": sub_path, "old": a[i], "new": None})
            else:
                diffs.extend(deep_diff(a[i], b[i], sub_path))
        return diffs

    # 値
    if a != b:
        diffs.append({"path": path or "(root)", "old": a, "new": b})
    return diffs


def classify_severity(path: str) -> Tuple[int, str, str]:
    # 差分パスに基づいて重要度を判定する。
    # 戻り値: (severity, emoji, label)  / severity: 3=Critical, 2=Medium, 1=Minor
    p = path.lower()

    # 重大：データバインドやタイプ、列数など
    critical_keywords = [
        "drive_dataset",
        "dataset_ref",
        "dataset",
        "bind",
        "impl_uri",
        "column_count",
        ".tables",
        "image",
        "img",
        "resource",
    ]
    if any(k in p for k in critical_keywords):
        return 3, "🔴", "重大"

    # 中程度：レイアウト・スタイル・フォントサイズなど
    medium_keywords = [
        "rect.",
        ".rect",
        "stroke",
        "font_size",
        "font.size",
        "fill.color",
        "fill_colour",
        "alignment",
        "align",
        "width",
        "height",
        "x",
        "y",
        "rotation",
        "skew",
    ]
    if any(k in p for k in medium_keywords):
        return 2, "🟡", "中"

    # テキスト変更は中〜重大とも考えられるが、ここでは中に寄せる
    if "impl.data.value" in p or "text" in p:
        return 2, "🟡", "中"

    # それ以外は軽微
    return 1, "🟢", "軽微"


def html_colored_change(path: str, old: Any, new: Any) -> str:
    # 差分1件をHTML（色付き）で表現する
    severity, emoji, label = classify_severity(path)
    if severity == 3:
        color = "red"
    elif severity == 2:
        color = "orange"
    else:
        color = "green"

    old_str = json.dumps(old, ensure_ascii=False)
    new_str = json.dumps(new, ensure_ascii=False)

    return (
        f'<div style="margin-bottom:4px;">'
        f'<span style="color:{color}; font-weight:bold;">{emoji} [{label}]</span> '
        f'<code>{path}</code><br>'
        f'<span style="color:{color};">旧: {old_str}</span><br>'
        f'<span style="color:{color};">新: {new_str}</span>'
        f"</div>"
    )


def build_markdown_report(
    old_name: str,
    new_name: str,
    added: List[Dict[str, Any]],
    removed: List[Dict[str, Any]],
    changed_rows: List[Dict[str, Any]],
    changed_detail: Dict[str, Any],
) -> str:
    # Markdownレポートを生成する
    lines: List[str] = []
    lines.append("# 帳票DX テンプレート差分レポート")
    lines.append("")
    lines.append(f"- 旧テンプレート: `{old_name}`")
    lines.append(f"- 新テンプレート: `{new_name}`")
    lines.append("")

    total_critical = sum(r["critical_cnt"] for r in changed_rows)
    total_medium = sum(r["medium_cnt"] for r in changed_rows)
    total_minor = sum(r["minor_cnt"] for r in changed_rows)

    lines.append("## サマリー")
    lines.append("")
    lines.append(f"- 追加オブジェクト数: **{len(added)}**")
    lines.append(f"- 削除オブジェクト数: **{len(removed)}**")
    lines.append(f"- 変更オブジェクト数: **{len(changed_rows)}**")
    lines.append(f"- 重大変更(🔴): **{total_critical}**")
    lines.append(f"- 中変更(🟡): **{total_medium}**")
    lines.append(f"- 軽微変更(🟢): **{total_minor}**")
    lines.append("")

    lines.append("## 追加されたオブジェクト")
    lines.append("")
    if not added:
        lines.append("- なし")
    else:
        lines.append("| id | name | kind | type | x | y | width | height |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for o in added:
            lines.append(
                f"| `{o.get('id')}` | {o.get('name','')} | {o.get('kind','')} | "
                f"{o.get('type','')} | {o.get('x','')} | {o.get('y','')} | "
                f"{o.get('width','')} | {o.get('height','')} |"
            )
    lines.append("")

    lines.append("## 削除されたオブジェクト")
    lines.append("")
    if not removed:
        lines.append("- なし")
    else:
        lines.append("| id | name | kind | type | x | y | width | height |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for o in removed:
            lines.append(
                f"| `{o.get('id')}` | {o.get('name','')} | {o.get('kind','')} | "
                f"{o.get('type','')} | {o.get('x','')} | {o.get('y','')} | "
                f"{o.get('width','')} | {o.get('height','')} |"
            )
    lines.append("")

    lines.append("## 変更されたオブジェクト詳細")
    lines.append("")
    if not changed_rows:
        lines.append("- なし")
    else:
        for row in changed_rows:
            oid = row["id"]
            det = changed_detail[oid]
            lines.append(f"### オブジェクト `{oid}`")
            lines.append("")
            lines.append(
                f"- kind/type: `{row.get('kind')}` / `{row.get('type')}`"
            )
            lines.append(
                f"- name: `{row.get('name_old')}` → `{row.get('name_new')}`"
            )
            lines.append(
                f"- 変更件数: 重大={row.get('critical_cnt')} / 中={row.get('medium_cnt')} / 軽微={row.get('minor_cnt')}"
            )
            lines.append("")
            lines.append("#### 差分一覧")
            lines.append("")

            diffs = det["diffs"]
            decorated: List[Tuple[int, str, str, Any, Any]] = []
            for d in diffs:
                severity, emoji, label = classify_severity(d["path"])
                decorated.append(
                    (severity, emoji, label, d["path"], d["old"], d["new"])
                )
            decorated.sort(key=lambda x: (-x[0], x[3]))

            lines.append("| 重要度 | パス | 旧値 | 新値 |")
            lines.append("| --- | --- | --- | --- |")
            for severity, emoji, label, path, old, new in decorated:
                old_str = json.dumps(old, ensure_ascii=False)
                new_str = json.dumps(new, ensure_ascii=False)
                lines.append(
                    f"| {emoji} {label} | `{path}` | `{old_str}` | `{new_str}` |"
                )
            lines.append("")

    return "\n".join(lines)


def build_excel_report(
    added: List[Dict[str, Any]],
    removed: List[Dict[str, Any]],
    changed_rows: List[Dict[str, Any]],
    changed_detail: Dict[str, Any],
) -> bytes:
    # Excelレポート（複数シート）を生成
    with io.BytesIO() as buffer:
        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            # Added / Removed / Changed summary
            if added:
                df_added = pd.DataFrame(added)
                df_added.to_excel(writer, sheet_name="Added", index=False)
            else:
                pd.DataFrame(columns=["id", "name"]).to_excel(
                    writer, sheet_name="Added", index=False
                )

            if removed:
                df_removed = pd.DataFrame(removed)
                df_removed.to_excel(writer, sheet_name="Removed", index=False)
            else:
                pd.DataFrame(columns=["id", "name"]).to_excel(
                    writer, sheet_name="Removed", index=False
                )

            if changed_rows:
                df_changed = pd.DataFrame(changed_rows)
                df_changed.to_excel(writer, sheet_name="ChangedSummary", index=False)
            else:
                pd.DataFrame(columns=["id", "name"]).to_excel(
                    writer, sheet_name="ChangedSummary", index=False
                )

            # Changed details (flattened)
            detail_rows: List[Dict[str, Any]] = []
            for row in changed_rows:
                oid = row["id"]
                det = changed_detail[oid]
                diffs = det["diffs"]
                for d in diffs:
                    sev, emoji, label = classify_severity(d["path"])
                    detail_rows.append(
                        {
                            "id": oid,
                            "name_old": row.get("name_old"),
                            "name_new": row.get("name_new"),
                            "kind": row.get("kind"),
                            "type": row.get("type"),
                            "severity": sev,
                            "level": label,
                            "emoji": emoji,
                            "path": d["path"],
                            "old": json.dumps(d["old"], ensure_ascii=False),
                            "new": json.dumps(d["new"], ensure_ascii=False),
                        }
                    )

            if detail_rows:
                df_detail = pd.DataFrame(detail_rows)
            else:
                df_detail = pd.DataFrame(
                    columns=[
                        "id",
                        "name_old",
                        "name_new",
                        "kind",
                        "type",
                        "severity",
                        "level",
                        "emoji",
                        "path",
                        "old",
                        "new",
                    ]
                )
            df_detail.to_excel(writer, sheet_name="ChangedDetails", index=False)

        return buffer.getvalue()


# --- メイン処理 --------------------------------------------------------------

if old_file is not None and new_file is not None:
    try:
        old_bytes = old_file.read()
        new_bytes = new_file.read()
        tpl_old, txt_old = load_xar_from_bytes(old_bytes)
        tpl_new, txt_new = load_xar_from_bytes(new_bytes)
    except Exception as e:
        st.error(f".xar の読み込みに失敗しました: {e}")
    else:
        idx_old = index_objects(tpl_old)
        idx_new = index_objects(tpl_new)

        ids_old = set(idx_old.keys())
        ids_new = set(idx_new.keys())

        added_ids = ids_new - ids_old
        removed_ids = ids_old - ids_new
        common_ids = ids_old & ids_new

        # サマリー用データ作成
        added = [summarize_object(idx_new[i]) for i in sorted(added_ids)]
        removed = [summarize_object(idx_old[i]) for i in sorted(removed_ids)]

        changed_rows: List[Dict[str, Any]] = []
        changed_detail: Dict[str, Any] = {}

        for oid in sorted(common_ids):
            o_old = idx_old[oid]
            o_new = idx_new[oid]
            sa = summarize_object(o_old)
            sb = summarize_object(o_new)

            # オブジェクト全体のdeep diff（rect/implなどすべて含む）
            obj_diffs = deep_diff(o_old, o_new, path="object")

            if obj_diffs:
                # 重要度ごとにカウント
                sev_counts = {1: 0, 2: 0, 3: 0}
                for d in obj_diffs:
                    severity, _emoji, _label = classify_severity(d["path"])
                    sev_counts[severity] += 1

                changed_rows.append(
                    {
                        "id": oid,
                        "name_old": sa.get("name"),
                        "name_new": sb.get("name"),
                        "kind": sa.get("kind"),
                        "type": sa.get("type"),
                        "minor_cnt": sev_counts[1],
                        "medium_cnt": sev_counts[2],
                        "critical_cnt": sev_counts[3],
                        "total_changes": sum(sev_counts.values()),
                    }
                )
                changed_detail[oid] = {
                    "old_summary": sa,
                    "new_summary": sb,
                    "old_full": o_old,
                    "new_full": o_new,
                    "diffs": obj_diffs,
                }

        st.subheader("差分サマリー")

        total_critical = sum(r["critical_cnt"] for r in changed_rows)
        total_medium = sum(r["medium_cnt"] for r in changed_rows)
        total_minor = sum(r["minor_cnt"] for r in changed_rows)

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("追加オブジェクト", len(added_ids))
        c2.metric("削除オブジェクト", len(removed_ids))
        c3.metric("変更オブジェクト", len(changed_rows))
        c4.metric("重大変更(🔴)", total_critical)
        c5.metric("中変更(🟡) / 軽微(🟢)", f"{total_medium} / {total_minor}")

        # レポート生成＆ダウンロードボタン
        st.markdown("### 📥 差分レポートのダウンロード")

        md_report = build_markdown_report(
            old_name=getattr(old_file, "name", "old.xar"),
            new_name=getattr(new_file, "name", "new.xar"),
            added=added,
            removed=removed,
            changed_rows=changed_rows,
            changed_detail=changed_detail,
        )

        st.download_button(
            label="Markdownレポート（.md）をダウンロード",
            data=md_report.encode("utf-8"),
            file_name="xar_diff_report.md",
            mime="text/markdown",
        )

        excel_bytes = build_excel_report(
            added=added,
            removed=removed,
            changed_rows=changed_rows,
            changed_detail=changed_detail,
        )

        st.download_button(
            label="Excelレポート（.xlsx）をダウンロード",
            data=excel_bytes,
            file_name="xar_diff_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        st.markdown("---")

        # 追加・削除・変更ごとのタブ + JSON diffタブ
        tab1, tab2, tab3, tab4 = st.tabs(
            ["➕ 追加", "➖ 削除", "✏️ 変更（色分け付き）", "🧾 JSONテキスト差分"]
        )

        with tab1:
            st.markdown("### 追加されたオブジェクト")
            if not added:
                st.info("追加されたオブジェクトはありません。")
            else:
                st.dataframe(added, use_container_width=True)

        with tab2:
            st.markdown("### 削除されたオブジェクト")
            if not removed:
                st.info("削除されたオブジェクトはありません。")
            else:
                st.dataframe(removed, use_container_width=True)

        with tab3:
            st.markdown("### 変更されたオブジェクト一覧")
            if not changed_rows:
                st.info("変更されたオブジェクトはありません。")
            else:
                st.dataframe(changed_rows, use_container_width=True)

                st.markdown("#### オブジェクト別の詳細差分")

                selected_id = st.selectbox(
                    "オブジェクトIDを選択", [row["id"] for row in changed_rows]
                )
                detail = changed_detail[selected_id]

                st.write(f"**ID:** `{selected_id}`")
                st.write(
                    f"**旧name:** {detail['old_summary'].get('name')} / "
                    f"**新name:** {detail['new_summary'].get('name')}"
                )
                st.write(
                    f"**kind/type:** {detail['old_summary'].get('kind')} / "
                    f"{detail['old_summary'].get('type')}"
                )

                # 重要度ごとにソートして表示（重大 → 中 → 軽微）
                diffs = detail["diffs"]
                diffs_with_sev = []
                for d in diffs:
                    severity, emoji, label = classify_severity(d["path"])
                    diffs_with_sev.append(
                        {
                            "severity": severity,
                            "emoji": emoji,
                            "label": label,
                            "path": d["path"],
                            "old": d["old"],
                            "new": d["new"],
                        }
                    )

                diffs_with_sev.sort(
                    key=lambda x: (-x["severity"], x["path"])
                )  # 重大から

                st.markdown("##### 差分一覧（色分け）")

                if not diffs_with_sev:
                    st.write("このオブジェクトには差分がありません。")
                else:
                    html_blocks = [
                        html_colored_change(
                            d["path"],
                            d["old"],
                            d["new"],
                        )
                        for d in diffs_with_sev
                    ]
                    st.markdown(
                        "\n".join(html_blocks),
                        unsafe_allow_html=True,
                    )

                with st.expander("旧オブジェクト（JSON）"):
                    st.json(detail["old_full"])
                with st.expander("新オブジェクト（JSON）"):
                    st.json(detail["new_full"])

        with tab4:
            st.markdown("### JSON テキストの完全 diff")
            diff_lines = difflib.unified_diff(
                txt_old.splitlines(),
                txt_new.splitlines(),
                fromfile="old.xat",
                tofile="new.xat",
                lineterm="",
            )
            diff_text = "\n".join(diff_lines)
            st.code(diff_text or "差分はありませんでした。", language="diff")

else:
    st.info("左に旧テンプレート、右に新テンプレートの .xar ファイルを指定してください。")
