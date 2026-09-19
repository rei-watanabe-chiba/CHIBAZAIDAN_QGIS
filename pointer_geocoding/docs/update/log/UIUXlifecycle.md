# PointerGeocoding プラグイン UI/UX ライフサイクル & 影響範囲マップ (UIUXlifecycle.md)

> **本ドキュメントの目的**:  
> コード改修・新機能追加・大規模リファクタリングの際に、UI/UX の発火ライフサイクル、データ・シグナルフロー、および改修時の「影響範囲（依存関係マップ）」を可視化・更新するためのドキュメントです。
> ドメインロジック・データ構造を定義した **`FeatureArchitecture.md`** とアンカーID (`FEAT-XX`) で相互リンクしており、LLMおよび開発者が画面操作と内部処理の影響範囲を双方向に特定できるように設計されています。

---

## 0. UI/UX ライフサイクル大分類目次 (Stage Index & Hierarchy Map)

```text
[QGIS起動・プラグイン有効化]
   │
   ▼
【Stage 1: 初期化・QGIS GUI登録ステージ】
   └── PointerGeocodingPlugin (`src/plugin.py`)
         ├── [トリガー] QGIS起動/プラグインロード ➔ メニュー/ツールバーにアクション登録
         └── 🔗 [機能アーキテクチャ] FEAT-00 (プラグイン・ライフサイクル基盤)

   │
   ▼ (ツールバー/メニューアクション押下)
【Stage 2: セッション起動・準備ステージ】
   ├── QMessageBox.question (`src/plugin.py`) [モーダル]
   │     └── [トリガー] QgsProject.isDirty() が True の場合
   └── StartDialog (`src/ui/start_dialog.py` / `StartDialog`) [モーダル]
         ├── [トリガー] プラグインアクション押下
         ├── [従属ダイアログ]
         │     ├── QFileDialog.getExistingDirectory (`src/ui/start_dialog.py`) [フォルダ選択]
         │     └── QFileDialog.getOpenFileName (`src/ui/start_dialog.py`) [CSV選択]
         └── 🔗 [機能アーキテクチャ] FEAT-00 (未保存保護・状態管理), FEAT-01 (セッション構築), FEAT-03 (基準点グリッドロード)

   │
   ▼ (セッション開始確定)
【Stage 3: メイン操作ドック起動ステージ】
   └── MainDockWidget (`src/ui/dock.py` / `MainDockWidget`) [QGIS右ドック常駐 固定幅設定]
         ├── [トリガー] StartDialog でセッション決定後
         ├── [常時表示パネル] PLOT (遺物点打刻・編集エリア) (`src/ui/tab2_plot.py` / `Tab2DigitizingMixin`)
         ├── [共通ヘルパー] バリデーション＆UIスタイル (`src/ui/style.py` / `UIStyleHelper`)
         └── 🔗 [機能アーキテクチャ] FEAT-01 (点打刻・属性編集), FEAT-02 (フォーカスモード/ラベル), FEAT-05 (レイヤ管理・同期・バリデーション防御機構)

   │
   ├───▶ 【Stage 4: サブ機能ダイアログ発火ステージ】 (メインマップツール自動サスペンド)
   │         ├── ImageDialog (`src/ui/dialogs.py` / `ImageDialog`) [モードレス]
   │         │     ├── [トリガー] MainDockWidget 「画像」ボタン (`btn_top_image`) 押下
   │         │     ├── [UI構築] `Tab1GeorefMixin._create_tab1_ui()`
   │         │     ├── [従属ダイアログ] GridInputDialog (`src/ui/dialogs.py` / `GridInputDialog`) [モーダル]
   │         │     └── 🔗 [機能アーキテクチャ] FEAT-03 (画像ジオリファレンス処理)
   │         │
   │         ├── ModelessSectionDialog [SET] (`src/ui/dialogs.py` / `ModelessSectionDialog`) [モードレス]
   │         │     ├── [トリガー] MainDockWidget 「設定」ボタン (`btn_top_settings`) 押下
   │         │     ├── [UI構築] `Tab3SettingsMixin._create_tab3_ui()`
   │         │     ├── [従属ダイアログ] QColorDialog [モーダル]
   │         │     └── 🔗 [機能アーキテクチャ] FEAT-02 (シンボル・ラベル変更処理)
   │         │
   │         ├── ModelessSectionDialog [OUT] (`src/ui/dialogs.py` / `ModelessSectionDialog`) [モードレス]
   │         │     ├── [トリガー] MainDockWidget 「出力」ボタン (`btn_top_output`) 押下
   │         │     ├── [UI構築] `Tab2DigitizingMixin._create_tab4_ui()`
   │         │     ├── [従属ダイアログ] QFileDialog.getSaveFileName [モーダル]
   │         │     └── 🔗 [機能アーキテクチャ] FEAT-04 (測量座標 CSV 出力処理)
   │         │
   │         └── ProjectSave (`src/ui/dock.py` / `_save_project`)
   │               └── [トリガー] MainDockWidget 「保存」ボタン (`btn_save_project`) 押下
   │
   └───▶ 【Stage 5: メインキャンバス打刻・属性編集オペレーションステージ】
             └── CanvasDigitizingTool (`src/canvas/map_tool.py` / `CanvasDigitizingTool`) [MapTool]
                   ├── [トリガー] QGISメインキャンバスクリック/ホバー
                   ├── [従属ダイアログ]
                   │     ├── FeatureCreateDialog (`src/ui/dialogs.py` / `FeatureCreateDialog`) [モーダル] ➔ QColorDialog
                   │     ├── PointNameEntryDialog (`src/ui/dialogs.py` / `PointNameEntryDialog`) [モーダル]
                   └── 🔗 [機能アーキテクチャ] FEAT-01 (点打刻・属性編集処理)
```

