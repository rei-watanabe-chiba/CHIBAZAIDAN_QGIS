"""
/***************************************************************************
 PointerGeocoding Plugin - Main Dock UI Constants
 ***************************************************************************/

Stage B split (mechanical, logic-preserving): extracted from main_dock.py.
Contains UI string/config constant classes shared across MainDockWidget,
its tab mixins, and the standalone dialog classes in main_dock_dialogs.py.

T-0017 (アプローチA): EXCAVATION_OPTIONS/ATTRIBUTE_OPTIONS は core_logic.py の
ExcavationType/AttributeType Enum の .value から構築し、コンボボックス文字列と
Enum定義の単一情報源化を図る（一覧の中身・順序は変更前と同一）。
"""

from ..logic.core import ExcavationType, AttributeType

# UI Configuration dictionary and layout ratios
class UIConfig:
    MAIN_RATIO = (3, 7)
    ROW_HEIGHT = 32
    SCALE_THRESHOLD = 500
    LABEL_SIZE_REF = 10
    SYMBOL_SIZE_REF = 4.0
    SYMBOL_SIZE_POINT = 3.0
    # --- T-0048 (人手確認フィードバック対応): fixed pixel width for
    # tab3_settings.py's compact form-row labels (サイズ/線幅/線色/間隔), so
    # every DOUBLE_SPINBOX_ROW/COLOR_BUTTON_ROW/SPINBOX_ROW input widget in a
    # given ROW_GROUP starts at the same x-offset regardless of its label's
    # character count. Sized for the widest of the four labels, "サイズ" (3
    # full-width chars) at the UI's 9pt base font (style.py's PANEL_STYLE):
    # a full-width glyph renders roughly at the font's em-box width (~14px
    # at 9pt/96dpi), so 3 chars need ~42px; 44px keeps a couple of px of
    # breathing room without being noticeably wider than the text. Not
    # applied to the 表示縮尺 section's 大グリッド:/小グリッド: labels (out
    # of scope per user feedback).
    TAB3_ROW_LABEL_WIDTH = 44
    # --- T-0025: fixed width of the right dock (root_widget passed to
    # QDockWidget.setWidget in main_dock.py), so the dock no longer relies
    # on QGIS's default auto-sizing. T-0048 (人手確認フィードバック対応):
    # widened 300 -> 320 so tab3's now fixed-width row labels
    # (TAB3_ROW_LABEL_WIDTH) don't crowd out the DOUBLE_SPINBOX_ROW/
    # COLOR_BUTTON_ROW input widgets beside them. This constant is shared by
    # the whole dock (tab1/tab2/tab3/tab4 all sit in the same root_widget),
    # so the +20px also applies to tab1/tab2/tab4; their rows are built with
    # stretch-ratio layouts (build_flex_row's MAIN_RATIO), so the extra
    # width simply grows their content area proportionally and does not
    # change any fixed-width element on those tabs. ---
    DOCK_WIDTH = 320
    # --- T-0027: fixed height (~6 rows) of the 図面選択リスト panel's
    # QListWidget, so it does not grow unbounded with many drawings and
    # instead scrolls internally. ---
    DRAWING_LIST_HEIGHT = 180

    # --- T-0035: full reset/simplification of the T-0034 margin/spacing
    # constants. T-0034 introduced a large set of finely-subdivided margin
    # constants (DOCK_OUTER_MARGIN, SECTION_GAP, PANEL_CONTAINER_MARGIN_TOP/
    # BOTTOM, PANEL_GROUP_SPACING, PANEL_INNER_SPACING, SEPARATOR_MARGIN_TOP/
    # BOTTOM); per user feedback that this subdivision added no real value,
    # they are replaced by three simple, broadly-reused constants below
    # (COMMON_MARGIN_LR / DIALOG_MARGIN / PANEL_MARGIN). See each call site
    # (main_dock.py / tab1_georef_mixin.py / tab2_digitizing_mixin.py /
    # tab3_settings_mixin.py / start_dialog.py / main_dock_dialogs.py) for
    # how they are applied. ---
    # Left/right margin for the top-level container of start_dialog.py,
    # tab1_georef_mixin.py, tab3_settings_mixin.py and tab2_digitizing_mixin.
    # py's _create_tab4_ui() (出力 dialog content).
    COMMON_MARGIN_LR = 8
    # Top/bottom margin and vertical setSpacing() for the top-level layout of
    # each "dialog content" widget: start_dialog.py's main_layout; the four
    # dialog classes in main_dock_dialogs.py (ImageDialog/GridInputDialog/
    # FeatureCreateDialog/ModelessSectionDialog); and the top-level containers
    # of tab1_georef_mixin.py / tab3_settings_mixin.py / tab2_digitizing_mixin.
    # py's _create_tab4_ui().
    DIALOG_MARGIN = 8
    # Top/bottom/left/right margin and vertical setSpacing() for
    # main_dock.py's root_layout (replacing the former separate
    # DOCK_OUTER_MARGIN), and the top-level container + individual panels
    # (info/attr/focus/drawing-list) of tab2_digitizing_mixin.py's
    # _create_tab2_ui() (replacing the former PANEL_GROUP_SPACING/
    # PANEL_CONTAINER_MARGIN_TOP/PANEL_CONTAINER_MARGIN_BOTTOM/
    # PANEL_INNER_SPACING).
    PANEL_MARGIN = 8
    # tab2_digitizing_mixin.py: layout.setContentsMargins(4, PANEL_MARGIN, 16,
    # PANEL_MARGIN) (Tab2 panel container; left/right kept as their own
    # dedicated constants below -- right margin is intentionally wider than
    # the others to leave room for the QScrollArea's scrollbar).
    PANEL_CONTAINER_MARGIN_LEFT = 4
    PANEL_CONTAINER_MARGIN_RIGHT = 16
    SEPARATOR_MARGIN = 12
    HEADER_LINE_SPACING = 4
    # main_dock.py: top_layout.setSpacing(6) (画像/設定/出力/保存 button row;
    # kept unchanged, out of scope for the T-0035 reset).
    TOP_ROW_BUTTON_SPACING = 6


