from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Iterator

from PySide6.QtCore import QSignalBlocker, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QDesktopServices, QFont, QKeySequence, QPixmap
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFontComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QLayout,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStyle,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .catalog import TagDefinition
from .pictures import EndingPictureIndex
from .path_settings import (
    default_persistent_root,
    ensure_writable_directory,
    is_game_root,
    write_shared_settings,
)
from .reader import (
    HOVER_MODE,
    IGNORE_MODE,
    RUBY_MODE,
    LocalReaderPage,
    ReaderSettings,
    ReaderSettingsStore,
    render_reader_html,
)
from .service import HEROINE_BY_ID, HEROINE_SELECTION_IDS, LegendService, SyncResult


CATEGORY_LABELS = {
    "ending": "ED名",
    "heroine": "結縁相手",
    "survival": "生存",
    "join": "唐門加入",
    "status": "身分・受入れ",
    "movement": "留学・移動",
    "event": "観測済みイベント",
    "manual": "手動タグ",
    "spoiler_candidate": "ネタバレ候補",
}

CATEGORY_COLORS = {
    "ending": "#25633f",
    "heroine": "#9a3f5f",
    "survival": "#116b6b",
    "join": "#285f9a",
    "status": "#8a5b16",
    "movement": "#5e6670",
    "event": "#704b8e",
    "manual": "#39424a",
    "spoiler_candidate": "#9a3f2b",
}

class BodySearchLineEdit(QLineEdit):
    next_requested = Signal()
    previous_requested = Signal()
    escape_requested = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.previous_requested.emit()
            else:
                self.next_requested.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.escape_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class TagSelectionDialog(QDialog):
    def __init__(
        self,
        tags: list[TagDefinition],
        assigned_ids: set[str],
        title: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        heading = QLabel("追加するタグを選択")
        heading.setObjectName("dialogHeading")
        layout.addWidget(heading)

        self.checkboxes: list[tuple[QCheckBox, str]] = []
        for tag in tags:
            checkbox = QCheckBox(tag.label)
            checkbox.setChecked(tag.id in assigned_ids)
            checkbox.setEnabled(tag.id not in assigned_ids)
            layout.addWidget(checkbox)
            self.checkboxes.append((checkbox, tag.id))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("選択したタグを追加")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_tag_ids(self) -> list[str]:
        return [tag_id for checkbox, tag_id in self.checkboxes if checkbox.isChecked() and checkbox.isEnabled()]


class ReaderSettingsDialog(QDialog):
    def __init__(self, value: ReaderSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("本文表示設定")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont(value.font_family))
        form.addRow("本文フォント", self.font_combo)

        self.size_spin = QSpinBox()
        self.size_spin.setRange(8, 48)
        self.size_spin.setSuffix(" px")
        self.size_spin.setValue(value.font_size)
        form.addRow("本文サイズ", self.size_spin)

        self.ruby_combo = QComboBox()
        self.ruby_combo.addItem("ルビとして表示", RUBY_MODE)
        self.ruby_combo.addItem("読みを無視", IGNORE_MODE)
        self.ruby_combo.addItem("カーソルを置いたときに表示", HOVER_MODE)
        index = self.ruby_combo.findData(value.ruby_mode)
        self.ruby_combo.setCurrentIndex(max(0, index))
        form.addRow("括弧内の読み", self.ruby_combo)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self) -> ReaderSettings:
        return ReaderSettings(
            self.font_combo.currentFont().family(),
            self.size_spin.value(),
            str(self.ruby_combo.currentData()),
        )