---

## 1. UI/UX根幹アーキテクチャ・基本設計 (Core UX Architecture & Principles)

今後のUI改修・機能追加において、**絶対に破ってはならないUX上のガードレール（設計思想）**を以下に定義する。

### 1.1 コンテキスト・スイッチングの排除（常時展開の原則）
連続打刻業務におけるクリック数と認知的負荷を最小化するため、メインの打刻操作パネルではタブやアコーディオンによるUI要素の隠蔽を禁止する。必要なすべてのパラメータ（点情報・属性・フォーカス等）を1画面内に常時展開させること。

### 1.2 視線移動の最小化（ダイアログのカーソル追従）
`PointNameEntryDialog` など、打刻中にユーザーのキー入力が必要となるモーダルは、画面中央ではなく「ユーザーがクリックしたキャンバス上のマウスポインタ座標付近」に計算してポップアップさせ、視線移動の物理的コストを極限まで削ること。

### 1.3 スマートUIとダンプツールの原則（イベント駆動オーケストレーション）
QGISのキャンバスツール（`CanvasDigitizingTool`）にはバリデーションやデータの組み立て責務を持たせず、純粋な「座標とクリックイベントの通知器（Dumb Tool）」に徹しさせる。入力の検証、重複チェック、DBへのコミットといったオーケストレーションは、すべてスマートなUI層（Dock側のMixin群）で集中的に制御すること。

### 1.4 非侵襲的なフェイルセーフ（見えない防御壁）
ユーザーの操作フローをモーダルエラーで強制停止させてはならない。エラー時は「赤枠表示とクリックの静かな無視（サイレントエラーブロック）」で対応し、サブ画面（画像・設定など）を開いた時は「背後のキャンバスツールを自動的にサスペンドする」ことで、操作ミスを物理的かつ静かに防ぐUXを維持すること。

### 1.5 GUI完全コード構築とコンテナ主導サイジング (DRY徹底)
* `.ui` ファイルを排除し、`ui/style.py` を用いたPythonベースの宣言的UIを採用。
* UI表示テキストは `UILabels`, `UIMessages` などの定数クラス群で一元管理し、ロジックと文字列定義を完全に分離（DRY化）する。
* **【レイアウト規則の厳格化（親コンテナ依存の原則）】**
  * ウィジェットの縦横比や整列は子コンテナとStretch比率などで統制し、`setFixedHeight` や `padding` の固定値指定による泥臭い微調整を禁止する。ウィジェット自身ではなく、**親コンテナのFlexレイアウト（QHBoxLayout 等の stretch 比率）**に伸縮を依存させる。

