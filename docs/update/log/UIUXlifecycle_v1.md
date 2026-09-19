# PointerGeocoding プラグイン UI/UX ライフサイクル & 影響範囲マップ (UIUXlifecycle.md)

> **本ドキュメントの目的**:  
> コード改修・新機能追加・大規模リファクタリングの際に、UI/UX の発火ライフサイクル、データ・シグナルフロー、および改修時の「影響範囲（依存関係マップ）」を可視化・更新するためのドキュメントです。
> ドメインロジック・データ構造を定義した **`FeatureArchitecture.md`** とアンカーID (`FEAT-XX`) で相互リンクしており、LLMおよび開発者が画面操作と内部処理の影響範囲を双方向に特定できるように設計されています。

---

## 0. UI/UX ライフサイクル大分類目次 (Phase Index & Hierarchy Map)

```text
[QGIS起動・プラグイン有効化]
   │
   ▼
【Phase 1: 初期化・QGIS GUI登録フェーズ】
   └── PointerGeocodingPlugin (`src/plugin.py`)
         ├── [トリガー] QGIS起動/プラグインロード ➔ メニュー/ツールバーにアクション登録
         └── 🔗 [機能アーキテクチャ] FEAT-01 (初期化)

   │
   ▼ (ツールバー/メニューアクション押下)
【Phase 2: セッション起動・準備フェーズ】
   ├── QMessageBox.question (`src/plugin.py`) [モーダル]
   │     └── [トリガー] QgsProject.isDirty() が True の場合
   └── StartDialog (`src/ui/start_dialog.py` / `StartDialog`) [モーダル]
         ├── [トリガー] プラグインアクション押下
         ├── [従属ダイアログ]
         │     ├── QFileDialog.getExistingDirectory (`src/ui/start_dialog.py`) [フォルダ選択]
         │     └── QFileDialog.getOpenFileName (`src/ui/start_dialog.py`) [CSV選択]
         └── 🔗 [機能アーキテクチャ] FEAT-01 (セッション構築), FEAT-03 (基準点グリッドロード)

   │
   ▼ (セッション開始確定)
【Phase 3: メイン操作ドック起動フェーズ】
   └── MainDockWidget (`src/ui/dock.py` / `MainDockWidget`) [QGIS右ドック常駐 固定幅設定]
         ├── [トリガー] StartDialog でセッション決定後
         ├── [常時表示パネル] PLOT (遺物点打刻・編集エリア) (`src/ui/tab2_plot.py` / `Tab2DigitizingMixin`)
         └── 🔗 [機能アーキテクチャ] FEAT-01 (点打刻・属性編集), FEAT-02 (フォーカスモード/ラベル)

   │
   ├───▶ 【Phase 4: サブ機能ダイアログ発火フェーズ】 (メインマップツール自動サスペンド)
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
   └───▶ 【Phase 5: メインキャンバス打刻・属性編集オペレーションフェーズ】
             └── CanvasDigitizingTool (`src/canvas/map_tool.py` / `CanvasDigitizingTool`) [MapTool]
                   ├── [トリガー] QGISメインキャンバスクリック/ホバー
                   ├── [従属ダイアログ]
                   │     ├── FeatureCreateDialog (`src/ui/dialogs.py` / `FeatureCreateDialog`) [モーダル] ➔ QColorDialog
                   │     ├── PointNameEntryDialog (`src/ui/dialogs.py` / `PointNameEntryDialog`) [モーダル]
                   └── 🔗 [機能アーキテクチャ] FEAT-01 (点打刻・属性編集処理)
```

---

## 詳細コンポーネント・マップ仕様

### Phase 3: メイン操作ドック起動フェーズ

#### 3.1 MainDockWidget (メイン操作ドック)
* **ID / Class**: `MainDockWidget`
* **格納ファイル**: `src/ui/dock.py`
  * **Mixins**: `Tab1GeorefMixin`, `Tab2DigitizingMixin`, `Tab3SettingsMixin`
* 🔗 **対応機能アーキテクチャ**: `FEAT-01: POINT_DIGITIZING`, `FEAT-02: SYMBOLOGY_LABEL_SYNC`

##### 1. 基本情報 & 発火条件
* **種別**: `QDockWidget` (QGIS 右ドックエリア常駐)
* **発火トリガー**: `StartDialog` でのセッション確定時
* **サスペンド対象**: なし (QGIS メイン画面と並行操作)

