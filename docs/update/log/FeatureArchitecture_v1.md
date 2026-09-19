# FeatureArchitecture.md

# PointerGeocoding プラグイン 主要機能内部アーキテクチャ仕様書

## 0. 機能インデックス & 相互参照アンカーマップ (Feature Index)

本ドキュメントは、PointerGeocoding プラグインの主要ドメイン機能における**データ構造、処理パイプライン、破壊不可制約 (Invariants)、およびレイヤ/DB同期ロジック**を定義するものである。
UI・操作制御のフローを記述した `UIUXlifecycle.md` と相互アンカーIDで紐付いており、コード改修時のLLMのハルシネーション防止および影響範囲特定に用いる。

| 機能ID | 機能名称 | 主担当モジュール | 関連 UI Phase (`UIUXlifecycle.md`) |
| :--- | :--- | :--- | :--- |
| **`FEAT-01`** | **点打刻・属性編集処理** | `src/logic/core.py`, `src/layer/gpkg.py`, `src/canvas/map_tool.py` | Phase 3 (Dock), Phase 5 (MapTool) |
| **`FEAT-02`** | **フィーチャーフィールド連動シンボル・ラベル変更処理** | `src/layer/symbology.py`, `src/layer/models.py` | Phase 3 (Dock), Phase 4 (SET Dialog) |
| **`FEAT-03`** | **画像ジオリファレンス処理** | `src/logic/transform.py`, `src/layer/manager.py` | Phase 4 (IMG Dialog) |
| **`FEAT-04`** | **測量座標 CSV 出力処理** | `src/logic/transform.py`, `src/logic/core.py` | Phase 4 (OUT Dialog) |

---

## FEAT-01: 点打刻・属性編集処理 (POINT_DIGITIZING)

### 1. 基本情報 & アンカー参照
* **機能ID**: `FEAT-01`
* **機能名称**: 点打刻・属性編集処理 (POINT_DIGITIZING)
* **主要担当モジュール**:
  * **ドメインロジック**: `src/logic/core.py` (`get_next_point_number`, `check_point_duplicate`, `build_digitized_feature`)
  * **UIロジック (検証・状態管理)**: `src/ui/tab2_plot.py` (`Tab2DigitizingMixin`)
  * **マップツール**: `src/canvas/map_tool.py` (`CanvasDigitizingTool`)
  * **データ層**: `src/layer/gpkg.py` (`GpkgCacheMixin`)

### 2. データ構造 & Source of Truth (データの真実の所在)
| データ種別 | 格納場所・オブジェクト | 状態の所有権 (Source of Truth) | 同期・更新タイミング |
| :--- | :--- | :--- | :--- |
| **打刻点データ** | `session_layers.gpkg` の `points` レイヤ | **Primary (DB)** | 新規打刻時、または既設点編集時の値変更時 (`editingFinished` 等でリアルタイムコミット) |
| **空間インデックス** | `QgsSpatialIndex` (メモリ) | Secondary (Cache) | Observerパターン: レイヤの `featureAdded` 等のシグナルで自動同期 |
| **属性キャッシュ** | `attr_cache`, `geom_cache` (メモリ) | Secondary (Cache) | 同上 |

### 3. E2E パイプライン (処理フロー)
本機能は大きく「新規点作成」モードと「既設点編集」モードに分かれます。
* **前提（検証の分離）**: `CanvasDigitizingTool` は座標取得とスナップ判定のみを担い、検証とDB更新はすべて `Tab2DigitizingMixin` 側で行われます。

#### A. 新規点作成モード (tab2_current_mode == "new")
スナップ判定を行わず、クリックした座標に新しい点を作成します。さらに内部で2つのサブモードに分岐します。
1. **自動連番モード (tab2_autonum_mode == "auto")**
   * 同一属性グループの直前点から数値を抽出し、自動採番（`get_next_point_number`）します。
   * UIの値をベースに重複チェック等を行い、フィーチャ生成と保存を行います。
2. **解除モード (tab2_autonum_mode == "release")**
   * 打刻座標付近に `PointNameEntryDialog` をポップアップさせ、ユーザーに点名・枝番を直接入力させます。
   * **【SP属性による強制】**: 属性が「SP (特殊遺物)」の場合は自動連番が意味を持たないため、この「解除」モードが強制適用されます。