### 1.6 OSネイティブUIの保護とQSpinBoxへのQSS適用パターン
一般的なボタン（QPushButton）やトグルは親コンテナに追従させる。**QSpinBox 等の数値入力ウィジェット**はQSSを適用する場合、以下の検証済み安全パターンに限定すること（`ui/style.py`の`get_style_sheet()`参照）。このパターン外の指定（特に矢印サブコントロールの独自描画）はOS標準の上下矢印UIを破壊した実績があるため厳禁とする。
1. **ボタンサブコントロールには`subcontrol-position`を必ず明示指定する**（`top right`/`bottom right`等）。これを省略すると、ボタンが視覚的にボックス外へ分離し、クリック判定領域もズレてホバー/クリックが効かなくなる。
2. **矢印グリフはborder-triangleハック（透明ボーダー+単色ボーダーで三角形を模擬する手法）で描画しない**。Qtの QSS実装では矢印サブコントロールに対して信頼性がなく、黒塗りの四角形になる等の不具合を起こす。
3. **矢印画像はbase64データURI（`image: url(data:image/svg+xml;base64,...)`）でも指定しない**。QtのQSS実装はbase64データURI画像を信頼できる形でサポートしておらず（QTBUG-51081）、矢印が完全に非表示になる。矢印は`src/icon/`配下に実SVGファイルとして配置し、`get_style_sheet()`内で絶対パス（`/`区切りに正規化）を動的計算して`image: url(...)`で参照すること。
4. **押下時などの状態変化フィードバックは、ボタンの背景色ではなく矢印アイコン自体の色（別SVGファイルへの差し替え）で表現する**。ボタン背景色を`:pressed`等で変化させると、フォーカス枠とのボックスモデル上の重なり（角丸・ボーダー幅の不一致等）を誘発しやすく、状態の組み合わせ（フォーカス+押下等）ごとに個別のケア（複合セレクタでのプロパティ再宣言）が必要になる。矢印アイコンの色変更は背景・ボーダーに触れないため、この種の重なり問題が発生しない。
5. 状態変化（`:pressed`等）のルールでは、幅・高さ等のプロパティをQtが前段のルールから引き継がない場合があるため、変化後の状態でも必要なプロパティ（`width`/`height`等）を明示的に再宣言すること。

---

## 2. 詳細コンポーネント・マップ仕様

### Stage 1: 初期化・QGIS GUI登録ステージ

#### 1.1 PointerGeocodingPlugin (プラグイン本体)
* **ID / Class**: `PointerGeocodingPlugin`
* **格納ファイル**: `src/plugin.py`, `src/__init__.py`
* 🔗 **対応機能アーキテクチャ**: `FEAT-00` (プラグイン・ライフサイクル基盤)

##### 1. 基本情報 & 発火条件
* **種別**: QGIS プラグインエントリポイント
* **発火トリガー**: QGIS起動時、またはプラグインマネージャからの有効化時 (`initGui`)
* **サスペンド対象**: なし

##### 2. シグナル & イベント接続・初期化フロー
* **High DPI 描画設定 (`__init__.py`)**: QGISの描画エンジンに対し `Qt.AA_UseHighDpiPixmaps` を検証・有効化し、高解像度環境でのUI崩れを防ぐ。
* **QGIS GUI 登録 (`plugin.py`)**:
  * QGISの「プラグイン」メニュー直下にアクションを追加。
  * 専用ツールバー「点群座標取得ツール」を登録。
  * **アイコンフォールバック機構**: `icon.svg` ➔ `icon.png` ➔ 動的描画による生成の3段階でフォールバックを行い、アセット欠損時でもUI登録を安全に完了させる。
* **トリガー先**: アクション押下により `run()` メソッドが発火し、Stage 2 へ移行。

##### 3. 防御機構・例外処理ルール
* **UIインポートエラーのフォールバック**: Stage 1 から Stage 3 へ移行する際、UIモジュール (`MainDockWidget`) が未定義またはインポートエラーを起こした場合、クラッシュさせずにQGISの MessageBar を用いて Info レベルの通知を行い、安全にフォールバックする。
* **アンロード (Unload) イベントとダイアログの自動破棄**: プラグイン無効化時、画面からツールバーやアクションをクリーンアップし、アクティブな `MainDockWidget` 本体を安全に破棄する。この際、**画像・設定・出力の3ダイアログはすべて `MainDockWidget` のネイティブな子ウィジェットとして構築されているため、Qtの親子関係によって連鎖的に自動破棄される。プラグイン終了時にダイアログの個別のクリーンアップ処理を書いてはならない。**

---

### Stage 2: セッション起動・準備ステージ

#### 2.1 StartDialog (セッション開始ダイアログ) と起動検証
* **ID / Class**: `StartDialog` / `plugin.py (QMessageBox)`
* **格納ファイル**: `src/ui/start_dialog.py`, `src/plugin.py`
* 🔗 **対応機能アーキテクチャ**: `FEAT-00` (状態汚染からの保護), `FEAT-01` (セッション構築), `FEAT-03` (基準点グリッドロード)

