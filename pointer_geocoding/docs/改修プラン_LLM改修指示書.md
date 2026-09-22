# PointerGeocoding プラグイン LLM改修指示書

## 0. メタ指示 & LLM実行コンテキスト (Meta Instructions for LLM)

> **[LLMへのロール定義と行動規範]**
> あなたはQGIS Pythonプラグイン（`PointerGeocoding`）のリファクタリングを完璧に遂行する **Senior Python/QGIS Architect LLM** です。
> 本ドキュメントは、既存のPointerGeocodingプラグインのアーキテクチャを「イベントコントローラー化および単一方向データフロー（Unidirectional Data Flow）」へ移行改修するための設計書です。
> 以下の指示、アーキテクチャ設計、ガードレール、およびステップ別タスクに従い、コードの生成・改修を実行してください。
> 改修前のプラグインコードは、接続しているNotebookのソースの中にディレクトリ名.txtの形でコンテナ化されて配置されています。ただし、既存ファイルを改修する際は、各stepの冒頭で**必ずユーザーに改修前のコードの提示を求めてください**。
> 不足情報は必ずユーザーに質問して確認し、設計書の内容とユーザーの要望に齟齬が認められる場合は、対話により意見のすり合わせと設計内容の柔軟な変更を許可します。

### 【LLMコード生成の絶対原則】
1. **既存機能の完全維持 (Regression-Free)**: リファクタリングによってユーザー操作、既存データ形式（GeoPackage / CSV / WorldFile）、QGISキャンバス描画の挙動を変えてはならない。
2. **不変ルールの厳格遵守**: 第4章の `[RULE-GEO-01]` 〜 `[RULE-DOMAIN-06]` に違反するコード生成を絶対禁止とする。
3. **段階的実行とセルフチェック**: 指示されたPhase/Stepの順序に従い、ステップごとに完成条件（Definition of Done）を満たしているか確認しながらコードを出力すること。

---

## 1. 全体アーキテクチャとデータフロー (Architecture & Data Flow)

本改修では、システム全体を **View (`src/ui/`)**、**Event Layer / Orchestration (`src/uilogic/`)**、**Domain Logic / Layer (`src/logic/` & `src/layer/`)**、および **Core UI Framework (`src/ui/core/`)** の4層構造に厳格分離します。

### ■ データフロー構造図
```
 [ View (src/ui/) ]
       │ 1. ユーザー操作の検知 ➔ UIAction 発行
       ▼
 [ EventDispatcher (src/uilogic/dispatcher.py) ] ── (前置検証・ビジー化・例外一括キャッチ)
       │ 2. DTO / 内部表現型パラメータの作成
       ▼
 [ Domain Logic (src/logic/ & src/layer/) ] ── (GUI非依存・純粋計算・データ処理)
       │ 3. 処理結果の返却
       ▼
 [ StateStore (src/ui/core/state.py) ] ── (不変 UIState の更新 & diff 通知)
       │ 4. state_changed シグナル (diff付き)
       ▼
 [ View (src/ui/) ] ── (_on_state_changed による blockSignals 下での差分描画同期)
```

### ■ 各層の責務と境界線

| 層 (Layer)           | 対象ディレクトリ・ファイル                                                                                                                                                                                                                                  | 主な責務と制約                                                                                                                               |
| :------------------ | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------ |
| **View**            | `src/ui/main_dock.py`<br>`src/ui/main_image.py`<br>`src/ui/main_settings.py`<br>`src/ui/main_output.py`<br>`src/ui/dialogs.py`<br>`src/ui/start_dialog.py`                                                                                     | ・`CoreUI` (`PanelSpec`) による宣言的UI構築<br>・ユーザー操作を検知し `UIAction` を発行<br>・`StateStore` の `state_changed` シグナルを受け取り、`blockSignals` 保護下で描画同期 |
| **Event Layer**     | `src/uilogic/dispatcher.py`<br>`src/uilogic/georef_logic.py`<br>`src/uilogic/digitizing_logic.py`<br>`src/uilogic/settings_logic.py`<br>`src/uilogic/output_logic.py`<br>`src/uilogic/dialogs_logic.py`<br>`src/uilogic/start_dialog_logic.py` | ・`UIAction` を受容し、共通前置バリデーション・ビジー制御・横断例外キャッチを実施<br>・UI表示文字列を即時 Enum / DTO へ翻訳し、Domain Layer へ委譲<br>・処理結果を `UIStateStore` へ Dispatch    |
| **Domain Logic**    | `src/logic/core.py`<br>`src/logic/transform.py`<br>`src/layer/manager.py`<br>`src/layer/*.py`                                                                                                                                                  | ・QGISオブジェクト処理、座標変換計算、アフィン変換、ファイルI/O                                                                                                   |
| **Core UI / State** | `src/ui/core/state.py`<br>`src/ui/core/builder.py`<br>`src/ui/core/validators.py`<br>`src/ui/core/field_spec.py`                                                                                                                               | ・アプリケーション状態の不変モデル（`UIState` / SSOT）管理<br>・`UIAction` 定義および `CoreUIBuilder` による宣言的UI構築<br>・無色透明な単体検証クラス（`Validator`）                   |