##### 2. データ & 状態バインディング
* **入力**: `LayerManager`, UI操作情報
* **出力**: QgsVectorLayerへの即時属性コミット（T-0038: 既設点編集中は `editingFinished` や `currentIndexChanged` などのシグナルでリアルタイムコミット）
* 🔗 **ロジック接続先**: `FEAT-01` (打刻・属性編集), `FEAT-02` (フォーカスモード・透過度)

##### 3. シグナル & イベント接続
* **発行シグナル (Emits)**:
  * 該当なし (内部イベントハンドラを直接呼ぶ)
* **受信シグナル (Listens)**:
  * `CanvasDigitizingTool.canvas_clicked` ➔ `_on_canvas_clicked()` (新規打刻処理)
  * `CanvasDigitizingTool.existing_point_selected` ➔ `_on_existing_point_selected()` (既設点編集状態遷移)
  * `CanvasDigitizingTool.blank_click_in_edit_mode` ➔ `_on_blank_click_in_edit_mode()` (選択解除)

##### 4. 状態・排他制御ルール (T-0036, T-0038)
* **新規モード (`tab2_current_mode == "new"`)**: キャンバスクリックで即時作成・スナップ無効化。SP属性以外は直前打刻追従型採番。
* **編集モード (`tab2_current_mode == "edit"`)**: 点を選択し、パネルに展開。点名・属性・枝番等のUI値を変更すると、変更確定イベントを契機にフィーチャへリアルタイムコミット（確定ボタンは廃止）。

---

### Phase 4: サブ機能ダイアログ発火フェーズ

#### 4.1 ImageDialog (画像管理 & 幾何補正ダイアログ)
* **ID / Class**: `ImageDialog`
* **格納ファイル**: `src/ui/dialogs.py` (UI構築: `Tab1GeorefMixin._create_tab1_ui`)
* 🔗 **対応機能アーキテクチャ**: `FEAT-03: IMAGE_GEOREFERENCING`

##### 1. 基本情報 & 発火条件
* **種別**: モードレス `QDialog`
* **発火トリガー**: `MainDockWidget` の「画像」ボタン押下
* **サスペンド対象**: `CanvasDigitizingTool` (メインマップツール一時停止)

##### 2. シグナル & イベント接続
* **受信シグナル (Listens)**:
  * `ImageGeorefTool.point_clicked` ➔ `GridInputDialog` を開き基準点を紐付け。

---

#### 4.2 ModelessSectionDialog [SET] (環境設定ダイアログ)
* **ID / Class**: `ModelessSectionDialog` (設定用)
* **格納ファイル**: `src/ui/dialogs.py` (UI構築: `Tab3SettingsMixin._create_tab3_ui`)
* 🔗 **対応機能アーキテクチャ**: `FEAT-02: SYMBOLOGY_LABEL_SYNC`

##### 1. 状態・排他制御ルール
* 設定適用時、`SymbologyMixin.apply_symbology` を経由してQGISキャンバス上のシンボルスタイルを動的に再構築する。

---

#### 4.3 ModelessSectionDialog [OUT] (座標CSV出力ダイアログ)
* **ID / Class**: `ModelessSectionDialog` (出力用)
* **格納ファイル**: `src/ui/dialogs.py` (UI構築: `Tab2DigitizingMixin._create_tab4_ui`)
* 🔗 **対応機能アーキテクチャ**: `FEAT-04: SURVEY_CSV_EXPORT`

##### 1. シグナル & イベント接続
* **受信シグナル (Listens)**:
  * CSV書き出し実行ボタン ➔ `_on_export_csv_clicked()` ➔ `transform.export_points_to_csv()` を実行。

---

### Phase 5: メインキャンバス打刻・属性編集オペレーションフェーズ

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

##### 4. 状態・排他制御ルール (T-0037, T-0039)
* **新規モード**: 既存フィーチャのスナップ処理・ホバーマーカー表示をスキップし、一律で `canvas_clicked` を発火する。
* **編集モード**: 15px以内のスナップ判定を行い、ヒット時は `existing_point_selected` を発火。ヒットしなかった場合は `blank_click_in_edit_mode` を発火し、Dock側の選択状態を解除させる。