##### 1. 基本情報 & 発火条件
* **種別**: モーダル `QDialog` / `QMessageBox`
* **発火トリガー**: プラグインのメニュー/ツールバーアクション押下後の `plugin.py::run()`
* **サスペンド対象**: QGIS メイン画面全体 (モーダルブロック)

##### 2. データ & 状態バインディング (UI要素マッピング)
* **セッション設定グループ (`config_group`)**:
  * `radio_new` / `radio_existing`: セッションの「新規作成」または「既存読み込み」モードの切り替え。
  * `edit_folder` (QLineEdit): セッションの親ディレクトリ（新規）またはセッションフォルダ（既存）のパスを保持。
  * `edit_session_name` (QLineEdit): 新規セッション名を入力（新規モード時のみ有効）。
* **グリッド設定グループ (`grid_group`)**:
  * `radio_grid_mode_new` / `radio_grid_mode_use_csv`: グリッド定義の「新規作成・更新」か「既存CSVファイル利用」かのモード切り替え。
  * `edit_grid_csv` (QLineEdit): 基準点座標が定義されたCSVファイルのパス。変更時に自動でメタデータが抽出され、以下の座標設定に反映される。
  * **原点・範囲設定**:
    * `spin_origin_x` / `spin_origin_y` (QSpinBox): 基準点（1A-00）の測量X・測量Y座標。
    * `spin_range_x_min` / `spin_range_x_max` (QSpinBox): X軸（大グリッド）の範囲（数値）。
    * `spin_range_y_min` / `spin_range_y_max` (`ExcelColumnSpinBox`): Y軸（大グリッド）の範囲（A〜ZZ）。
  * **プレビュー計算**:
    * `spin_preview_x` / `edit_preview_y`: 確認用のグリッド番号入力。
    * `lbl_preview_status` / `panel_preview_status`: 入力値に応じてリアルタイムに計算された測量座標、またはエラー（範囲外など）を表示するステータスパネル。
* **出力オブジェクト**:
  * `btn_ok` 押下時 (`_validate_and_accept` 経由) に、上記UI群から値を抽出し、`session_data` 辞書（`session_type`, `session_name`, `parent_dir_path` または `session_dir_path`, `grid_config` 等）を構成して `plugin.py` へ返却する。

##### 3. 従属・子ダイアログ
* 未保存確認 (QMessageBox.question): `QgsProject.instance().isDirty()` 判定でTrueの場合
* フォルダ選択 (QFileDialog.getExistingDirectory)
* ファイル選択 (QFileDialog.getOpenFileName)

##### 4. 状態・排他制御ルール（バリデーション・フロー）
セッション構築の安全性を担保するため、UIの入力に対し「入力時のリアクティブ・バリデーション」と「確定時の最終バリデーション」の2段階で制御を行う。
* **未保存プロジェクト保護 (UI介入)**: `run()` 発火の直後、未保存の変更がある場合は `QMessageBox` を展開し、継続の是非を問う。
* **① リアルタイム・バリデーション (`_refresh_grid_status_panel` / `_update_ok_button_state`)**
  * **発火トリガー**: グリッド設定グループ内の各種スピンボックス、またはCSVパスの変更時。
  * **フロー・条件**:
    1. **CSV無効 (`_csv_invalid`)**: CSVが指定されているが読み込めない場合、`btn_ok` (開始ボタン) を強制無効化（Hard Block）。
    2. **範囲指定の逆転 (`_is_range_invalid`)**: X範囲またはY範囲の最小値が最大値を上回っている場合、`btn_ok` を強制無効化（Hard Block）。
    3. **生成上限警告 (`_compute_expected_row_count`)**: 想定グリッド数が閾値 (10,000件) を超過した場合、一時的に `btn_ok` を無効化。`btn_grid_warning_confirm` (確認ボタン) を押下して警告を了承した場合のみロックが解除される。
    4. **プレビュー座標の正常表示 (`_update_grid_coordinate_preview`)**: 上記1〜3のすべての警告状態（`_active_grid_warning`）が存在しない、または解消された場合にのみ実行。プレビュー用の入力値が指定範囲内に収まっていれば計算された測量座標を緑色のステータスパネルに表示し、範囲外であればエラーとして「範囲外」を表示する。