#### B. 既設点編集モード (tab2_current_mode == "edit")
クリック座標周辺の既存点を検索し、ヒットした点を選択状態にします。
1. **データロード時の安全装置 (`_suppress_realtime_commit`)**: DBからUIパネルに値を展開する際、UI変更イベントが発火してDBへ書き戻してしまう無限ループを防ぐため、一時的にコミットを遮断します。
2. **リアルタイムコミット (T-0038)**: ロード完了後、ユーザーが点名や属性を変更すると、確定ボタンなしで直接DBへ書き込まれます。

### 4. 破壊不可制約 & ビジネスルール (Invariants)
> ⚠️ **この機能を改修・リファクタリングする際に破ってはならない制約**
1. **【測量座標系アダプタの境界分離】**: 内部データ (`real_x`, `real_y`、ジオメトリ) は**全て QGIS キャンバスと同じ数学座標系 (X=東西, Y=南北)** で統一する。測量座標 (X=南北, Y=東西) への変換は `to_survey_coords` 等を用いて I/O 境界でのみ行う。
2. **【StrEnumパターン】**: 属性値 (`ExcavationType`, `AttributeType`) は Enum を使用し、DB書き込み時は `.value` で文字列化する。
3. **【自動連番の SP 属性除外】**: SP (特殊遺物) 属性は手入力固定であり、自動連番ロジックから完全に除外する。
4. **【グローバル重複チェック】**: 点の重複判定に図面名 (`drawing_name`) は用いず、プロジェクト全体で判定する (T-0032)。

---

## FEAT-02: フィーチャーフィールド連動シンボル・ラベル変更処理 (SYMBOLOGY_LABEL_SYNC)

### 1. 基本情報
* **機能ID**: `FEAT-02`
* **機能名称**: フィーチャーフィールド連動シンボル・ラベル変更処理
* **主要担当モジュール**:
  * **シンボロジ構築**: `src/layer/symbology.py` (`SymbologyMixin`)
  * **設定UIとイベント購読**: `src/ui/tab3_settings.py` (`Tab3SettingsMixin`)
  * **設定状態管理**: `src/layer/manager.py` (設定保存とシグナル発行)

### 2. データ構造 & Source of Truth
| データ種別 | 格納場所・オブジェクト | 状態の所有権 | 同期・更新タイミング |
| :--- | :--- | :--- | :--- |
| **全体表示設定** | `settings.json` (LayerManager経由) | **Primary (Config File)** | 設定パネルの「適用」ボタン押下時 (`save_settings`) |
| **QGIS レンダラー** | `QgsVectorLayer` (メインキャンバス表示) | Render Output | `settings_changed` シグナル受領時、UI属性変更時、またはFocus Mode切替時 |

### 3. E2E パイプライン (処理フロー)
本機能は、大きく3つの軸でシンボル・ラベルの制御が行われます。

#### ① 環境設定 (`settings_changed`) による全体同期
* **トリガー**: UI (Tab 3) で設定を変更し「適用」を押下して JSON に保存された際の発火。
* **対象**: シンボルの基本サイズ・線幅、ラベルの設定（オフセットやハロ）、基準点のスケールディペンデント表示制御、およびデフォルト値である「出土形態: グリッド」のカラー変更。
* **処理フロー**: `Tab3SettingsMixin` がシグナルを受領し、`SymbologyMixin` の `apply_ref_point_symbology` と `apply_point_symbology` を呼び出し、レンダラーを再構築します。

#### ② UI操作によるリアクティブなシンボル変更
* **トリガー**: パネル上のカラーピッカーでの色変更や、属性（出土形態、遺構名、属性カテゴリ）の変更。
* **対象**: フィーチャごとのカテゴリ形状（丸、ダイヤ、三角、二重丸）およびフィーチャカラー。
* **処理フロー**: カラーピッカーやUIの変更が**リアルタイムコミット（FEAT-01）**によってDBの `color_code` や `attribute_type` に書き込まれます。シンボロジは `coalesce("color_code", '#FF5722')` のようにデータ定義プロパティでフィールドを参照しているため、DBが更新されるとQGISの描画エンジンが自動的にリアクティブに地図上の色や形状を更新します。