class UIDialogSizes:
    """T-0025: dialog-level width/height constants for the modeless/modal
    dialogs built in main_dock_dialogs.py, extracted from the previously
    hardcoded resize()/setMinimumWidth() call sites so they have a single,
    named source of truth alongside UIConfig."""

    IMAGE_DIALOG_WIDTH = 1100
    IMAGE_DIALOG_HEIGHT = 650
    GRID_DIALOG_MIN_WIDTH = 380
    # 【ローカル編集】ModelessSectionDialoのサイズ指定を追加
    SETTINGS_DIALOG_WIDTH = 400
    SETTINGS_DIALOG_HEIGHT = 500
    OUT_DIALOG_WIDTH = 400
    OUT_DIALOG_HEIGHT = 300

class UILabels:
    DOCK_TITLE = "点群座標取得パネル"
    BTN_SAVE_PROJECT = "💾 プロジェクトを保存"
    # --- T-0034: tab display strings shortened to English abbreviations
    # (画像管理/遺物点作成/設定/CSV出力 -> IMG/PLOT/SET/OUT); internal module/
    # class/variable/method identifiers (tab1/tab2/tab3/output_*) are
    # unchanged, this only affects the strings shown in the UI. ---
    TAB_1_TITLE = "IMG"
    TAB_2_TITLE = "PLOT"
    TAB_3_TITLE = "SET"
    # --- T-0024: right-dock top button row (image / settings / output / save) ---
    BTN_TOP_IMAGE = "画像"
    BTN_TOP_SETTINGS = "設定"
    BTN_TOP_OUTPUT = "出力"
    BTN_TOP_SAVE = "保存"
    # --- T-0034: renamed from OUTPUT_DIALOG_TITLE to TAB_4_TITLE to align
    # with the TAB_1_TITLE/TAB_2_TITLE/TAB_3_TITLE naming pattern used by
    # the other three dialogs' content mixins (see main_dock.py's
    # self.tab4_container / tab2_digitizing_mixin.py's _create_tab4_ui). ---
    TAB_4_TITLE = "OUT"
    # --- Settings Tab ---
    TAB3_SECTION_REF_SYMBOL   = "基準点"
    TAB3_SECTION_POINT_SYMBOL = "遺物点"
    TAB3_SECTION_LABEL_SYMBOL = "ラベル"
    TAB3_SECTION_SCALE   = "表示縮尺"

    TAB3_LBL_SYMBOL = "シンボル:"
    TAB3_LBL_COLOR  = "カラー:"

    TAB3_LBL_SIZE       = "サイズ"
    TAB3_LBL_LINEWIDTH  = "線幅"
    TAB3_LBL_LINECOLOR  = "線色"
    TAB3_BTN_COLOR      = "カラーを選択..."
    TAB3_POINT_FILL_ON  = "塗りあり"
    TAB3_POINT_FILL_OFF = "塗りなし"

    TAB3_LABEL_SIZE      = "サイズ"
    TAB3_LABEL_HALO      = "白枠"
    TAB3_LABEL_HALO_ON   = "白線あり"
    TAB3_LABEL_HALO_OFF  = "白線なし"
    TAB3_LABEL_OFFSET    = "間隔"

    TAB3_SCALE_MAJOR     = "大グリッド:"
    TAB3_SCALE_MINOR     = "小グリッド:"
    TAB3_SCALE_ALWAYS    = "常時"
    TAB3_SCALE_SPECIFY   = "指定"
    TAB3_BTN_APPLY       = "✅ 適用"
    TAB3_APPLY_SUCCESS   = "設定を適用しました。"
    TAB3_APPLY_NO_SESSION = "セッションが開始されていません。"
    TAB1_INFO_HEADER = "📌 画像管理・事前配置ワークフロー"
    TAB1_INFO_STEP1 = "手順 1: 画像ファイルを選択し、「確定」を押してください。"
    TAB1_INFO_STEP2 = "手順 2: 「基準点設定」を押してプレビュー画面から基準点を配置してください。"
    TAB1_INFO_IMAGE_REF = "画像: {name} | 基準点: {count} / 4 点"
    TAB1_INFO_TRANSFORM_DONE = "状態: 変換済 (残差を確認してください)"
    TAB1_INFO_RESIDUAL_INIT = "残差: 未実行"
    IMAGE_FILE = "画像ファイル:"
    LAYER_NAME = "レイヤ名:"
    SAVE_IMAGE_NAME = "レイヤ名:"
    BTN_BROWSE = "参照..."
    BTN_CONFIRM_IMAGE = "確定"
    BTN_SETUP_REF_POINTS = "基準点設定"
    GROUP_REF_POINTS = "基準点設定"
    PREVIEW_DIALOG_TITLE = "基準点設定プレビュー"
    PREVIEW_HINT = "💡 プレビュー画像をクリックして基準点（最大4点）を配置してください。"
    REF_TABLE_HEADERS = ["基準点名", "画像ピクセル", "実座標 X (m)", "実座標 Y (m)"]
    BTN_DELETE_REF = "選択行を削除"
    BTN_CLEAR_REFS = "全基準点をクリア"
    GROUP_TRANSFORM = "2. 座標変換・実空間配置"
    TRANSFORM_INIT_STATUS = "状態: 未実行 (最低2点以上の基準点が必要です)"
    BTN_TRANSFORM = "座標変換"
    BTN_EXPORT_LAYER = "レイヤ出力"
    GRID_DIALOG_TITLE = "基準点グリッド設定"
    GRID_X_LABEL = "大グリッドＸ"
    GRID_Y_LABEL = "大グリッドＹ"
    GRID_SUB_LABEL = "小グリッド (00-99)"
    BTN_DELETE_SELECTED_POINT = "選択点を削除"
    BTN_CONFIRM = "確定"
    BTN_CANCEL = "キャンセル"
    ERR_GRID_NOT_FOUND = "エラー: グリッド '{grid}' の座標データがCSV内に存在しません。"
    ERR_GY_NOT_FOUND = "エラー: Yグリッド '{gy}' はグリッドCSVに存在しません。"
    ERR_GRID_DUPLICATE = "エラー: 基準点 '{grid}' は既に登録されています。"
    STATUS_GRID_FOUND = "グリッド: {grid}\n実座標: X = {rx:.3f} m, Y = {ry:.3f} m"
    MSG_LAYER_CONFIRMED = "レイヤ名を「{name}」に確定しました。「基準点設定」を押して基準点を配置してください。"
    ERR_TRANSFORM_NOT_CALCULATED = "先に「座標変換」を実行して残差を確認してください。"
    MSG_TRANSFORM_SUCCESS = "座標変換パラメータを計算しました。残差を確認して「レイヤ出力」を実行してください。"
    GROUP_FOCUS = "マスター制御: フォーカスモード"
    BTN_FOCUS_OFF = "🎯 フォーカスモード (OFF)"
    BTN_FOCUS_ON = "🎯 フォーカスモード (ON)"
    BTN_FILTER_OFF = "フィルター: OFF"
    BTN_FILTER_ON = "フィルター: ON"
    BTN_FILTER_SETTINGS = "設定"
    FILTER_DIALOG_TITLE = "表示フィルター設定"
    BTN_CLEAR_ALL = "すべてクリア"
    FILTER_TARGET_DRAWING = "対象図面"
    FILTER_DRAWING_SELECTED = "選択図面"
    FILTER_DRAWING_ALL = "全図面"
    FILTER_ATTRIBUTES = "属性"
    FILTER_EXCAVATION = "出土形態"
    FILTER_FEATURE = "遺構名"
    OPACITY_LABEL = "透明度:"
    DRAWING_NAME = "対象図面:"
    DRAWING_UNSPECIFIED = "-- 未指定 --"
    BTN_DELETE_POINT = "削除"
    EXCAVATION_TYPE = "出土形態:"
    EXCAVATION_OPTIONS = [ExcavationType.GRID.value, ExcavationType.FEATURE.value]
    FEATURE_SELECTOR = "遺構名:"
    UNREGISTERED = "未登録"
    FEATURE_NEW_OPTION = "未登録"
    POINT_NAME = "点名:"
    BRANCH_NO = "枝番:"
    ATTRIBUTE_CODE = "属性:"
    ATTRIBUTE_OPTIONS = [
        AttributeType.S.value,
        AttributeType.P.value,
        AttributeType.C.value,
        AttributeType.SP.value,
    ]
    # T-0032: display-only labels for combo_attribute; the underlying
    # AttributeType values (S/P/C/SP) stored on features/used in comparisons
    # are unchanged (see Tab2DigitizingMixin._get_attribute_value/_set_attribute_value).
    ATTRIBUTE_DISPLAY_MAP = {
        AttributeType.S.value: "S:石器",
        AttributeType.P.value: "P:土器",
        AttributeType.C.value: "C:炭化物",
        AttributeType.SP.value: "SP",
    }
    BTN_COLOR_PICKER = "カラー選択"
    GROUP_CSV = "CSV出力設定"

    # --- T-0027: 4-panel main area restructure (点情報/属性/フォーカスモード/図面選択リスト) ---
    GROUP_POINT_INFO = "点情報"
    GROUP_ATTRIBUTE_PANEL = "属性パネル"
    GROUP_DRAWING_LIST = "図面選択リスト"
    # --- 軽微修正: 図面選択リストパネルへの基準点レイヤ表示/非表示トグル追加 ---
    LBL_REF_POINT_VISIBILITY = "基準点: "
    RADIO_VISIBLE = "表示"
    RADIO_HIDDEN = "非表示"
    LBL_INFO_GROUP_OR_FEATURE = "出土形態:"
    LBL_INFO_POINT_BRANCH = "点名/枝番:"
    LBL_INFO_COORDS = "XY座標:"
    BTN_CREATE_FEATURE = "遺構管理"
    FEATURE_MANAGE = "遺構管理"
    FEATURE_MANAGE_DIALOG_TITLE = "遺構管理"
    FEATURE_CREATE_DIALOG_TITLE = "遺構管理"
    STATUS_MSG_NEW_FEATURE = "{feature} : 新規作成"
    STATUS_MSG_EDIT_FEATURE = "{feature} : 入力した設定を反映"
    NEW_FEATURE_NAME = "新規遺構名:"
    # --- T-0040: 新規モード「解除」時のクリック位置への点名・枝番入力ダイアログ ---
    POINT_NAME_ENTRY_DIALOG_TITLE = "点名・枝番入力"
    # --- T-0032: 点情報パネル ステータス帯 文言 ---
    STATUS_NEW_POINT = "新規点作成"
    STATUS_EDIT_POINT = "既設点編集"
    STATUS_ERR_FEATURE_REQUIRED = "遺構名未指定"
    STATUS_ERR_OUT_OF_BOUNDS = "図面範囲外"
    STATUS_ERR_DUPLICATE = "点名重複エラー"
    # --- T-0036: tab2先頭の新規/編集モード切替トグル、点情報パネルの
    # モード連動ボタンエリア(新規モード=自動連番/解除トグル、編集モード=削除)。
    # 命名はtab1_georef_mixin.pyの新規追加/編集削除トグルの命名パターンに揃える。 ---
    TAB2_MODE_NEW = "新規"
    TAB2_MODE_EDIT = "編集"
    AUTONUM_MODE_AUTO = "自動連番"
    AUTONUM_MODE_RELEASE = "解除"
    ENCODING = "文字コード:"
    RADIO_UTF8 = "UTF-8 (BOM付き)"
    RADIO_SJIS = "Shift-JIS"
    CSV_DESTINATION = "出力先:"
    BTN_EXPORT_CSV = "📄 CSV出力"
    UNLOADED = "未読み込み"
    TRANSFORM_HELMERT = "2点ヘルマート変換"
    TRANSFORM_AFFINE = "{count}点アフィン変換"
    STATUS_NEED_MORE_REFS = "基準点登録数: {count} 点 (※最低2点以上の基準点が必要です)"
    STATUS_INPUT_COORDS = "基準点登録数: {count} 点 (実座標 X, Y をテーブル内に入力してください)"
    STATUS_READY_TRANSFORM = "基準点登録数: {count} 点 ({mode}の実行準備が完了しました)"