---

## 2. コア基盤コンポーネント仕様 (Core Infrastructure Specification)

### 2.1 EventDispatcher (src/uilogic/dispatcher.py) 仕様
中央ディスパッチャーを作成し、各 Controller に散在していた「前置バリデーション」「大域ビジー表示」「横断例外キャッチ」「State更新」のパイプラインを一括仲介します。

*   **一元化の適用対象**:
    *   確定したユーザーの意思決定アクション（例: `ExportCsvAction`, `ExecuteTransformAction`, `SaveProjectAction`, `ConfirmGeorefAction` など）。
    *   ドメイン計算例外・ファイルI/O例外の一括キャッチと、`UIState` へのエラーメッセージ反映。
*   **非適用（ローカル受容）対象**:
    *   コンボボックスの選択変更やテキスト入力時のリアルタイムバリデーション、キャンバスのホバー・スナップ等の軽量なUIイベントは、各 Controller / View 内で即時受容して差し支えありません。

### 2.2 画面ロック・ビジー制御の運用方針 (Interaction & Busy Guard Policy)
画面ロックについては、処理の規模と文脈に応じて **「大域ロック (Global Lock)」** と **「局所ガード (Local Guard)」** を使い分け、過度な一元化によるパフォーマンス低下や操作性の不全を防ぎます。

1.  **大域ロック（Global Lock / ディスパッチャー主導）**:
    *   ファイルI/O、重い座標変換計算、セッション読み込み等の非同期/長時間処理で使用します。
    *   `EventDispatcher` パイプライン内で `UIState.is_processing` を `True` に設定し、`main_dock.py` の `_on_state_changed` を介してアプリ全体（カーソルWait化・ドック非活性化・キャンバス操作不可）を一括制御します。
2.  **局所ガード（Local Guard / Controller主導）**:
    *   キャンバス上の単打刻・属性一時反映・シンボロジ更新など、短時間かつ特定の文脈に閉じた連続操作で使用します。
    *   `digitizing_logic.py` 内の `busy_interaction_guard()` コンテキストマネージャーや、`map_tool.set_interaction_locked()` 等の局所制御をそのまま活用し、ディスパッチャーを介さずに同期的に画面・キャンバスを保護することを認めます。

### 2.3 CoreUI 自動バインド機構 (src/ui/core/builder.py)
PanelSpec のイベントフック（on_click, on_change）から UIAction を自動発行し、EventDispatcher または各 Controller のハンドラへ流す `panel.auto_bind(dispatcher, action_mapping)` を実装します。これにより View と Controller 間の巨大な手動コールバック辞書（`bind_view_callbacks`）を廃止し、宣言的なバインドを実現します。

---

## 3. 強行ガードレール & 不変ルール (Guardrails & Code Rules)

コード生成にあたり、以下のルールIDを絶対的に厳守してください。