#### ③ フォーカスモードによる動的透過度変更
* **トリガー**: 「Focus Mode」トグルのオンオフ、または透過度スライダーの変更、UIのカテゴリフィルタ（図面名、出土形態等）の変更。
* **対象**: 選択中のカテゴリに合致しないフィーチャの透過度ダウン。
* **処理フロー**: `build_opacity_expression` が現在のUIフィルタ状態からSQLライクな `CASE WHEN` 評価式を生成します（例：`CASE WHEN "drawing_name" = 'X' AND ... THEN 100 ELSE 20 END`）。その後 `apply_opacity_expression` が `QgsPropertyOpacity` を使ってレンダラー全体に式を適用し、即座に再描画させます。

### 4. 破壊不可制約 & ビジネスルール (Invariants)
> ⚠️ **この機能を改修・リファクタリングする際に破ってはならない制約**
1. **【シンボロジ生成の責務一元化】**: `CanvasDigitizingTool` はシンボロジ操作を行いません。すべてのレンダラー生成とプロパティ適用は `SymbologyMixin` に集約されています（T-0017）。
2. **【データ定義プロパティの利用】**: ラベル色やカラーコード、透過度などを反映する際、フィーチャをループして個別に設定してはなりません。必ず `QgsProperty` と `dataDefinedProperties` を用い、QGISのレンダリングエンジン側で式（Expression）として評価させるパターンを厳守します。

---

## FEAT-03: 画像ジオリファレンス処理 (IMAGE_GEOREFERENCING)

### 1. 基本情報
* **機能ID**: `FEAT-03`
* **機能名称**: 画像ジオリファレンス処理
* **主要担当モジュール**:
  * **UIオーケストレーション**: `src/ui/tab1_image.py` (`Tab1GeorefMixin`)
  * **座標変換ロジック**: `src/logic/transform.py` (`CoordinateTransformer`)
  * **一括座標更新**: `src/logic/core.py` (`update_point_layer_geometry`)
  * **基準点CSV管理**: `src/layer/grid_csv.py` (`GridCsvMixin`)

### 2. データ構造 & Source of Truth
| データ種別 | 格納場所・オブジェクト | 状態の所有権 | 同期・更新タイミング |
| :--- | :--- | :--- | :--- |
| **ジオリファレンス設定** | `ImageLayerMeta` (`models.py`) | **Primary** | 変換確定時 (レイヤ出力時) に JSON へ保存 |
| **基準点グリッド** | `PointGeo_grid.csv` (`ref_points` レイヤ) | Secondary | ロード時に `delimitedtext` として展開 |

### 3. E2E パイプライン (処理フロー)
本機能は、「画像選択〜基準点打刻」「変換計算」「確定と一括更新」の3フェーズに分かれます。

#### ① 画像選択と基準点打刻 (プレビューキャンバス)
1. **ワールドファイル拒否判定**: 「基準点設置」ボタン押下時 (`_on_confirm_image_clicked`)、ソース画像と同じ階層にワールドファイル (`.tfw`, `.jgw` 等) が存在しないか検査し、存在すれば拒否します（本プラグインが主導権を持つため）。
2. **遅延コピー**: この時点ではセッションの `image/` ディレクトリへ実ファイルはコピーされず、プレビューダイアログ (`ImageDialog`) はソース画像を直接参照します。
3. **スナップ判定**: キャンバス上をクリックした際 (`_on_preview_canvas_point_clicked`)、スクリーン座標系で既存の基準点と距離計算を行い、15px以内なら「編集/削除モード」、それ以外なら「新規追加モード」で `GridInputDialog` をポップアップさせます。
4. **測量座標→数学座標変換**: ユーザーが入力した 測量X(南北)・測量Y(東西) は直ちに `from_survey_coords` によって 数学X(東西)・数学Y(南北) に変換され、`real_x`・`real_y` としてメモリに保持されます。

#### ② 変換行列の計算 (`_on_transform_clicked`)
1. **入力**: ピクセル座標 (`pixel_x`/`y`) と 実座標 (`real_x`/`y`) のペアリストを受領。
2. **変換行列計算**: 2点なら `compute_helmert_2p`、3点以上なら `compute_affine_3p` を呼び出してアフィンパラメータ (A, B, C, D, E, F) を取得。
3. **指標計算**: `evaluate_residuals` によって回転角と歪み(%)を算出し、UIのステータスパネルに表示。