* **② 確定時バリデーション (`_validate_and_accept`)**
  * **発火トリガー**: `btn_ok` クリック時。
  * **フロー・条件**:
    1. **フォルダ共通検証**: パス未入力、または実在しないディレクトリの場合は警告ダイアログを表示しブロック。
    2. **新規作成モード (`radio_new`)**: セッション名が未入力、OSの禁止文字を含む場合、または同名ディレクトリが存在する場合はエラーダイアログでブロック。
    3. **既存読み込みモード (`radio_existing`)**: 指定フォルダ内に `.qgz` が1つも存在しない場合、エラーダイアログでブロック。
  * すべての検証を通過した場合のみ `self.accept()` が呼ばれ、`session_data` を返却。セッション構築処理 (`layer_manager`) でのエラー時は `QMessageBox.critical` で遮断する。

---

### Stage 3: メイン操作ドック起動ステージ

#### 3.1 MainDockWidget (メイン操作ドック)
* **ID / Class**: `MainDockWidget`
* **格納ファイル**: `src/ui/dock.py`, `src/ui/tab2_plot.py` (Tab2DigitizingMixin)
* 🔗 **対応機能アーキテクチャ**: `FEAT-00: PLUGIN_LIFECYCLE_CORE`, `FEAT-01: POINT_DIGITIZING`, `FEAT-02: SYMBOLOGY_LABEL_SYNC`

##### 1. 基本情報 & 発火条件
* **種別**: QGIS ネイティブ DockWidget (RightDockWidgetArea)
* **発火トリガー**: Stage 2 のセッション開始処理完了時 (`layer_manager.setup_new_session` 成功後)
* **サスペンド対象**: トップボタンから起動する3つのモードレスダイアログ (画像, 設定, 出力) のいずれかが表示されている間は、キャンバスでの打刻ツール (`map_tool`) がサスペンドされる。

##### 2. データ & 状態バインディング (UI要素マッピング)
* **トップボタン群 (dock.py)**:
  * `btn_top_image`, `btn_top_settings`, `btn_top_output`: 画像 (Stage 4), 設定 (Stage 4), 出力 (Stage 4) のモードレスダイアログをそれぞれ起動。
  * `btn_save_project`: QGISプロジェクトとレイヤの保存処理を即時実行。
* **キャンバスツール (`map_tool`)**:
  * `CanvasDigitizingTool` インスタンス。キャンバス上でのクリックや既存点の選択状態をUIに伝達する。

> 💡 **UX設計ルール**: 以下の4つのパネル（点情報、属性、フォーカス、図面選択）は、アコーディオン方式（折りたたみ）を採用していません。頻繁な状態切り替えが発生する連続打刻フローにおいてアコーディオンは相性が悪いため、**意図的に『全パネル常時展開』を採用**しています。

* **モード切替・点情報パネル (`group_point_info`)**:
  * `tab2_mode_buttons`: 新規 (new) / 編集 (edit) のモード切替トグル。
  * `panel_point_info` / `lbl_point_info_status`: 状態（新規点作成 / 既設点編集 / エラー）と座標概要を示すステータス表示フレーム。
  * `edit_point_name` (QSpinBox): S/P/C属性用の点名入力（自動連番対応）。
  * `edit_point_name_sp` (QLineEdit): SP属性用のフリーテキスト点名入力。
  * `edit_branch_no`: 枝番入力。
  * `tab2_autonum_buttons`: 「自動連番」と「解除」のトグル（新規モード時のみ表示）。
  * `btn_delete_point`: 既存点削除ボタン（編集モード時のみ表示）。
* **属性パネル (`group_attribute_panel`)**:
  * `combo_attribute`: 属性（S:石器 / P:土器 / C:炭化物 / SP）。
  * `combo_excavation_type`: 出土形態（グリッド / 遺構）。
  * `combo_feature_name`: 遺構名セレクタ。
  * `btn_create_feature`: 新規遺構作成ダイアログの起動（出土形態が「遺構」かつ「新規作成」選択時のみ有効）。
  * `btn_color_picker`: 遺構カラー指定用ピッカー。
  * `combo_drawing_name`: 対象図面セレクタ。
* **フォーカスモードパネル (`group_focus`)**:
  * `btn_focus_mode`: フォーカスモードのON/OFFトグル。
  * `slider_opacity`: 透過度設定スライダー (0-100%)。
* **図面選択リスト (`group_drawing_list`)**:
  * `list_drawing_visibility`: 各画像ファイル（図面レイヤ）の表示/非表示を切り替えるリスト。