class EndingPictureDialog(QDialog):
    def __init__(self, title: str, picture_path: Path | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 680)
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setMinimumSize(640, 420)
        if picture_path is not None:
            pixmap = QPixmap(str(picture_path))
            if not pixmap.isNull():
                label.setPixmap(pixmap)
                label.setScaledContents(False)
                label.resize(pixmap.size())
        scroll.setWidget(label)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("閉じる")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class PathSettingsDialog(QDialog):
    def __init__(self, service: LegendService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("パス設定")
        self.setMinimumWidth(720)
        self._game_root = service.paths.game_root
        self._legend_directory = service.paths.legend_directory

        layout = QVBoxLayout(self)

        game_group = QGroupBox("ゲーム本体の場所")
        game_layout = QVBoxLayout(game_group)
        game_description = QLabel(
            "Mortal.exeとBepInExの場所を確認するために使用します。"
            "ゲームや伝説の保存先は変更しません。"
        )
        game_description.setWordWrap(True)
        game_description.setObjectName("mutedLabel")
        game_layout.addWidget(game_description)
        game_row = QHBoxLayout()
        self.game_root_edit = QLineEdit(str(self._game_root))
        self.game_root_edit.setReadOnly(True)
        game_button = QPushButton("指定")
        game_button.clicked.connect(self._select_game_root)
        game_row.addWidget(self.game_root_edit, 1)
        game_row.addWidget(game_button)
        game_layout.addLayout(game_row)
        layout.addWidget(game_group)

        legend_group = QGroupBox("伝説TXT・ED画像の保存先")
        legend_layout = QVBoxLayout(legend_group)
        legend_description = QLabel(
            "MODのエクスポート保存先を上書きします。"
            "ゲーム標準のLegendフォルダより優先されます。"
        )
        legend_description.setWordWrap(True)
        legend_description.setObjectName("mutedLabel")
        legend_layout.addWidget(legend_description)
        legend_row = QHBoxLayout()
        self.legend_directory_edit = QLineEdit(str(self._legend_directory))
        self.legend_directory_edit.setReadOnly(True)
        legend_button = QPushButton("保存先を変更")
        legend_button.clicked.connect(self._select_legend_directory)
        default_button = QPushButton("標準の保存先に戻す")
        default_button.clicked.connect(self._restore_default_legend_directory)
        legend_row.addWidget(self.legend_directory_edit, 1)
        legend_row.addWidget(legend_button)
        legend_row.addWidget(default_button)
        legend_layout.addLayout(legend_row)
        layout.addWidget(legend_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("設定を保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _select_game_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "活俠傳ゲームフォルダを指定", str(self._game_root)
        )
        if not selected:
            return
        candidate = Path(selected).resolve()
        if not is_game_root(candidate):
            QMessageBox.warning(
                self,
                "ゲームフォルダを確認できません",
                "Mortal.exe、BepInEx\\plugins、BepInEx\\configがあるフォルダを指定してください。",
            )
            return
        self._game_root = candidate
        self.game_root_edit.setText(str(candidate))

    def _select_legend_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "伝説TXT・ED画像の保存先を変更",
            str(self._legend_directory),
            QFileDialog.Option.ShowDirsOnly,
        )
        if not selected:
            return
        try:
            candidate = ensure_writable_directory(Path(selected))
        except OSError as exception:
            QMessageBox.warning(self, "保存先を使用できません", str(exception))
            return
        self._legend_directory = candidate
        self.legend_directory_edit.setText(str(candidate))

    def _restore_default_legend_directory(self) -> None:
        self._legend_directory = default_persistent_root() / "Legend"
        self.legend_directory_edit.setText(str(self._legend_directory))

    def values(self) -> tuple[Path, Path]:
        return self._game_root, self._legend_directory


class LegendMainWindow(QMainWindow):
    def __init__(self, service: LegendService) -> None:
        super().__init__()
        self.service = service
        self.current_legend_id: int | None = None
        self.current_body_text = ""
        self._directory_signature: tuple[int, int, int] | None = None
        self._refreshing = False
        self.reader_settings_store = ReaderSettingsStore(self.service.paths.viewer_settings_path)
        self.reader_settings = self.reader_settings_store.load()
        self.picture_index = EndingPictureIndex(self.service.paths.pictures_directory)

        self.setWindowTitle("活俠傳 伝説管理")
        self.resize(1480, 900)
        self.setMinimumSize(1040, 680)
        self._build_actions()
        self._build_ui()
        self._apply_style()

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self.refresh_list)
        self.search_edit.textChanged.connect(lambda: self.search_timer.start())

        self.monitor_timer = QTimer(self)
        self.monitor_timer.setInterval(3000)
        self.monitor_timer.timeout.connect(self._poll_directories)
        self.monitor_timer.start()

        self.sync_all(show_result=False)

    def _build_actions(self) -> None:
        style = self.style()
        self.sync_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_BrowserReload), "再読込", self
        )
        self.sync_action.setShortcut(QKeySequence.StandardKey.Refresh)
        self.sync_action.triggered.connect(self.sync_all)

        self.open_folder_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon), "伝説フォルダを開く", self
        )
        self.open_folder_action.triggered.connect(self.open_legend_directory)

        self.backup_action = QAction(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), "DBをバックアップ", self
        )
        self.backup_action.triggered.connect(self.create_backup)

        self.reader_settings_action = QAction("本文表示設定", self)
        self.reader_settings_action.triggered.connect(self.open_reader_settings)

        self.body_search_action = QAction("本文検索", self)
        self.body_search_action.setShortcut(QKeySequence.StandardKey.Find)
        self.body_search_action.triggered.connect(self.open_body_search)

        self.path_settings_action = QAction("パス設定", self)
        self.path_settings_action.triggered.connect(self.open_path_settings)

        self.library_panel_action = QAction("一覧", self)
        self.library_panel_action.setCheckable(True)
        self.library_panel_action.setChecked(True)
        self.library_panel_action.setToolTip("伝説一覧を表示または非表示にします")
        self.library_panel_action.toggled.connect(self._set_library_panel_visible)

        self.detail_panel_action = QAction("詳細", self)
        self.detail_panel_action.setCheckable(True)
        self.detail_panel_action.setChecked(True)
        self.detail_panel_action.setToolTip("詳細サイドバーを表示または非表示にします")
        self.detail_panel_action.toggled.connect(self._set_detail_panel_visible)

    def _build_ui(self) -> None:
        toolbar = QToolBar("メイン", self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.addAction(self.sync_action)
        toolbar.addAction(self.open_folder_action)
        toolbar.addSeparator()
        toolbar.addAction(self.backup_action)
        toolbar.addSeparator()
        toolbar.addAction(self.reader_settings_action)
        toolbar.addAction(self.body_search_action)
        toolbar.addAction(self.path_settings_action)
        toolbar.addSeparator()
        toolbar.addAction(self.library_panel_action)
        toolbar.addAction(self.detail_panel_action)
        self.addToolBar(toolbar)

        self.root_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.root_splitter.setChildrenCollapsible(False)
        self.library_panel = self._build_library_panel()
        self.reader_panel = self._build_reader_panel()
        self.detail_panel = self._build_detail_panel()
        self.root_splitter.addWidget(self.library_panel)
        self.root_splitter.addWidget(self.reader_panel)
        self.root_splitter.addWidget(self.detail_panel)
        self.root_splitter.setSizes([560, 500, 420])
        self.root_splitter.setStretchFactor(0, 0)
        self.root_splitter.setStretchFactor(1, 1)
        self.root_splitter.setStretchFactor(2, 0)
        self.setCentralWidget(self.root_splitter)

        self.status_label = QLabel("準備中")
        self.statusBar().addPermanentWidget(self.status_label)

    def _build_library_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("libraryPanel")
        panel.setMinimumWidth(520)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        heading = QLabel("伝説一覧")
        heading.setObjectName("panelHeading")
        layout.addWidget(heading)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("ED名、結縁相手、本文を検索")
        self.search_edit.setClearButtonEnabled(True)
        layout.addWidget(self.search_edit)

        self.legend_tree = QTreeWidget()
        self.legend_tree.setObjectName("legendTree")
        self.legend_tree.setHeaderLabels(["ED", "結縁", "日時", "状態", "タグ"])
        self.legend_tree.setRootIsDecorated(False)
        self.legend_tree.setAlternatingRowColors(True)
        self.legend_tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.legend_tree.setUniformRowHeights(False)
        self.legend_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header = self.legend_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.legend_tree.setColumnWidth(0, 150)
        self.legend_tree.setColumnWidth(1, 72)
        self.legend_tree.setColumnWidth(2, 86)
        self.legend_tree.setColumnWidth(3, 48)
        self.legend_tree.currentItemChanged.connect(self._on_legend_selected)
        layout.addWidget(self.legend_tree, 1)

        self.library_count = QLabel("0件")
        self.library_count.setObjectName("mutedLabel")
        layout.addWidget(self.library_count)
        return panel

    def _build_reader_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("readerPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        self.title_label = QLabel("伝説を選択してください")
        self.title_label.setObjectName("readerTitle")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.subtitle_label = QLabel("")
        self.subtitle_label.setObjectName("mutedLabel")
        self.subtitle_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.subtitle_label.setWordWrap(True)
        layout.addWidget(self.subtitle_label)

        self.top_tags_frame = QFrame()
        self.top_tags_frame.setObjectName("topTagsFrame")
        top_tags_layout = QHBoxLayout(self.top_tags_frame)
        top_tags_layout.setContentsMargins(0, 0, 0, 0)
        top_tags_layout.setSpacing(8)
        top_tags_heading = QLabel("タグ")
        top_tags_heading.setObjectName("mutedLabel")
        top_tags_layout.addWidget(top_tags_heading)
        self.top_tag_scroll = QScrollArea()
        self.top_tag_scroll.setObjectName("topTagScroll")
        self.top_tag_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.top_tag_scroll.setWidgetResizable(False)
        self.top_tag_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.top_tag_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.top_tag_scroll.setFixedHeight(34)
        self.top_tag_container = QWidget()
        self.top_tag_layout = QHBoxLayout(self.top_tag_container)
        self.top_tag_layout.setContentsMargins(1, 1, 1, 1)
        self.top_tag_layout.setSpacing(6)
        self.top_tag_layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        self.top_tag_scroll.setWidget(self.top_tag_container)
        top_tags_layout.addWidget(self.top_tag_scroll, 1)
        self.top_tags_frame.setVisible(False)
        layout.addWidget(self.top_tags_frame)

        self.body_search_frame = QFrame()
        self.body_search_frame.setObjectName("bodySearchFrame")
        body_search_layout = QHBoxLayout(self.body_search_frame)
        body_search_layout.setContentsMargins(8, 6, 6, 6)
        body_search_layout.setSpacing(6)
        self.body_search_edit = BodySearchLineEdit()
        self.body_search_edit.setPlaceholderText("現在の本文を検索")
        self.body_search_edit.setClearButtonEnabled(True)
        self.body_search_edit.textChanged.connect(self._run_body_search)
        self.body_search_edit.next_requested.connect(lambda: self._move_body_search(1))
        self.body_search_edit.previous_requested.connect(lambda: self._move_body_search(-1))
        self.body_search_edit.escape_requested.connect(self.close_body_search)
        body_search_layout.addWidget(self.body_search_edit, 1)
        self.body_search_count = QLabel("0 / 0")
        self.body_search_count.setMinimumWidth(48)
        self.body_search_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_search_layout.addWidget(self.body_search_count)
        previous_button = QToolButton()
        previous_button.setArrowType(Qt.ArrowType.UpArrow)
        previous_button.setToolTip("前の一致箇所 (Shift+Enter)")
        previous_button.clicked.connect(lambda: self._move_body_search(-1))
        body_search_layout.addWidget(previous_button)
        next_button = QToolButton()
        next_button.setArrowType(Qt.ArrowType.DownArrow)
        next_button.setToolTip("次の一致箇所 (Enter)")
        next_button.clicked.connect(lambda: self._move_body_search(1))
        body_search_layout.addWidget(next_button)
        close_button = QToolButton()
        close_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton))
        close_button.setToolTip("本文検索を閉じる (Esc)")
        close_button.clicked.connect(self.close_body_search)
        body_search_layout.addWidget(close_button)
        self.body_search_frame.setVisible(False)
        layout.addWidget(self.body_search_frame)

        self.body_view = QWebEngineView()
        self.body_view.setPage(LocalReaderPage(self.body_view))
        self.body_view.loadFinished.connect(self._on_reader_loaded)
        self.body_view.setHtml(render_reader_html("", self.reader_settings))
        layout.addWidget(self.body_view, 1)

        action_row = QHBoxLayout()
        self.open_file_button = QPushButton("ファイルを開く")
        self.open_file_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        self.open_file_button.clicked.connect(self.open_current_file)
        self.rename_button = QPushButton("ED名と結縁相手でリネーム")
        self.rename_button.clicked.connect(self.rename_current)
        self.embed_button = QPushButton("確定済みのタグを文頭に追記")
        self.embed_button.setObjectName("primaryButton")
        self.embed_button.clicked.connect(self.embed_current_tags)
        self.picture_button = QPushButton("ED画像表示")
        self.picture_button.clicked.connect(self.show_ending_picture)
        action_row.addWidget(self.open_file_button)
        action_row.addWidget(self.picture_button)
        action_row.addStretch(1)
        action_row.addWidget(self.rename_button)
        action_row.addWidget(self.embed_button)
        layout.addLayout(action_row)
        return panel

    def _build_detail_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(360)

        content = QWidget()
        content.setObjectName("detailPanel")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 18)
        layout.setSpacing(12)

        metadata_group = QGroupBox("確定情報")
        metadata_layout = QFormLayout(metadata_group)
        metadata_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.ending_combo = QComboBox()
        self._constrain_combo(self.ending_combo, 16)
        self.ending_combo.addItem("ED名不明", None)
        for ending in sorted(self.service.catalog.endings.values(), key=lambda item: item.title_id):
            self.ending_combo.addItem(f"{ending.file_prefix}  {ending.name}", ending.title_id)
        self.heroine_combo = QComboBox()
        self._constrain_combo(self.heroine_combo, 12)
        self.heroine_combo.addItem("結縁相手不明", None)
        for heroine_id in HEROINE_SELECTION_IDS:
            self.heroine_combo.addItem(HEROINE_BY_ID[heroine_id], heroine_id)
        metadata_layout.addRow("ED名", self.ending_combo)
        metadata_layout.addRow("結縁相手", self.heroine_combo)
        self.metadata_source_label = QLabel("")
        self.metadata_source_label.setObjectName("mutedLabel")
        self.metadata_source_label.setWordWrap(True)
        metadata_layout.addRow("情報源", self.metadata_source_label)
        self.save_metadata_button = QPushButton("確定情報を保存")
        self.save_metadata_button.clicked.connect(self.save_metadata)
        metadata_layout.addRow("", self.save_metadata_button)
        layout.addWidget(metadata_group)

        self.parameters_group = QGroupBox("保存時パラメータ")
        parameters_layout = QVBoxLayout(self.parameters_group)
        self.parameters_tree = QTreeWidget()
        self.parameters_tree.setHeaderLabels(["項目", "値"])
        self.parameters_tree.setRootIsDecorated(True)
        self.parameters_tree.setAlternatingRowColors(True)
        self.parameters_tree.setMinimumHeight(220)
        parameters_header = self.parameters_tree.header()
        parameters_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        parameters_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        parameters_layout.addWidget(self.parameters_tree)
        self.parameters_group.setVisible(False)
        layout.addWidget(self.parameters_group)

        tag_group = QGroupBox("タグ")
        tag_layout = QVBoxLayout(tag_group)
        self.tag_tree = QTreeWidget()
        self.tag_tree.setObjectName("tagTree")
        self.tag_tree.setHeaderHidden(True)
        self.tag_tree.setRootIsDecorated(True)
        self.tag_tree.setAlternatingRowColors(False)
        self.tag_tree.setMinimumHeight(210)
        tag_layout.addWidget(self.tag_tree)

        tag_command_row = QHBoxLayout()
        self.add_tag_button = QPushButton("タグを追加")
        self.add_tag_button.clicked.connect(self.add_regular_tags)
        self.remove_tag_button = QPushButton("選択タグを外す")
        self.remove_tag_button.clicked.connect(self.remove_selected_tag)
        self.spoiler_button = QPushButton("ネタバレタグを追加")
        self.spoiler_button.setObjectName("spoilerButton")
        self.spoiler_button.clicked.connect(self.add_spoiler_tags)
        tag_command_row.addWidget(self.add_tag_button)
        tag_command_row.addWidget(self.remove_tag_button)
        tag_command_row.addStretch(1)
        tag_layout.addLayout(tag_command_row)
        tag_layout.addWidget(self.spoiler_button, 0, Qt.AlignmentFlag.AlignLeft)

        freeform_row = QHBoxLayout()
        self.freeform_edit = QLineEdit()
        self.freeform_edit.setPlaceholderText("自由タグ")
        self.freeform_edit.returnPressed.connect(self.add_freeform_tag)
        self.freeform_button = QPushButton("追加")
        self.freeform_button.clicked.connect(self.add_freeform_tag)
        freeform_row.addWidget(self.freeform_edit, 1)
        freeform_row.addWidget(self.freeform_button)
        tag_layout.addLayout(freeform_row)
        layout.addWidget(tag_group)

        note_group = QGroupBox("メモ")
        note_layout = QVBoxLayout(note_group)
        self.note_edit = QPlainTextEdit()
        self.note_edit.setMaximumHeight(120)
        note_layout.addWidget(self.note_edit)
        self.save_note_button = QPushButton("メモを保存")
        self.save_note_button.clicked.connect(self.save_note)
        note_layout.addWidget(self.save_note_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(note_group)

        file_group = QGroupBox("ファイル情報")
        file_layout = QFormLayout(file_group)
        self.file_name_label = QLabel("-")
        self.file_name_label.setWordWrap(True)
        self.file_name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.file_name_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.hash_label = QLabel("-")
        self.hash_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.hash_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.file_state_label = QLabel("-")
        file_layout.addRow("ファイル", self.file_name_label)
        file_layout.addRow("本文SHA-256", self.hash_label)
        file_layout.addRow("状態", self.file_state_label)
        layout.addWidget(file_group)
        layout.addStretch(1)

        scroll.setWidget(content)
        return scroll

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f4f6f3; color: #202620; font-family: 'Yu Gothic UI'; font-size: 13px; }
            QToolBar { background: #ffffff; border: 0; border-bottom: 1px solid #d8ded8; spacing: 4px; padding: 5px 8px; }
            QToolButton { padding: 6px 9px; border-radius: 5px; }
            QToolButton:hover { background: #eef3ef; }
            #libraryPanel, #detailPanel { background: #fafbfa; }
            #readerPanel { background: #ffffff; }
            #bodySearchFrame { background: #f4f7f4; border: 1px solid #cfd7d0; border-radius: 5px; }
            #topTagScroll { background: transparent; }
            #panelHeading { font-size: 18px; font-weight: 700; }
            #readerTitle { font-size: 21px; font-weight: 700; }
            #dialogHeading { font-size: 16px; font-weight: 700; }
            #mutedLabel { color: #637064; }
            QLineEdit, QComboBox, QPlainTextEdit, QListWidget, QTreeWidget, QWebEngineView {
                background: #ffffff; border: 1px solid #cfd7d0; border-radius: 5px; padding: 5px;
                selection-background-color: #2d6f5b; selection-color: #ffffff;
            }
            QTreeWidget { padding: 0; alternate-background-color: #f4f7f4; }
            QTreeWidget#legendTree::item { padding: 5px 2px; }
            QTreeWidget#tagTree::item { padding: 4px 3px; }
            QHeaderView::section { background: #eef3ef; border: 0; border-bottom: 1px solid #cfd7d0; padding: 7px 5px; font-weight: 600; }
            QGroupBox { border: 1px solid #d8ded8; border-radius: 6px; margin-top: 10px; padding-top: 10px; background: #ffffff; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; font-weight: 700; }
            QPushButton { min-height: 30px; padding: 3px 10px; border: 1px solid #aeb9af; border-radius: 5px; background: #ffffff; }
            QPushButton:hover { background: #eef3ef; }
            QPushButton:disabled { color: #9aa29a; background: #f2f3f2; }
            #primaryButton { background: #2d6f5b; border-color: #2d6f5b; color: #ffffff; font-weight: 600; }
            #primaryButton:hover { background: #245c4b; }
            #spoilerButton { color: #9a3f2b; border-color: #c58a7c; }
            QStatusBar { background: #ffffff; border-top: 1px solid #d8ded8; }
            QSplitter::handle { background: #d8ded8; width: 1px; }
            """
        )

    @contextmanager
    def _busy(self, message: str) -> Iterator[None]:
        self.status_label.setText(message)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            yield
        finally:
            QApplication.restoreOverrideCursor()

    def sync_all(self, checked: bool = False, show_result: bool = True) -> None:
        del checked
        if self._refreshing:
            return
        self._refreshing = True
        try:
            with self._busy("受信箱と伝説フォルダを読込中"):
                result = self.service.sync(scan_files=True)
                self.refresh_list()
                self._directory_signature = self._make_directory_signature()
            self._set_sync_status(result)
            if show_result and result.inbox_failed:
                QMessageBox.warning(
                    self,
                    "一部を取り込めませんでした",
                    f"{result.inbox_failed}件のイベントをfailedフォルダへ移動しました。",
                )
        except Exception as exception:
            self._show_error("読込に失敗しました", exception)
        finally:
            self._refreshing = False

    def _set_sync_status(self, result: SyncResult) -> None:
        if result.inbox_failed:
            self.status_label.setText(f"監視中 / 取込失敗 {result.inbox_failed}件")
        elif result.inbox_imported:
            self.status_label.setText(f"監視中 / 新規取込 {result.inbox_imported}件")
        else:
            self.status_label.setText("監視中")

    def refresh_list(self) -> None:
        selected_id = self.current_legend_id
        rows = self.service.database.list_legends(
            self.search_edit.text(),
            None,
            self.service.paths.legend_directory,
        )
        blocker = QSignalBlocker(self.legend_tree)
        self.legend_tree.clear()
        target_item = None
        for row in rows:
            title = row["title_name"] or "ED名不明"
            heroine = row["heroine"] or "結縁相手不明"
            exported = self._format_datetime(row["exported_at"])
            states = []
            if row["file_missing"]:
                states.append("欠落")
            if row["is_duplicate"]:
                states.append("重複")
            if row["confidence"] in ("low", "partial"):
                states.append("要確認")
            tags = row["tag_labels"] or ""
            tag_labels = [label for label in tags.split(" / ") if label]
            visible_tags = "・".join(tag_labels[:2])
            if len(tag_labels) > 2:
                visible_tags += f"  ほか{len(tag_labels) - 2}件"
            item = QTreeWidgetItem([title, heroine, exported, " / ".join(states), visible_tags])
            item.setData(0, Qt.ItemDataRole.UserRole, int(row["id"]))
            item.setToolTip(0, row["current_file_name"])
            item.setToolTip(4, tags)
            self.legend_tree.addTopLevelItem(item)
            if int(row["id"]) == selected_id:
                target_item = item
        del blocker
        self.library_count.setText(f"{len(rows)}件")
        if target_item is not None:
            self.legend_tree.setCurrentItem(target_item)
            self.show_legend(selected_id)
        elif self.legend_tree.topLevelItemCount():
            self.legend_tree.setCurrentItem(self.legend_tree.topLevelItem(0))
            self._on_legend_selected(self.legend_tree.currentItem(), None)
        else:
            self.current_legend_id = None
            self._clear_detail()

    def _on_legend_selected(
        self,
        current: QTreeWidgetItem | None,
        previous: QTreeWidgetItem | None,
    ) -> None:
        del previous
        if current is None:
            return
        self.show_legend(int(current.data(0, Qt.ItemDataRole.UserRole)))

    def show_legend(self, legend_id: int) -> None:
        legend = self.service.database.get_legend(legend_id)
        if legend is None:
            self.refresh_list()
            return
        self.current_legend_id = legend_id
        title = legend["title_name"] or "ED名不明"
        heroine = legend["heroine"] or "結縁相手不明"
        prefix = f"{legend['file_prefix']}  " if legend["file_prefix"] else ""
        self.title_label.setText(prefix + title)
        self.subtitle_label.setText(f"結縁相手: {heroine}    出力日時: {self._format_datetime(legend['exported_at'], True)}")
        self.current_body_text = legend.get("plain_text") or ""
        self.body_view.setHtml(render_reader_html(self.current_body_text, self.reader_settings))
        self._fill_top_tags(legend)

        self._select_combo_data(self.ending_combo, legend["title_id"])
        heroine_id = 0 if legend["heroine_id"] == 20 else legend["heroine_id"]
        self._select_combo_data(self.heroine_combo, heroine_id)
        self.metadata_source_label.setText(
            f"ED: {self._source_label(legend['title_source'])} / 結縁: {self._source_label(legend['heroine_source'])}"
        )

        self.note_edit.setPlainText(legend["note"] or "")
        self.file_name_label.setText(legend["current_file_name"])
        full_hash = legend["content_sha256"]
        self.hash_label.setText(full_hash[:16] + "...")
        self.hash_label.setToolTip(full_hash)
        states = ["本文あり"]
        if legend["file_missing"]:
            states = ["ファイル欠落"]
        if legend["duplicate_of"]:
            states.append(f"重複 #{legend['duplicate_of']}")
        if legend["tags_embedded_at"]:
            states.append("タグ追記済み")
        self.file_state_label.setText(" / ".join(states))

        self._fill_tag_list(legend)
        self._fill_parameters(legend.get("parameters") or {})
        enabled = not bool(legend["file_missing"])
        for button in (self.open_file_button, self.rename_button, self.embed_button):
            button.setEnabled(enabled)

    def _fill_tag_list(self, legend: dict) -> None:
        self.tag_tree.clear()
        parents: dict[str, QTreeWidgetItem] = {}
        for tag in legend["tags"]:
            source = self._source_label(tag["source"])
            category_id = str(tag["category"])
            category = CATEGORY_LABELS.get(category_id, category_id)
            parent = parents.get(category_id)
            if parent is None:
                parent = QTreeWidgetItem([category])
                parent_font = parent.font(0)
                parent_font.setBold(True)
                parent.setFont(0, parent_font)
                self.tag_tree.addTopLevelItem(parent)
                parents[category_id] = parent
            item = QTreeWidgetItem([str(tag["label"])])
            item.setData(0, Qt.ItemDataRole.UserRole, tag["id"])
            item.setToolTip(0, f"分類: {category}\n情報源: {source}")
            item.setForeground(0, QBrush(QColor(CATEGORY_COLORS.get(category_id, "#39424a"))))
            parent.addChild(item)
        self.tag_tree.expandAll()

    def _fill_top_tags(self, legend: dict) -> None:
        while self.top_tag_layout.count():
            item = self.top_tag_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        tags = [
            tag
            for tag in legend["tags"]
            if tag["category"] not in ("ending", "heroine")
        ]
        self.top_tags_frame.setVisible(bool(tags))
        for index, tag in enumerate(tags):
            category_id = str(tag["category"])
            category = CATEGORY_LABELS.get(category_id, category_id)
            source = self._source_label(tag["source"])
            if index:
                separator = QLabel("・")
                separator.setObjectName("mutedLabel")
                self.top_tag_layout.addWidget(separator)
            label = QLabel(str(tag["label"]))
            label.setObjectName("mutedLabel")
            label.setToolTip(f"分類: {category}\n情報源: {source}")
            self.top_tag_layout.addWidget(label)
        self.top_tag_container.adjustSize()

    def _fill_parameters(self, parameters: dict) -> None:
        self.parameters_tree.clear()
        sections = (
            ("abilities", "主人公能力", "value"),
            ("personality", "性情・処世・品性・道徳", "value"),
            ("resources", "所持金", "value"),
            ("faction", "門派", "value"),
            ("relationships", "好感度", "value"),
            ("skills", "スキル", "level"),
        )
        has_items = False
        for key, label, value_key in sections:
            values = parameters.get(key) or []
            if not isinstance(values, list) or not values:
                continue
            parent = QTreeWidgetItem([label, ""])
            self.parameters_tree.addTopLevelItem(parent)
            for value in values:
                if not isinstance(value, dict):
                    continue
                number = value.get(value_key)
                if value_key == "level":
                    display = f"Lv. {number}"
                else:
                    level_text = value.get("display_value")
                    display = f"{level_text} ({number})" if level_text else str(number)
                parent.addChild(QTreeWidgetItem([str(value.get("label") or value.get("key") or ""), display]))
                has_items = True
            parent.setExpanded(False)
        self.parameters_group.setVisible(has_items)

    def _clear_detail(self) -> None:
        self.title_label.setText("伝説がありません")
        self.subtitle_label.clear()
        self.current_body_text = ""
        self.body_view.setHtml(render_reader_html("", self.reader_settings))
        self.top_tags_frame.setVisible(False)
        self.tag_tree.clear()
        self.parameters_tree.clear()
        self.parameters_group.setVisible(False)
        self.note_edit.clear()
        self.file_name_label.setText("-")
        self.hash_label.setText("-")
        self.file_state_label.setText("-")

    def save_metadata(self) -> None:
        if self.current_legend_id is None:
            return
        try:
            self.service.set_metadata(
                self.current_legend_id,
                self.ending_combo.currentData(),
                self.heroine_combo.currentData(),
            )
            self.refresh_list()
            self.status_label.setText("確定情報を保存しました")
        except Exception as exception:
            self._show_error("確定情報を保存できませんでした", exception)

    def add_regular_tags(self) -> None:
        if self.current_legend_id is None:
            return
        legend = self.service.database.get_legend(self.current_legend_id)
        if legend is None:
            return
        assigned = {tag["id"] for tag in legend["tags"]}
        candidates = [
            tag
            for tag in self.service.catalog.ordered_tags(include_spoilers=False)
            if tag.category not in ("ending", "heroine")
        ]
        dialog = TagSelectionDialog(candidates, assigned, "タグを追加", self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            for tag_id in dialog.selected_tag_ids():
                self.service.add_tag(self.current_legend_id, tag_id)
            self.show_legend(self.current_legend_id)
        except Exception as exception:
            self._show_error("タグを追加できませんでした", exception)

    def add_spoiler_tags(self) -> None:
        if self.current_legend_id is None:
            return
        legend = self.service.database.get_legend(self.current_legend_id)
        if legend is None:
            return
        assigned = {tag["id"] for tag in legend["tags"]}
        candidates = [
            tag
            for tag in self.service.catalog.ordered_tags(include_spoilers=True)
            if not tag.default_visible and tag.category not in ("ending", "heroine")
        ]
        dialog = TagSelectionDialog(candidates, assigned, "ネタバレタグを追加", self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            for tag_id in dialog.selected_tag_ids():
                self.service.add_tag(self.current_legend_id, tag_id)
            self.show_legend(self.current_legend_id)
        except Exception as exception:
            self._show_error("ネタバレタグを追加できませんでした", exception)

    def add_freeform_tag(self) -> None:
        if self.current_legend_id is None:
            return
        label = self.freeform_edit.text().strip()
        if not label:
            return
        try:
            self.service.add_freeform_tag(self.current_legend_id, label)
            self.freeform_edit.clear()
            self.show_legend(self.current_legend_id)
        except Exception as exception:
            self._show_error("自由タグを追加できませんでした", exception)

    def remove_selected_tag(self) -> None:
        if self.current_legend_id is None or self.tag_tree.currentItem() is None:
            return
        tag_value = self.tag_tree.currentItem().data(0, Qt.ItemDataRole.UserRole)
        if tag_value is None:
            return
        tag_id = str(tag_value)
        try:
            self.service.remove_tag(self.current_legend_id, tag_id)
            self.show_legend(self.current_legend_id)
        except Exception as exception:
            self._show_error("タグを外せませんでした", exception)

    def save_note(self) -> None:
        if self.current_legend_id is None:
            return
        try:
            self.service.update_note(self.current_legend_id, self.note_edit.toPlainText())
            self.status_label.setText("メモを保存しました")
        except Exception as exception:
            self._show_error("メモを保存できませんでした", exception)

    def rename_current(self) -> None:
        if self.current_legend_id is None:
            return
        try:
            with self._busy("ファイル名を変更中"):
                destination = self.service.rename_legend(self.current_legend_id)
            self.refresh_list()
            self.status_label.setText(f"{destination.name} に変更しました")
        except Exception as exception:
            self._show_error("ファイル名を変更できませんでした", exception)

    def embed_current_tags(self) -> None:
        if self.current_legend_id is None:
            return
        legend = self.service.database.get_legend(self.current_legend_id)
        if legend is None:
            return
        tag_count = len(legend["tags"])
        answer = QMessageBox.question(
            self,
            "確定済みタグを追記",
            f"確定済みタグ {tag_count}件をTXTの文頭へ書き込みます。\n"
            "既存の管理ブロックがある場合は置き換えます。本文は変更しません。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            with self._busy("タグを書き込み中"):
                self.service.embed_tags(self.current_legend_id)
            self.show_legend(self.current_legend_id)
            self.status_label.setText("確定済みタグを文頭に追記しました")
        except Exception as exception:
            self._show_error("タグを追記できませんでした", exception)

    def open_current_file(self) -> None:
        if self.current_legend_id is None:
            return
        legend = self.service.database.get_legend(self.current_legend_id)
        if legend:
            QDesktopServices.openUrl(QUrl.fromLocalFile(legend["full_path"]))

    def show_ending_picture(self) -> None:
        if self.current_legend_id is None:
            return
        legend = self.service.database.get_legend(self.current_legend_id)
        if legend is None:
            return
        picture_path = self.picture_index.picture_for_title(legend.get("title_id"))
        title = legend.get("title_name") or "ED画像"
        EndingPictureDialog(title, picture_path, self).exec()

    def open_reader_settings(self) -> None:
        dialog = ReaderSettingsDialog(self.reader_settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.reader_settings = dialog.value()
        self.reader_settings_store.save(self.reader_settings)
        self.body_view.setHtml(render_reader_html(self.current_body_text, self.reader_settings))

    def open_body_search(self) -> None:
        self.body_search_frame.setVisible(True)
        self.body_search_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.body_search_edit.selectAll()
        self._run_body_search()

    def close_body_search(self) -> None:
        self.body_search_frame.setVisible(False)
        self.body_search_edit.clear()
        self.body_search_count.setText("0 / 0")
        self.body_view.page().findText("")
        self.body_view.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _on_reader_loaded(self, success: bool) -> None:
        if success and self.body_search_frame.isVisible():
            self._run_body_search()

    def _run_body_search(self) -> None:
        query = self.body_search_edit.text()
        self.body_view.page().findText("")
        if not query:
            self.body_search_count.setText("0 / 0")
            return
        self.body_view.page().findText(
            query,
            QWebEnginePage.FindFlag(0),
            lambda result, expected=query: self._update_body_search_status(result, expected),
        )

    def _move_body_search(self, delta: int) -> None:
        if not self.body_search_edit.text():
            return
        flags = (
            QWebEnginePage.FindFlag.FindBackward
            if delta < 0
            else QWebEnginePage.FindFlag(0)
        )
        self.body_view.page().findText(
            self.body_search_edit.text(),
            flags,
            lambda result: self._update_body_search_status(
                result, self.body_search_edit.text()
            ),
        )

    def _update_body_search_status(self, result: object, expected_query: str) -> None:
        if expected_query != self.body_search_edit.text() or result is None:
            return
        count = int(result.numberOfMatches())
        index = int(result.activeMatch())
        self.body_search_count.setText(f"{index} / {count}")

    def open_path_settings(self) -> None:
        dialog = PathSettingsDialog(self.service, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        game_root, legend_directory = dialog.values()
        try:
            legend_directory = ensure_writable_directory(legend_directory)
            new_paths = replace(
                self.service.paths,
                game_root=game_root,
                legend_directory=legend_directory,
            )
            with self._busy("保存先を切替中"):
                result = self.service.switch_paths(new_paths)
            write_shared_settings(
                self.service.paths.shared_settings_path,
                game_root,
                legend_directory,
            )
            self.picture_index = EndingPictureIndex(new_paths.pictures_directory)
            self._directory_signature = self._make_directory_signature()
            self.refresh_list()
            self._set_sync_status(result)
        except Exception as exception:
            self._show_error("パス設定を保存できませんでした", exception)

    def open_legend_directory(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.paths.legend_directory)))

    def _set_library_panel_visible(self, visible: bool) -> None:
        if hasattr(self, "library_panel"):
            self.library_panel.setVisible(visible)

    def _set_detail_panel_visible(self, visible: bool) -> None:
        if hasattr(self, "detail_panel"):
            self.detail_panel.setVisible(visible)

    def create_backup(self) -> None:
        try:
            destination = self.service.create_backup()
            self.status_label.setText(f"バックアップ: {destination.name}")
        except Exception as exception:
            self._show_error("バックアップを作成できませんでした", exception)

    def _poll_directories(self) -> None:
        if self._refreshing:
            return
        signature = self._make_directory_signature()
        if signature != self._directory_signature:
            self.sync_all(show_result=False)

    def _make_directory_signature(self) -> tuple[int, int, int]:
        files = list(self.service.paths.legend_directory.glob("*.txt"))
        inbox = list(self.service.paths.inbox_directory.glob("*.json"))
        mtimes = [path.stat().st_mtime_ns for path in (*files, *inbox) if path.exists()]
        return len(files), len(inbox), max(mtimes, default=0)

    @staticmethod
    def _select_combo_data(combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    @staticmethod
    def _constrain_combo(combo: QComboBox, minimum_contents_length: int) -> None:
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(minimum_contents_length)
        combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    @staticmethod
    def _source_label(source: str | None) -> str:
        return {
            "game_end_key": "ゲーム内ED ID",
            "game_title_partner": "旧版ゲーム内想い人ID",
            "story_rule": "観測済み結縁イベント",
            "mod": "MOD確定",
            "filename": "ファイル名",
            "scan": "ファイル走査",
            "manual": "手動",
            "manual_metadata": "手動確定",
            "user": "手動",
            "unknown": "不明",
        }.get(source or "unknown", source or "不明")

    @staticmethod
    def _format_datetime(value: str | None, include_seconds: bool = False) -> str:
        if not value:
            return "不明"
        try:
            parsed = datetime.fromisoformat(value).astimezone()
            return parsed.strftime("%Y/%m/%d %H:%M:%S" if include_seconds else "%m/%d %H:%M")
        except ValueError:
            return value

    def _show_error(self, title: str, exception: Exception) -> None:
        self.status_label.setText(title)
        QMessageBox.critical(self, title, str(exception))


def create_main_window(service: LegendService) -> LegendMainWindow:
    return LegendMainWindow(service)