#### ③ 確定と一括座標更新 (`_on_export_layer_clicked`)
1. **実ファイルのコピーと書き出し**: ここで初めて画像をセッションの `image/` にコピーし、同時にワールドファイルを書き出します。JSON メタデータ (`update_image_metadata`) も更新されます。
2. **一括座標更新 (`update_point_layer_geometry`)**: 
   * 当該図面に属する全フィーチャを走査。
   * 保持されている `pixel_x` と `pixel_y` に対してアフィン変換パラメータを適用。
   * 新しい数学座標 (`calc_math_x`, `calc_math_y`) を計算し、DBの `canvas_x`, `canvas_y`, `real_x`, `real_y` と `QgsGeometry` を一括で上書き更新します。

### 4. 破壊不可制約 & ビジネスルール (Invariants)
> ⚠️ **この機能を改修・リファクタリングする際に破ってはならない制約**
1. **【基準点 CSV 読み込み時の軸スワップ】**: `GridCsvMixin` で CSV を `delimitedtext` レイヤとして読み込む際、測量座標からQGISキャンバス上の座標（数学座標）へ正しくマッピングするため、URIプロバイダ設定で意図的に `xField=Ｙ座標列`（%EF%BC%B9%E5%BA%A7%E6%A8%99）, `yField=Ｘ座標列` とスワップしてロードします。
2. **【遅延コピー (Deferred Copy) の維持】**: 画像ファイルの `image/` へのコピーは「基準点設置」時点で行ってはなりません。途中で作業をキャンセルされた場合に孤立ファイル（Orphaned file）が残るのを防ぐため、必ず「レイヤ出力（書き出し）」の直前で行います。
3. **【最小点数制約】**: ヘルマート変換は最低2点、アフィン変換は最低3点が必要です。

---

## FEAT-04: 図面出力・エクスポート処理 (DRAWING_OUTPUT_EXPORT)

### 1. 基本情報
* **機能ID**: `FEAT-04`
* **機能名称**: 図面出力・エクスポート処理
* **主要担当モジュール**: 
  * **UIオーケストレーション**: `src/ui/tab2_plot.py` (`Tab2DigitizingMixin._create_tab4_ui`)
  * **出力ロジック**: `src/logic/transform.py` (`export_points_to_csv`)

### 2. データ構造 & Source of Truth
| データ種別 | 格納場所・オブジェクト | 状態の所有権 | 同期・更新タイミング |
| :--- | :--- | :--- | :--- |
| **打刻点データ** | `QgsVectorLayer` (`point_layer`) | **Primary (DB)** | FEAT-01完了時 |
| **CSV 出力結果** | ユーザー指定パスの `.csv` | Render Output | エクスポート実行時 |

### 3. E2E パイプライン (処理フロー)
1. **対象チェック**: `point_layer` の全フィーチャを取得します（**対象図面によるフィルタリングや特定フィールドによるソートは行わず、レイヤ内の全件をそのまま出力します**）。
2. **実座標チェック**: 出力対象フィーチャのうち、未計算（`real_x`・`real_y` およびフォールバックの `canvas_x`・`canvas_y` が未取得）のものが1件でも存在すれば、出力処理を中止し警告ダイアログを表示します。
3. **CSV書き出し**:
   * 出力エンコーディングはUIのラジオボタンで指定された `utf-8-sig` または `cp932` (Shift_JIS) を適用します。
   * 各フィーチャから 出土形態・遺構名・属性・点名・枝番 を抽出します。
   * メモリ内の数学座標 (`real_x`, `real_y`) に対して `to_survey_coords` を適用し、測量座標へ変換した上で出力します。

### 4. 破壊不可制約 & ビジネスルール (Invariants)
> ⚠️ **この機能を改修・リファクタリングする際に破ってはならない制約**
1. **【無選別フルダンプ制約】**: UI上で対象図面が選択されていたとしても、エクスポート処理(`export_points_to_csv`)はフィルタリングを行わず、現在保持している全てのポイントをダンプします。
2. **【エンコーディングの選択式】**: CSVの文字コードは固定せず、UIで `utf-8-sig`（BOM付きUTF-8）または `cp932`（Shift_JIS）から選択可能にする必要があります。デフォルトは `utf-8-sig` です。
3. **【測量座標への逆変換】**: データベース内（`canvas_x`/`canvas_y` または `real_x`/`real_y`）に保持されている数学座標を、出力直前の境界で `to_survey_coords` を使って**測量座標（X軸=南北, Y軸=東西）**へ逆変換してからCSVに書き出します。