##### 3. シグナル & イベント接続
* **打刻ツール連動**: `map_tool.canvas_clicked` ➔ `_on_canvas_clicked`（新規点打刻処理）、`map_tool.existing_point_selected` ➔ `_on_existing_point_selected`（既存点の属性情報をUIにロード）。
* **リアルタイム・コミット (既設点編集時)**: 編集モードで既存点が選択されている間、点名 (`edit_point_name.editingFinished`) や属性 (`combo_attribute.currentIndexChanged`) が変更されると、旧来の「変更ボタン」を介さずに、直接フィーチャへ値がコミットされる (`_commit_point_identity_if_editing`, `_commit_attribute_fields_if_editing`)。
* **ダイアログ開閉と打刻の連動**: 各モードレスダイアログ（画像、設定、出力）の表示/非表示イベントに `_update_main_map_tool_state` が接続され、開いている間はキャンバス打刻をブロックする。

##### 4. 状態・排他制御ルール
* **ダイアログ排他制御**: いずれかのモードレスダイアログが開いている間は、キャンバスでの `map_tool` を強制的に `unsetMapTool` し、誤操作を防ぐ。
* **属性(SP)によるUI切り替え**: `combo_attribute` で「SP」が選択されると、自動連番トグルが強制的に「解除」にロックされ、点名入力がスピンボックスからフリーテキスト (`edit_point_name_sp`) へと自動で切り替わる。
* **エラー時打刻ブロック**: 遺構名未指定や点名重複エラーが発生している間（`_point_info_has_error == True` の時）は、ステータスパネルがエラー表示（赤枠等）になり、キャンバスからの新規打刻および既存点のリアルタイム更新が強制的にブロックされる。
* **ロード時イベント抑止**: 既存データ展開時の無限ループを避けるため、UIへの値セット中は `_suppress_realtime_commit = True` や `blockSignals(True)` を用いて一時的にイベントを遮断する。
* **特定フィールドの編集ロック**: 既存点を選択して編集状態に入ると、対象図面（`combo_drawing_name`）の変更がロックされ不変となる（`_set_category_widgets_locked`）。
* **編集モード中の空振り**: 編集モードのままキャンバスの空白部分（スナップ範囲外）をクリックすると、選択状態が解除されるが、モード自体は「編集」のまま維持される（`_on_blank_click_in_edit_mode`）。
* **削除ボタンの即時実行**: 「削除」ボタン押下時は、確認ダイアログなしで即座にフィーチャが削除される（`_on_delete_selected_point`）。
* **モード切替時のステート初期化**: 既存点を選択した状態のまま「新規」モードに切り替えると、自動で選択状態がリセットされ、不正な重複エラー判定の残留を防ぐ（`_on_tab2_mode_changed`）。
* **自動連番「解除」モード時のパネル挙動**: 連番トグルが「解除」に設定されている場合（SP属性選択時の強制ロックを含む）、出土形態や遺構名などのカテゴリを切り替えても、サイドパネルの点名入力欄への自動採番・上書き処理を停止し、手動入力を保護する。
* **打刻シグナルの分岐ルーティング**: 「解除」モード中にキャンバスから新規打刻シグナル (`canvas_clicked`) を受信した場合、パネルの値を用いた即時打刻は行わず、手動入力ダイアログ (`PointNameEntryDialog`) の呼び出しフロー (`_handle_release_mode_click`) へと処理を分岐させる。
* **カラーピッカーのグレーアウト保護**: 出土形態が「グリッド」に設定されている場合、全体設定（Stage 4.2）との競合を防ぐため、UI上の個別カラーピッカーボタンは強制的に無効化されフラットなグレーアウト表示となる。
* **遺構カラーの過去遡及一括更新**: カラーピッカーで色を変更した際、これから打つ点の色が変わるだけでなく、現在選択中の「遺構名」と一致する過去の全打刻ポイントの属性に対してもバックグラウンドで色が遡及一括更新され、画面が一斉に塗り替わる。

---

### Stage 4: サブ機能ダイアログ発火ステージ

#### 4.1 ImageDialog (画像管理 & 幾何補正ダイアログ)
* **ID / Class**: `ImageDialog`
* **格納ファイル**: `src/ui/dialogs.py` (UI構築: `Tab1GeorefMixin._create_tab1_ui`)
* 🔗 **対応機能アーキテクチャ**: `FEAT-03: IMAGE_GEOREFERENCING`

##### 1. 基本情報 & 発火条件
* **種別**: モードレス `QDialog`
* **発火トリガー**: `MainDockWidget` の「画像」ボタン押下
* **サスペンド対象**: `CanvasDigitizingTool` (メインマップツール一時停止)