| ルールID | ドメイン | 概要・実装ルール | 実装コード例 (DO / DON'T) |
| :--- | :--- | :--- | :--- |
| **`[RULE-GEO-01]`** | 座標系境界＆純粋計算 | **【I/O境界でのみ変換・純粋関数化】**<br>内部計算は常に **数学座標系（Canvas X=東西, Canvas Y=南北）** で統一。CSV出力・DelimitedText・UI表示の境界でのみアダプター（`to_survey_coords` / `from_survey_coords`）を通す。<br>(※ **Survey X=南北, Survey Y=東西**。つまり Canvas X = Survey Y, Canvas Y = Survey X)。 | ⭕ **DO**: `sx, sy = to_survey_coords(math_x, math_y)` (I/O境界のみ)<br>❌ **DON'T**: `math_x, math_y = math_y, math_x` (ロジック内部での直接XY手動入替) |
| **`[RULE-UI-02]`** | リアクティブ同期 | **【シグナル遮断の徹底＆逆参照禁止】**<br>View側でウィジェット値をセットする際は、必ず `widget.blockSignals(True/False)` または `suppress_realtime_commit` でシグナルを遮断する。<br>`uilogic` から `ui/main_dock.py` への逆インポートを絶対禁止とする。 | ⭕ **DO**: `widget.blockSignals(True); widget.setText(val); widget.blockSignals(False)`<br>❌ **DON'T**: 遮断なしの `setText()`（無限再帰シグナルループ発生） |
| **`[RULE-TYPE-03]`** | 型・表示分離 | **【即時 Enum/DTO 翻訳】**<br>Viewからの表示用文字列（`"S:石器"`, `"遺構"`, `"UTF-8 (BOM付き)"` 等）は Controller 入入直後に型安全な `StrEnum`（`AttributeType`, `ExcavationType`）や DTO（`PluginSettings` 等）へ即時翻訳する。 | ⭕ **DO**: `attr_enum = AttributeType(combo.currentData())`<br>❌ **DON'T**: `"S:石器"` という表示文字列を `CASE WHEN` 式やデータベースへ流す |
| **`[RULE-LAYER-04]`** | キャッシュ・同期 | **【レイヤ更新ループの集約】**<br>レイヤのジオメトリ・属性更新時は独自ループを書かず、既存の `batch_update_attributes` や統合更新シーケンス（`LayerManager`）を経由する。 | ⭕ **DO**: `batch_update_attributes(layer, updates)`<br>❌ **DON'T**: `for feat in layer.getFeatures(): feat.setAttribute(...)` を個別実装 |
| **`[RULE-PERSIST-05]`** | 永続化・UI制御 | **【一括永続化とUIロック】**<br>データ更新 -> メタデータ保存（`save_image_metadata`） -> ワールドファイル生成（`write_world_file`） -> プロジェクト保存（`QgsProject.write`） -> キャンバス再描画 の一式を `busy_interaction_guard` 保護下で一括実行。 | ⭕ **DO**: 一連の保存シーケンスを単一のアクションハンドラでトランザクション的に完結<br>❌ **DON'T**: UIロックなしに各保存処理を別イベントでバラバラに呼ぶ |
| **`[RULE-DOMAIN-06]`** | ドメイン規則 | **【重複判定と自動採番ルール】**<br>・重複チェック（`check_point_duplicate`）は全図面横断（グローバル一意性）で判定する。<br>・自動採番（`get_next_point_number`）では、手入力対象である `AttributeType.SP` を探索対象から除外する。 | ⭕ **DO**: `check_point_duplicate` は全図面対象。SP属性は採番探索からスキップ<br>❌ **DON'T**: 特定図面内だけで重複判定する。SP属性の点を自動採番計算に含める |

---

## 4. 段階的改修ステップ & タスク指示 (Step-by-Step Execution Plan)

改修は以下の3フェーズ・5ステップで順番に実行してください。各ステップごとにコードを出力し、動作検証を行ってください。

```
┌────────────────────────────────────────────────────────┐
│ Phase 1: イベント層基盤の構築                           │
│  ・Step 1: Core層基盤強化 (UIStateStore, Validation)   │
│  ・Step 2: EventDispatcher 作成 (src/uilogic/dispatcher)│
│  ・Step 3: CoreUIBuilder と auto_bind 統合              │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ Phase 2: 各画面 Controller の段階的アクション移行       │
│  ・Step 4.1: Tab 4 (OUT: output_logic.py)              │
│  ・Step 4.2: Tab 3 (SET: settings_logic.py)            │
│  ・Step 4.3: Tab 1 (IMG: georef_logic.py)              │
│  ・Step 4.4: Tab 2 (PLOT: digitizing_logic.py)         │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│ Phase 3: View層の最適化 & 逆参照の完全クリーンアップ   │
│  ・Step 5: Viewからドメイン知識消去・差分同期テスト     │
└────────────────────────────────────────────────────────┘
```

---

### Phase 1: イベント層基盤の構築 (Step 1 〜 Step 3)

#### ■ Step 1: Core層の基盤強化 (`src/ui/core/`)
* **対象ファイル**: `src/ui/core/state.py`, `src/ui/core/validators.py`
* **指示**:
  1. `UIStateStore` に `EventDispatcher` と連携できるパイプライン用メソッドを追加する。
  2. `ValidationResult` にエラー時のフィールドフォーカス用識別子や詳細メッセージを保持できるよう拡張する。
* **適用ルール**: `[RULE-UI-02]`
* **完了条件 (Definition of Done)**: `UIStateStore` が dispatch 後に不変状態 `UIState` を正しく生成し、`state_changed` シグナルを発行すること。

#### ■ Step 2: `EventDispatcher` の作成 (`src/uilogic/dispatcher.py`)
* **対象ファイル**: `src/uilogic/dispatcher.py` (新規作成)
* **指示**:
  1. 仕様（第2.1節）に基づき `EventDispatcher` クラスを実装する。
  2. `UIAction` タイプごとにハンドラ関数および `Validator` リストを登録できる `register_handler` を実装する。
  3. 前置バリデーション -> ビジーガード -> ハンドラ実行 -> 横断例外キャッチ -> `UIStateStore` への Dispatch パイプラインを完成させる。
* **適用ルール**: `[RULE-PERSIST-05]`
* **完了条件**: アクション発行時に例外が発生した場合でも、UIがロックされたままにならず安全にエラーメッセージが `UIState` へ渡ること。

#### ■ Step 3: `CoreUIBuilder` への `auto_bind` 組み込み (`src/ui/core/builder.py`)
* **対象ファイル**: `src/ui/core/builder.py`
* **指示**:
  1. `BuiltPanel` クラスに `auto_bind(dispatcher, action_mapping)` メソッドを追加する。
  2. ウィジェットのシグナル（`clicked`, `currentIndexChanged` 等）から対応する `UIAction` インスタンスを自動生成し、`dispatcher.dispatch(action)` を呼び出す仕組みを構築する。
* **適用ルール**: `[RULE-UI-02]`
* **完了条件**: View 側で手動の `bind_view_callbacks` 辞書を作成せずにUIイベントを Dispatcher へ送信できること。

---

### Phase 2: 画面（Tab）ごとの段階的移行 (Step 4)

#### ■ Step 4.1: Tab 4 (OUT) の移行 (`src/uilogic/output_logic.py`, `src/ui/main_output.py`)
* **対象ファイル**: `src/uilogic/output_logic.py`, `src/ui/main_output.py`
* **指示**:
  1. CSV出力のアクション（`UpdateOutputSettingsAction`, `ExportCsvAction`）を定義し、Dispatcher ハンドラへ移行する。
  2. 文字コード選択肢（`"UTF-8 (BOM付き)"` / `"Shift-JIS"`）を即時内部表現（`utf-8-sig` / `cp932`）へ翻訳する。
  3. `export_points_to_csv` の呼び出し境界で `to_survey_coords` アダプターが正しく適用されていることを確認する。
* **適用ルール**: `[RULE-GEO-01]`, `[RULE-TYPE-03]`
* **完了条件**: CSV出力が正常に行われ、UI表示文字コードがドメイン層へ流出しないこと。

#### ■ Step 4.2: Tab 3 (SET) の移行 (`src/uilogic/settings_logic.py`, `src/ui/main_settings.py`)
* **対象ファイル**: `src/uilogic/settings_logic.py`, `src/ui/main_settings.py`
* **指示**:
  1. 設定保存・カラー変更・スケール切り替えを `UIAction` 化し Dispatcher へ移行する。
  2. 設定値の受け渡しを `PluginSettings` DTO クラス経由に一元化する。
* **適用ルール**: `[RULE-TYPE-03]`
* **完了条件**: 設定変更が `settings.json` へ正常に永続化され、マップのシンボロジが再描画されること。

#### ■ Step 4.3: Tab 1 (IMG) の移行 (`src/uilogic/georef_logic.py`, `src/ui/main_image.py`)
* **対象ファイル**: `src/uilogic/georef_logic.py`, `src/ui/main_image.py`
* **指示**:
  1. 画像参照、確定、基準点追加・削除、座標変換、レイヤ出力をアクションハンドラ化する。
  2. 画像コピー -> ワールドファイル作成 -> メタデータ保存 -> プロジェクト保存 -> レイヤ読み込み の永続化フローを単一ハンドラ内に集約する。
* **適用ルール**: `[RULE-GEO-01]`, `[RULE-PERSIST-05]`
* **完了条件**: アフィン変換およびワールドファイル出力後、QGIS上にジオリファレンス画像が正しく配置されること。

#### ■ Step 4.4: Tab 2 (PLOT) の移行 (`src/uilogic/digitizing_logic.py`, `src/ui/main_dock.py`)
* **対象ファイル**: `src/uilogic/digitizing_logic.py`, `src/ui/main_dock.py`
* **指示**:
  1. キャンバス打刻、点選択、点削除、属性変更、フォーカスモードの各操作を Dispatcher アクション化する。
  2. `"S:石器"` や `"遺構"` などのUIラベルを `AttributeType` / `ExcavationType` Enum へ進入直後に即時翻訳する。
  3. 打刻点更新時に `batch_update_attributes` を使用し、個別の機能ループを排除する。
  4. `check_point_duplicate`（全図面参照）および `get_next_point_number`（`AttributeType.SP` 除外）のルールを適用する。
* **適用ルール**: `[RULE-GEO-01]`, `[RULE-UI-02]`, `[RULE-TYPE-03]`, `[RULE-LAYER-04]`, `[RULE-PERSIST-05]`, `[RULE-DOMAIN-06]`
* **完了条件**: 打刻・既設点編集・自動採番・重複エラー表示・フォーカス透過度が正常に連動動作すること。

---

### Phase 3: View層の最適化 & クリーンアップ (Step 5)

#### ■ Step 5: View層の完全純粋化と循環参照の確認
* **対象ファイル**: `src/ui/` 以下のすべてのファイル
* **指示**:
  1. 各 View から QGIS レイヤツリー直接操作やロジック計算のコードを完全に削除する。
  2. すべての描画更新が `_on_state_changed` 内の `blockSignals` 保護下で実行されるように集約する。
  3. `src/uilogic/` 内のモジュールから `src/ui/main_dock.py` 等への逆インポートが一切存在しないことを確認・検証する。
* **適用ルール**: `[RULE-UI-02]`, `[RULE-TYPE-03]`
* **完了条件**: 逆参照インポートエラーが発生せず、すべてのUI操作と描画更新が不変 `UIState` を介して同期すること。

---

### 改修に際しての注意すべきポイント

#### モーダルダイアログ（`QDialog.exec_()`）の扱い
- 確定動作で完成したパラメータを保持する `UIAction` を作成し、`EventDispatcher` へ発行すること
#### `QgsMapTool`との接合境界
- `EventDispatcher` へ投入するのは、「打刻点の決定」「点の選択/削除」「モード切替」などの確定したユーザー意思決定アクションのみとする

---

## 5. LLMコード出力標準 & セルフチェックリスト (Output Standards & Verification)

### ■ コード出力標準 (Output Requirements)
1. **完全コード出力**: 修正箇所だけでなく、モジュール全体の完全な Python コードを出力すること（途中の省略 `...` は不可）。
2. **型ヒント (Type Hints)**: すべての関数・メソッドに引数および戻り値の型ヒントを明記すること (`typing.Optional`, `Tuple`, `Dict`, `Any` 等)。
3. **Docstring**: Google スタイルの Docstring を全クラス・メソッドに記述し、処理概要と引数を明記すること。

### ■ LLMセルフチェックリスト (Self-Check Gate)
コード生成後、以下のチェックリストをすべてパスしているか確認してください。

- [ ] `src/uilogic/` から `src/ui/`（`main_dock.py` 等）への逆インポートが存在しないか？
- [ ] View 側のウィジェット更新処理はすべて `blockSignals(True/False)` で保護されているか？
- [ ] UI表示用文字列（例: `"S:石器"`, `"UTF-8 (BOM付き)"`）がドメイン層やQGIS式エンジンに流出していないか？
- [ ] 座標計算は内部で数学座標系（X=東西, Y=南北）に統一され、アダプターはI/O境界のみで呼ばれているか？
- [ ] `check_point_duplicate` は全図面対象で判定され、`AttributeType.SP` は自動採番対象から除外されているか？
- [ ] `is_processing` によるビジー制御と例外キャッチが漏れなく実装されているか？