---

## FEAT-05: レイヤ管理・同期・バリデーション防御機構 (LAYER_SYNC_DEFENSE)

### 1. 基本情報
* **機能ID**: `FEAT-05`
* **機能名称**: レイヤ管理・同期・バリデーション防御機構
* **主要担当モジュール**: 
  * `src/ui/tab2_plot.py` (入力監視・シグナル制御)
  * `src/ui/dock.py` (コンテキストマネージャ)
  * `src/layer/manager.py` (属性の静的アトミック同期)
  * `src/ui/style.py` (UIエラーフィードバック)

### 2. E2E パイプラインと防御策 (3大分類)

本プラグインは、QGIS標準のレイヤ編集モードや属性テーブル変更に依存せず、独自UIからの入力イベントを起点として静的かつリアルタイムにDBを更新するアーキテクチャを採用しています。そのため、無限ループや不整合を防ぐ以下の防御機構・バリデーションが稼働しています。

#### ① 画像レイヤ管理 (対象図面の同期と保護)
* **対象図面 (drawing_name) の独自アトミック同期**:
  UIからレイヤ名の変更・削除を行った際、QGIS標準のレイヤツリーイベントに依存せず、`LayerManager.rename_drawing_name` / `clear_drawing_name_for_layer` を実行します。これにより、`point_layer` 内の当該図面に紐付く全フィーチャの `drawing_name` 属性をバックグラウンドで一括置換・クリアし、状態の乖離を防ぎます。
* **トランザクション中のユーザー操作ロック (`busy_interaction_guard`)**:
  画像のコピー、レイヤ名の変更・削除、座標変換の確定など、重いI/O操作や一括更新トランザクションが走っている最中は、マウスポインタを砂時計に変更しキャンバス上のクリックイベントを無効化します。これにより非同期的な状態変更の割り込みを完全に防ぎます。

#### ② 点名・枝番系（点情報グループ）
* **リアルタイム重複スキャンと自己除外 (`_check_realtime_duplicate`)**:
  点名や枝番のUI値が変更されるたびに、対象レイヤ内から「出土形態・遺構名・点名・枝番」が一致するフィーチャが存在しないか走査します。この際、**現在編集中（セレクト中）のフィーチャ自身のIDは検索対象から除外 (`exclude_feature_id`)** し、インプレース編集時の誤検知（自己重複）を回避します。
* **SP属性専用の入力形式制限 (Regex Validation)**:
  自動連番の対象外となるSP（特別遺物）属性のテキストボックスには、`QRegularExpressionValidator(r"^[A-Za-z0-9_-]+$")` を適用し、半角英数字・ハイフン・アンダースコア以外の入力をQtレベルで強制ブロックします。
* **UIエラーフィードバックとコミット遮断**:
  重複エラー検知時は直ちに `UIStyleHelper.set_error_border` で当該入力ボックスの枠線を赤くし、内部エラーフラグ (`_point_info_has_error`) を True にします。このフラグが立っている間は、DBへのリアルタイムコミット（保存処理）をすべて遮断します。

#### ③ 点属性系（旧: 属性パネル / 出土形態・遺構名など）
* **無限ループの抑止 (`_suppress_realtime_commit`)**:
  編集モード移行時、既存フィーチャのデータを読み込んでUIのコンボボックスに値をセット（ロード）する際、通常なら `currentIndexChanged` 等のシグナルが発火し、意図せず再帰的なDB書き込み（リアルタイムコミット）が発生してしまいます。これを防ぐため、ロード中は `_suppress_realtime_commit = True` とし、シグナルハンドラを空振りさせます。
* **未指定状態のリアルタイム検知 (`_is_feature_name_missing`)**:
  出土形態が「遺構」に設定されたにもかかわらず、具体的な遺構名が未選択（「-- 新規追加 --」のプレースホルダー状態）であることを検知し、前述の「コミット遮断」機構を発動させます。
* **プログラム的な状態変更のシグナルブロック (`blockSignals`)**:
  リストアイテムやコンボボックスをUIヘルパーから再構築する際、一時的に `widget.blockSignals(True)` を呼び出すことで、画面の初期化・再描画に伴うイベント連鎖を安全に断ち切っています。