##### 2. 配置UI要素 (Data & State Bindings)
* `tab1_mode_buttons`: 「新規追加」vs「編集/削除」のモード切替トグル。
* **新規モード用**: `edit_image_path` (画像パス), `edit_image_name` (画像名), `btn_browse_image`。
* **編集モード用**: `combo_edit_layer` (対象レイヤ選択), `btn_rename_layer` (レイヤ名変更), `btn_delete_layer` (削除)。
* **共通**: `table_ref_points` (基準点座標一覧), プレビューキャンバス (`QgsMapCanvas`), `btn_confirm_image` (基準点設置ダイアログ呼び出し), `btn_transform` (変換計算), `btn_export_layer` (レイヤ出力)。

##### 3. 従属・子ダイアログ (UX Flow)
* `GridInputDialog` (モーダル): プレビューキャンバス上でクリックした際に発火。Xグリッド(数値), Yグリッド(英字強制大文字化), 小グリッドを入力させ、リアルタイムに `PointGeo_grid.csv` のキャッシュデータと照合・バリデーションを行う。

##### 4. 状態・排他制御ルール
* **既存ワールドファイルの拒否**: 新規画像追加時、同一階層に `.tfw` などのワールドファイルが既に存在する場合は、本プラグインの管轄外となるため登録をブロックする。
* **画像の遅延コピー**: 「基準点設置」時点ではセッションディレクトリへの実ファイルコピーを行わず、元ファイルを参照する。最終的な「レイヤ出力」確定時に初めてコピーとワールドファイル書き出しを行う。
* **打刻点の削除警告**: 「削除」ボタン押下時、その図面名を対象 (`drawing_name`) として既にキャンバスに打刻された点が存在する場合は、事前に警告ダイアログを発出する。
* **ボタンの活性制御**: 基準点が2点未満、または座標が未確定の場合は `btn_transform` (変換計算) が無効化される。
* **トランザクション中の操作ロック (UX視点)**: 画像の出力、名前変更、削除などの重いI/O操作中は、マウスポインタが砂時計化し、画面上のあらゆるクリックや操作が一時的にブロックされ、ユーザーによる非同期の割り込みを物理的に防ぐ。
* **打刻ポイントの自動追従 (UX視点)**: パネル上で画像レイヤの名前を変更した場合、ユーザーが手動で過去の打刻点を修正しなくても、バックグラウンドで自動的に対象図面名が同期・更新され、不整合を意識させない作りになっている。

---

#### 4.2 ModelessSectionDialog [SET] (環境設定ダイアログ)
* **ID / Class**: `ModelessSectionDialog` (設定用)
* **格納ファイル**: `src/ui/dialogs.py` (UI構築: `Tab3SettingsMixin._create_tab3_ui`)
* 🔗 **対応機能アーキテクチャ**: `FEAT-02: SYMBOLOGY_LABEL_SYNC`

##### 1. 配置UI要素 (Data & State Bindings)
* **カラーピッカー**: `ref_line_color`, `point_line_color` など（`QColorDialog` を呼び出し設定）。
* **スケール閾値設定**: `major_scale_mode`, `minor_scale_mode` (常時表示 vs 指定スケール)。

##### 2. 状態・排他制御ルール
* **Stage 2 起動時からの完全な状態復元 (UX視点)**: UIの初期ステート（ラジオボタンの選択状態やスピンボックスの活性/非活性）はハードコードされた初期値を持たず、起動時に読み込んだ JSON の値（例: スケール閾値が `-1` であれば「常時表示」とみなす）から逆算・推論され、完全な単一方向データフローで前回終了時の状態が齟齬なく復元されます。
* **指定モード連動**: スケール表示が「指定」に設定された場合のみ、閾値を入力するスピンボックス (`major_scale_value`, `minor_scale_value`) が活性化(有効化)される。
* **変更の適用 (Apply)**: `btn_settings_apply` 押下時、全パネルの値を収集して `settings.json` に保存する。このファイルI/O完了をトリガーに発火する `settings_changed` シグナルを受け取り、QGISキャンバス上の全シンボロジを動的（リアクティブ）に再構築・再描画する（再起動不要）。

---

#### 4.3 ModelessSectionDialog [OUT] (座標CSV出力ダイアログ)
* **ID / Class**: `ModelessSectionDialog` (出力用)
* **格納ファイル**: `src/ui/dialogs.py` (UI構築: `Tab2DigitizingMixin._create_tab4_ui`)
* 🔗 **対応機能アーキテクチャ**: `FEAT-04: SURVEY_CSV_EXPORT`

