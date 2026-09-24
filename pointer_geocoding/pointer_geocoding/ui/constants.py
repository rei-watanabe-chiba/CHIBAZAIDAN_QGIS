"""
/***************************************************************************
 PointerGeocoding Plugin - Main Dock UI Constants
 ***************************************************************************/

UI string/config constant classes shared across the dock and dialog modules.

EXCAVATION_OPTIONS/ATTRIBUTE_OPTIONS are built from ExcavationType/
AttributeType Enum's .value, keeping the combo box strings and Enum
definition as a single source of truth.
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
    # Fixed pixel width for compact settings-panel form-row labels
    # (サイズ/線幅/線色/間隔), so every input widget in a given ROW_GROUP
    # starts at the same x-offset regardless of its label's character
    # count. Sized for the widest of the four labels, "サイズ" (3 full-width
    # chars) at the UI's 9pt base font: a full-width glyph renders roughly
    # at the font's em-box width (~14px at 9pt/96dpi), so 3 chars need
    # ~42px; 44px keeps a couple of px of breathing room. Not applied to
    # the 表示縮尺 section's 大グリッド:/小グリッド: labels.
    TAB3_ROW_LABEL_WIDTH = 44
    # Fixed width of the right dock (root_widget passed to
    # QDockWidget.setWidget in main_dock.py), so the dock no longer relies
    # on QGIS's default auto-sizing. Wide enough that the settings panel's
    # fixed-width row labels (TAB3_ROW_LABEL_WIDTH) don't crowd out the
    # input widgets beside them. Shared by the whole dock (all tabs sit in
    # the same root_widget), so other tabs' stretch-ratio rows simply grow
    # their content area proportionally without any fixed-width impact.
    DOCK_WIDTH = 320
    # Fixed height (~6 rows) of the 図面選択リスト panel's QListWidget, so
    # it does not grow unbounded with many drawings and instead scrolls
    # internally.
    DRAWING_LIST_HEIGHT = 180

    # Left/right margin for top-level dialog/tab content containers.
    COMMON_MARGIN_LR = 8
    # Top/bottom margin and vertical spacing for "dialog content" widgets
    # (start dialog, modal/modeless dialogs).
    DIALOG_MARGIN = 8
    # Top/bottom/left/right margin and vertical spacing for the dock's root
    # layout and Tab2's panel containers (info/attr/focus/drawing-list).
    PANEL_MARGIN = 8
    # Tab2 panel container left/right margins; right is intentionally wider
    # than the others to leave room for the QScrollArea's scrollbar.
    PANEL_CONTAINER_MARGIN_LEFT = 4
    PANEL_CONTAINER_MARGIN_RIGHT = 16
    SEPARATOR_MARGIN = 12
    HEADER_LINE_SPACING = 4
    # 画像/設定/出力/保存 button row spacing (top of the dock).
    TOP_ROW_BUTTON_SPACING = 6


class UIDialogSizes:
    """Dialog-level width/height constants for the modeless/modal dialogs,
    kept as a single named source of truth alongside UIConfig."""

    IMAGE_DIALOG_WIDTH = 1100
    IMAGE_DIALOG_HEIGHT = 650
    GRID_DIALOG_MIN_WIDTH = 380
    SETTINGS_DIALOG_WIDTH = 400
    SETTINGS_DIALOG_HEIGHT = 500
    OUT_DIALOG_WIDTH = 400
    OUT_DIALOG_HEIGHT = 300

class UILabels:
    DOCK_TITLE = "点群座標取得パネル"
    BTN_SAVE_PROJECT = "💾 プロジェクトを保存"
    # Tab display strings (shown in UI); internal tab1/tab2/tab3 identifiers
    # are unrelated and unaffected by these display abbreviations.
    TAB_1_TITLE = "IMG"
    TAB_2_TITLE = "PLOT"
    TAB_3_TITLE = "SET"
    # Right-dock top button row (image / settings / output / save)
    BTN_TOP_IMAGE = "画像"
    BTN_TOP_SETTINGS = "設定"
    BTN_TOP_OUTPUT = "出力"
    BTN_TOP_SAVE = "保存"
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
    TRANSFORM_INIT_STATUS = "状態: 未実行 (最低2点以上の基準点と実座標が必要です。揃ったら座標変換を実行してください)"
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
    # 点情報パネル(編集モード)の既設点 編集/削除ボタン
    BTN_EDIT_SELECTED_POINT = "編集"
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
    # Display-only labels for the attribute combo box; the underlying
    # AttributeType values (S/P/C/SP) stored on features and used in
    # comparisons are unaffected by this mapping.
    ATTRIBUTE_DISPLAY_MAP = {
        AttributeType.S.value: "S:石器",
        AttributeType.P.value: "P:土器",
        AttributeType.C.value: "C:炭化物",
        AttributeType.SP.value: "SP",
    }
    BTN_COLOR_PICKER = "カラー選択"
    GROUP_CSV = "CSV出力設定"

    # 4-panel main area: 点情報/属性/フォーカスモード/図面選択リスト
    GROUP_POINT_INFO = "点情報"
    GROUP_ATTRIBUTE_PANEL = "属性パネル"
    GROUP_DRAWING_LIST = "図面選択リスト"
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
    # 新規モード「解除」時のクリック位置への点名・枝番入力ダイアログ
    POINT_NAME_ENTRY_DIALOG_TITLE = "点名・枝番入力"
    # 点情報パネル ステータス帯 文言
    STATUS_NEW_POINT = "新規点作成"
    STATUS_EDIT_POINT = "既設点編集"
    STATUS_MULTI_SELECTED = "{count}件選択中"
    # 点編集ダイアログ(一括変更モード)用
    BULK_KEEP = "(変更しない)"
    BULK_EDIT_TITLE = "点情報一括変更"
    BULK_EDIT_STATUS = "{count}件を更新"
    STATUS_ERR_FEATURE_REQUIRED = "遺構名未指定"
    STATUS_ERR_OUT_OF_BOUNDS = "図面範囲外"
    STATUS_ERR_DUPLICATE = "点名重複エラー"
    # 点名検索(点情報パネルの検索行・INFO表示)
    STATUS_SEARCH_HIT = "検索中 {index}/{total}件"
    STATUS_SEARCH_NOT_FOUND = "該当なし"
    # tab2先頭の新規/編集モード切替トグル。点情報パネルのモード連動ボタン
    # エリア(新規モード=自動連番/解除トグル、編集モード=削除)。
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

class UIPlaceholders:
    IMAGE_PATH = "画像ファイルを選択してください"
    IMAGE_NAME = "例: plan_01"
    NEW_FEATURE = "例: SK01, Pit12"
    BRANCH_NO = "例: a, 1 (未入力可)"
    POINT_NAME_SP = "半角英数字・ハイフン・アンダースコアのみ (例: SP-01)"
    CSV_PATH = "CSV出力先ファイルを指定してください"
    POINT_SEARCH = "点名(完全一致)"

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
    ERR_TITLE_CALC = "計算エラー"
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
    # PointNameEntryDialog重複エラー文言を点情報パネルの
    # UILabels.STATUS_ERR_DUPLICATE("点名重複エラー")と揃えるためのプレフィックス付き
    # フォーマット。core_logic.build_point_ident()が返す識別子文字列と組み合わせて使う。
    ERR_POINT_NAME_DUPLICATE = UILabels.STATUS_ERR_DUPLICATE + ": {ident}"
    MSG_CONFIRM_DELETE_POINT = "選択中の点を削除してよろしいですか？"
    MSG_DELETE_SUCCESS_TITLE = "ポイント削除"
    MSG_DELETE_SUCCESS = "ポイントを削除しました。"
    MSG_CONFIRM_DELETE_POINTS = "選択中の{count}件の点を削除してよろしいですか？"
    MSG_DELETE_SUCCESS_COUNT = "{count}件のポイントを削除しました。"
    MSG_BULK_UPDATE_TITLE = "一括変更"
    MSG_BULK_UPDATE_RESULT = "{updated}件を更新しました。"
    MSG_BULK_UPDATE_SKIPPED = "{skipped}件をスキップしました(内訳: {detail})"
    MSG_BULK_SKIP_SP = "SP属性 {n}件"
    MSG_BULK_SKIP_DUPLICATE = "重複 {n}件"
    MSG_BULK_SKIP_OUT_OF_BOUNDS = "図面範囲外 {n}件"
    MSG_BULK_SKIP_FEATURE_REQUIRED = "遺構名未指定 {n}件"
    MSG_COMMIT_FAILED_TITLE = "保存エラー"
    MSG_COMMIT_FAILED = "変更の保存に失敗したため、変更を取り消しました。"
    MSG_UPDATE_OUT_OF_BOUNDS_TITLE = "図面範囲外"
    MSG_UPDATE_OUT_OF_BOUNDS = (
        "変更先の図面のピクセル範囲外に物理座標があるため、対象図面を変更できませんでした。"
    )
    MSG_EXPORT_CSV_TITLE = "CSV出力完了"

    MSG_CONFIRM_DELETE_REF = "この基準点を削除しますか？"

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

    ERR_TITLE_DIGITIZE = "打刻エラー"
    ERR_DIGITIZE_REQUIRED = "必須項目が未入力のため打刻できません。"
    ERR_TITLE_DUPLICATE_DIGITIZE = "重複打刻エラー"
    MSG_DUPLICATE_POINT = "同じ点（{ident}）が既に登録されています。\n点名または枝番を変更してください。"

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