class UIPlaceholders:
    IMAGE_PATH = "画像ファイルを選択してください"
    IMAGE_NAME = "例: plan_01"
    NEW_FEATURE = "例: SK01, Pit12"
    BRANCH_NO = "例: a, 1 (未入力可)"
    POINT_NAME_SP = "半角英数字・ハイフン・アンダースコアのみ (例: SP-01)"
    CSV_PATH = "CSV出力先ファイルを指定してください"

class UIDialogTitles:
    BROWSE_IMAGE = "図面画像ファイルを選択"
    IMAGE_FILTER = "画像ファイル (*.png *.jpg *.jpeg *.tif *.tiff *.bmp);;すべてのファイル (*.*)"
    COLOR_PICKER = "遺構カラーを選択"
    BROWSE_CSV = "CSV出力先を指定"
    CSV_FILTER = "CSVファイル (*.csv)"
    INPUT_REF_TITLE = "基準点名の入力"
    INPUT_REF_PROMPT = "基準点名を入力してください (例: K-1, Ref-1):"

class UIMessages:
    ERR_TITLE_INPUT = "入力エラー"
    ERR_TITLE_FILE = "ファイルエラー"
    ERR_TITLE_LOAD = "読み込みエラー"
    ERR_TITLE_DUPLICATE = "重複エラー"
    ERR_TITLE_GENERIC = "エラー"
    MSG_TITLE_INFO = "通知"
    MSG_TITLE_LIMIT = "上限通知"
    MSG_CONFIRM_TITLE = "削除確認"
    MSG_CONFIRM_IMAGE_FIRST = "編集対象のレイヤを選択してから「基準点設置」を実行してください。"
    ERR_INVALID_IMAGE = "有効な画像ファイルを選択してください。"
    ERR_SOURCE_HAS_WORLDFILE = (
        "選択した画像には既にワールドファイルが付随しています。"
        "本プラグインは座標変換により独自のワールドファイルを生成するため、"
        "既存のワールドファイルを持つ画像は使用できません。"
    )
    ERR_REQUIRED_IMAGE_NAME = "レイヤ名を入力してください。"
    ERR_INVALID_IMAGE_NAME = "レイヤ名に使用できない文字 (\\ / : * ? \" < > |) が含まれています。"
    MSG_IMAGE_LOADED_TITLE = "画像読み込み完了"
    MSG_IMAGE_LOADED = "画像をプレビュー表示しました: {name}"
    ERR_PREVIEW_FAILED = "プレビュー画像の読み込みに失敗しました:\n{msg}"
    MSG_LIMIT_REFS = "基準点は最大4点まで登録できます。\n不要な基準点を削除してください。"
    ERR_DUPLICATE_REF = "同名の基準点 '{name}' が既に存在します。\n別の名称を入力してください。"
    ERR_DUPLICATE_LAYER_NAME = "同名のレイヤ '{name}' が既に存在します。\n別の名称を入力してください。"
    MSG_SELECT_REF_ROW = "削除する基準点を行選択してください。"
    ERR_MIN_2_REFS = "最低2点以上の基準点が必要です。"
    ERR_INPUT_REAL_COORDS = "基準点 '{name}' の実座標 (X, Y) を入力してください。"
    ERR_WORLDFILE_FAILED = "ワールドファイル生成に失敗しました:\n{msg}"
    ERR_CANVAS_PLACEMENT_FAILED = "メインキャンバスへの画像配置に失敗しました:\n{msg}"
    MSG_GEOREF_COMPLETE_TITLE = "事前ジオリファレンス完了"
    MSG_GEOREF_COMPLETE = "ワールドファイルを生成し、画像を実空間に配置しました。「遺物点作成」タブで打刻を開始できます。"
    MSG_SAVE_TITLE = "プロジェクト保存"
    MSG_SAVE_SUCCESS = "プロジェクトとGeoPackageの変更を上書き保存しました。"
    MSG_SAVE_FAILED = "プロジェクトの保存に失敗しました。"
    MSG_SELECT_FEATURE_NAME = "対象の遺構名をセレクタから選択してください。"
    MSG_COLOR_APPLIED_TITLE = "カラー適用"
    MSG_COLOR_APPLIED = "遺構 '{feature}' の全打刻点 ({count}件) にカラー {color} を適用しました。"
    MSG_RENAME_LAYER_SUCCESS = "レイヤ名を '{old}' から '{new}' に変更しました。"
    ERR_POINT_NAME_REQUIRED = "点名（点番号）を入力してください。"
    ERR_NEW_FEATURE_REQUIRED = "新規遺構名を入力してください。"
    # --- T-0041: PointNameEntryDialog重複エラー文言を点情報パネルの
    # UILabels.STATUS_ERR_DUPLICATE("点名重複エラー")と揃えるためのプレフィックス付き
    # フォーマット。core_logic.build_point_ident()が返す識別子文字列と組み合わせて使う。 ---
    ERR_POINT_NAME_DUPLICATE = UILabels.STATUS_ERR_DUPLICATE + ": {ident}"
    MSG_DELETE_SUCCESS_TITLE = "ポイント削除"
    MSG_DELETE_SUCCESS = "ポイントを削除しました。"
    MSG_EXPORT_CSV_TITLE = "CSV出力完了"

    # --- T-0025: undefined-literal cleanup (main_dock_dialogs.py) ---
    MSG_CONFIRM_DELETE_REF = "この基準点を削除しますか？"

    # --- T-0025: undefined-literal cleanup (tab1_georef_mixin.py) ---
    MSG_CONFIRM_DELETE_LAYER_TITLE = "レイヤ削除"
    MSG_CONFIRM_DELETE_LAYER = "レイヤ '{name}' を削除しますか？\n関連するファイルやメタデータも削除されます。"
    MSG_CONFIRM_POINTS_EXIST_TITLE = "ポイントが存在します"
    MSG_CONFIRM_POINTS_EXIST = (
        "この図面に関連づけられた打刻点が存在します。\n"
        "削除を続行すると、これらの点の対象図面はクリアされグローバル点になります。\n"
        "続行しますか？"
    )
    MSG_DELETE_LAYER_SUCCESS_TITLE = "削除完了"
    MSG_DELETE_LAYER_SUCCESS = "レイヤ '{name}' を削除しました。"
    ERR_LAYER_META_NOT_FOUND = "レイヤ '{name}' のメタデータが見つかりません。"
    MSG_RENAME_LAYER_SUCCESS_TITLE = "レイヤ名変更完了"
    MSG_TRANSFORM_COMPLETE_TITLE = "座標変換完了"
    ERR_IMAGE_FILE_NOT_FOUND = "対象画像ファイルが見つかりません。"

    # --- T-0025: undefined-literal cleanup (tab2_digitizing_mixin.py) ---
    ERR_TITLE_DIGITIZE = "打刻エラー"
    ERR_DIGITIZE_REQUIRED = "必須項目が未入力のため打刻できません。"
    ERR_TITLE_DUPLICATE_DIGITIZE = "重複打刻エラー"
    MSG_DUPLICATE_POINT = "同じ点（{ident}）が既に登録されています。\n点名または枝番を変更してください。"

    # --- T-0025: undefined-literal cleanup (plugin.py) ---
    MSG_TITLE_PLUGIN = "点群座標取得"
    MSG_UNSAVED_CHANGES_TITLE = "未保存の変更"
    MSG_UNSAVED_CHANGES = (
        "現在のQGISプロジェクトに変更が加えられています。\n"
        "保存せずに新しいセッションを開始すると、未保存のデータは破棄されます。\n"
        "続行しますか？"
    )
    ERR_TITLE_SESSION = "セッションエラー"
    ERR_SESSION_INIT_FAILED = "セッションの初期化に失敗しました:\n{message}"
    MSG_STEP1_READY = (
        "Step 1（セッション管理基盤）の準備が完了しました。"
        "ドックパネルモジュール (Step 2) を待機しています。"
    )


MAIN_RATIO = UIConfig.MAIN_RATIO