##### 1. 配置UI要素 (Data & State Bindings)
* `radio_utf8` / `radio_sjis`: 出力文字エンコーディングのトグル。
* `edit_csv_path`, `btn_browse_csv`: 保存先パス。
* `btn_export_csv`: 出力実行ボタン。

##### 2. 状態・排他制御ルール
* **出力前バリデーション**: 出力実行時 (`_on_export_csv_clicked`)、現在のプロジェクト内の全点をスキャンする。未計算（基準点が未確定で `real_x`/`real_y` が存在しない等）のフィーチャが1件でも含まれる場合、全体のエクスポート処理を中断して警告を出す。

---

### Stage 5: メインキャンバス打刻・属性編集オペレーションステージ

#### 5.1 CanvasDigitizingTool (メイン打刻マップツール)
* **ID / Class**: `CanvasDigitizingTool`
* **格納ファイル**: `src/canvas/map_tool.py`
* 🔗 **対応機能アーキテクチャ**: `FEAT-01: POINT_DIGITIZING`

##### 1. 基本情報 & 発火条件
* **種別**: `QgsMapTool` 派生クラス
* **発火トリガー**: メインキャンバスのクリック・ホバー

##### 2. 従属・子ダイアログ
* `FeatureCreateDialog`: 遺構名新規追加時 (モーダル)
* `PointNameEntryDialog`: 解除モードやSP属性打刻時の点名直接入力時 (モーダル)

##### 3. シグナル & イベント接続
* **発行シグナル (Emits)**:
  * `canvas_clicked(QgsPointXY)`: 新規モード時の通常クリック
  * `existing_point_selected(dict)`: 編集モード時、15px以内の既存点スナップ
  * `blank_click_in_edit_mode`: 編集モード時、空振りクリック (スナップ失敗)

##### 4. 状態・排他制御ルール (UX / バリデーション / 安全策)
* **サイレントエラーブロック**: 新規点打刻時、遺構名未指定や点名重複などのエラー状態にある場合、ポップアップ等で操作を阻害するのではなく、UIパネルのステータス表示が赤枠エラーになるだけで「キャンバスクリックを静かに無視（ブロック）する」という安全・非侵襲的なフェイルセーフが実装されている。
* **フォーカスモード連動スナップ (安全策)**: 編集モードでキャンバスをホバーまたはクリックした際、現在の「フォーカスモード」で非表示（透過）になっているフィーチャに対しては、空間検索（`QgsSpatialIndex`）のヒット候補から意図的に除外される。これにより、見えていない無関係なポイントを誤って選択・編集してしまう事故を物理的に防ぐ。
* **編集モード中の空振り時の選択解除**: 編集モードで既存フィーチャの無い場所（スナップ範囲外）をクリックした場合、新規点は作成されず、「編集モード」を維持したまま、現在選択中の情報パネル状態のみをクリアする（`blank_click_in_edit_mode` シグナル）。
* **クリック位置へのダイアログ追従**: SP属性や「解除」モード時に出現する `PointNameEntryDialog` は、画面中央ではなく、ユーザーがクリックしたキャンバス上のまさにそのマウスポインタ位置を計算して出現（ポップアップ）し、視線移動を最小限に抑える設計となっている。

##### 4. 状態・排他制御ルール (T-0037, T-0039)
* **新規モード**: 既存フィーチャのスナップ処理・ホバーマーカー表示をスキップし、一律で `canvas_clicked` を発火する。
* **編集モード**: 15px以内のスナップ判定を行い、ヒット時は `existing_point_selected` を発火。ヒットしなかった場合は `blank_click_in_edit_mode` を発火し、Dock側の選択状態を解除させる。

##### 5. 手動入力ダイアログUXフロー (解除モード / SP属性時)
* **ダイアログのポップアップ**: 打刻ツールがクリックを検知した際、Dock側が「解除」モード（SP属性含む）であれば、クリック位置の近傍に `PointNameEntryDialog` がモーダル表示され、ユーザーに確実な点名・枝番の入力を促す。
* **内部ウィジェットの動的切替**: メインドックと同様に、ダイアログ内部の入力ウィジェットも**「属性がSPの場合は正規表現付きの `QLineEdit` に、それ以外は `QSpinBox` に動的に切り替わる」**よう設計されており、SP属性特有の自由入力と通常連番の厳格な型を両立している。
* **直前打刻値のプレフィル (入力補助)**: ダイアログが開く際、同一グループ（出土形態・遺構名・SP/非SP区分が一致）内で直前に打刻された点名を算出し、初期値として自動セットする (`_get_last_created_point_name`)。これにより手動入力の負担を最小限に抑える。
