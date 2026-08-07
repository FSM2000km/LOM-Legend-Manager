from __future__ import annotations

import json
import re
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
from .mod_settings import MOD_SETTINGS, is_game_running, read_mod_settings, write_mod_settings
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
    render_reader_body_html,
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

PERSONALITY_LABELS = ("性情", "処世", "品性", "道徳")
MISSING_PERSONALITY_VALUE = "__missing__"
LIST_RUBY_PATTERN = re.compile(r"[（(][ぁ-ゖァ-ヺー・]+[）)]")

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


class MultiSelectFilterDialog(QDialog):
    def __init__(
        self,
        title: str,
        choices: list[tuple[object, str]],
        selected: set[object],
        parent: QWidget | None = None,
        show_match_mode: bool = False,
        require_all: bool = True,
        spoiler_values: set[object] | None = None,
        show_spoilers: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(440, 560)
        layout = QVBoxLayout(self)

        self.search = QLineEdit()
        self.search.setPlaceholderText("候補を検索")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)

        selection_row = QHBoxLayout()
        select_all = QPushButton("すべて選択")
        clear_all = QPushButton("すべて解除")
        selection_row.addWidget(select_all)
        selection_row.addWidget(clear_all)
        selection_row.addStretch(1)
        layout.addLayout(selection_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self._items: list[tuple[QTreeWidgetItem, object]] = []
        for value, label in choices:
            item = QTreeWidgetItem([label])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if value in selected else Qt.CheckState.Unchecked)
            self.tree.addTopLevelItem(item)
            self._items.append((item, value))
        layout.addWidget(self.tree, 1)

        self.match_combo: QComboBox | None = None
        if show_match_mode:
            self.match_combo = QComboBox()
            self.match_combo.addItem("選択したタグをすべて含む", True)
            self.match_combo.addItem("選択したタグのいずれかを含む", False)
            self.match_combo.setCurrentIndex(0 if require_all else 1)
            layout.addWidget(self.match_combo)

        self._spoiler_values = spoiler_values or set()
        self.spoiler_checkbox: QCheckBox | None = None
        if spoiler_values is not None:
            self.spoiler_checkbox = QCheckBox("ネタバレタグを候補に表示")
            self.spoiler_checkbox.setChecked(show_spoilers)
            self.spoiler_checkbox.toggled.connect(lambda: self._filter_items(self.search.text()))
            layout.addWidget(self.spoiler_checkbox)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("絞り込みを適用")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.search.textChanged.connect(self._filter_items)
        select_all.clicked.connect(lambda: self._set_visible_checks(Qt.CheckState.Checked))
        clear_all.clicked.connect(lambda: self._set_visible_checks(Qt.CheckState.Unchecked))
        self._filter_items("")

    def _filter_items(self, text: str) -> None:
        query = text.strip().casefold()
        show_spoilers = self.spoiler_checkbox is None or self.spoiler_checkbox.isChecked()
        for item, value in self._items:
            hidden_by_query = bool(query) and query not in item.text(0).casefold()
            item.setHidden(hidden_by_query or (value in self._spoiler_values and not show_spoilers))

    def _set_visible_checks(self, state: Qt.CheckState) -> None:
        for item, _ in self._items:
            if not item.isHidden():
                item.setCheckState(0, state)

    def selected_values(self) -> set[object]:
        return {value for item, value in self._items if item.checkState(0) == Qt.CheckState.Checked}

    def require_all(self) -> bool:
        return bool(self.match_combo.currentData()) if self.match_combo is not None else True

    def show_spoilers(self) -> bool:
        return self.spoiler_checkbox.isChecked() if self.spoiler_checkbox is not None else False


class ConfirmedInfoDialog(QDialog):
    DEFINITIONS = (
        ("metadata", "ED・結縁相手"),
        ("tags", "確定済みタグ"),
        ("abilities", "主人公能力"),
        ("personality", "性情・処世・品性・道徳"),
        ("resources", "所持金"),
        ("faction", "門派情報"),
        ("relationships", "好感度"),
        ("skills", "スキル"),
    )

    def __init__(self, selected: set[str], available: set[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("文頭へ追記する確定情報")
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        heading = QLabel("追記する大カテゴリを選択してください")
        heading.setObjectName("dialogHeading")
        layout.addWidget(heading)
        self.checkboxes: list[tuple[QCheckBox, str]] = []
        for key, label in self.DEFINITIONS:
            checkbox = QCheckBox(label)
            checkbox.setChecked(key in selected and key in available)
            checkbox.setEnabled(key in available)
            if key not in available:
                checkbox.setToolTip("この伝説には該当する情報がありません")
            layout.addWidget(checkbox)
            self.checkboxes.append((checkbox, key))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("選択内容を文頭へ追記")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_categories(self) -> set[str]:
        return {key for checkbox, key in self.checkboxes if checkbox.isChecked() and checkbox.isEnabled()}


class PersonalityFilterDialog(QDialog):
    def __init__(
        self,
        choices: dict[str, list[str]],
        selected: dict[str, set[str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("人物傾向で絞り込み")
        self.setMinimumWidth(700)
        layout = QVBoxLayout(self)
        description = QLabel("分類内は複数選択、分類どうしはすべて満たす伝説を表示します。")
        description.setObjectName("mutedLabel")
        layout.addWidget(description)
        self.checkboxes: dict[str, list[tuple[QCheckBox, str]]] = {}
        for label in PERSONALITY_LABELS:
            group = QGroupBox(label)
            group_layout = QHBoxLayout(group)
            entries: list[tuple[QCheckBox, str]] = []
            values = list(choices.get(label) or [])
            if MISSING_PERSONALITY_VALUE not in values:
                values.append(MISSING_PERSONALITY_VALUE)
            for value in values:
                display = "未記録" if value == MISSING_PERSONALITY_VALUE else value
                checkbox = QCheckBox(display)
                checkbox.setChecked(value in selected.get(label, set()))
                group_layout.addWidget(checkbox)
                entries.append((checkbox, value))
            group_layout.addStretch(1)
            self.checkboxes[label] = entries
            layout.addWidget(group)

        clear_button = QPushButton("すべて解除")
        clear_button.clicked.connect(self._clear_all)
        layout.addWidget(clear_button, 0, Qt.AlignmentFlag.AlignLeft)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("絞り込みを適用")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _clear_all(self) -> None:
        for entries in self.checkboxes.values():
            for checkbox, _ in entries:
                checkbox.setChecked(False)

    def selected_filters(self) -> dict[str, set[str]]:
        return {
            label: {value for checkbox, value in entries if checkbox.isChecked()}
            for label, entries in self.checkboxes.items()
            if any(checkbox.isChecked() for checkbox, _ in entries)
        }


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


class ModSettingsDialog(QDialog):
    def __init__(self, values: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("LOM Legend Manager MOD設定")
        self.resize(620, 620)
        layout = QVBoxLayout(self)
        notice = QLabel("変更内容は、次回ゲーム起動時から反映されます。")
        notice.setObjectName("mutedLabel")
        layout.addWidget(notice)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        self.controls: dict[str, QWidget] = {}
        for definition in MOD_SETTINGS:
            if definition.kind == "bool":
                control = QCheckBox(definition.label)
                control.setChecked(bool(values.get(definition.key, definition.default)))
            elif definition.kind == "int":
                control = QSpinBox()
                control.setRange(definition.minimum, definition.maximum)
                control.setValue(int(values.get(definition.key, definition.default)))
            else:
                control = QComboBox()
                for value, label in definition.choices:
                    control.addItem(label, value)
                index = control.findData(values.get(definition.key, definition.default))
                control.setCurrentIndex(max(0, index))
            control.setToolTip(definition.description)
            if definition.kind == "bool":
                form.addRow("", control)
            else:
                form.addRow(definition.label, control)
            self.controls[definition.key] = control
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("設定を保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for definition in MOD_SETTINGS:
            control = self.controls[definition.key]
            if isinstance(control, QCheckBox):
                result[definition.key] = control.isChecked()
            elif isinstance(control, QSpinBox):
                result[definition.key] = control.value()
            elif isinstance(control, QComboBox):
                result[definition.key] = control.currentData()
        return result


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
        self.current_content_sha256 = ""
        self.current_reader_key = ""
        self.current_reader_html = ""
        self.current_reader_body_html = ""
        self._pending_scroll_ratio = 0.0
        self.ending_filter: set[int | None] = set()
        self.heroine_filter: set[int | None] = set()
        self.tag_filter: set[str] = set()
        self.tag_filter_require_all = True
        self.show_spoiler_tag_filters = False
        self.personality_filter: dict[str, set[str]] = {}
        self.sort_column = 6
        self.sort_descending = True
        self._directory_signature: tuple[int, int, int] | None = None
        self._refreshing = False
        self.reader_settings_store = ReaderSettingsStore(self.service.paths.viewer_settings_path)
        self.reader_settings = self.reader_settings_store.load()
        self.current_legend_id = self.reader_settings_store.load_last_legend_id()
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

        self.reader_position_timer = QTimer(self)
        self.reader_position_timer.setInterval(1000)
        self.reader_position_timer.timeout.connect(self._capture_reader_position)
        self.reader_position_timer.start()

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

        self.mod_settings_action = QAction("MOD設定", self)
        self.mod_settings_action.triggered.connect(self.open_mod_settings)

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
        toolbar.addAction(self.mod_settings_action)
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
        self.root_splitter.setSizes([470, 630, 380])
        self.root_splitter.setStretchFactor(0, 0)
        self.root_splitter.setStretchFactor(1, 1)
        self.root_splitter.setStretchFactor(2, 0)
        self.setCentralWidget(self.root_splitter)

        self.status_label = QLabel("準備中")
        self.statusBar().addPermanentWidget(self.status_label)

    def _build_library_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("libraryPanel")
        panel.setMinimumWidth(440)
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

        filter_row = QHBoxLayout()
        self.ending_filter_button = QPushButton("ED: すべて")
        self.ending_filter_button.clicked.connect(self.open_ending_filter)
        self.heroine_filter_button = QPushButton("結縁: すべて")
        self.heroine_filter_button.clicked.connect(self.open_heroine_filter)
        self.tag_filter_button = QPushButton("タグ: すべて")
        self.tag_filter_button.clicked.connect(self.open_tag_filter)
        self.personality_filter_button = QPushButton("人物傾向: すべて")
        self.personality_filter_button.clicked.connect(self.open_personality_filter)
        self.clear_filter_button = QToolButton()
        self.clear_filter_button.setText("解除")
        self.clear_filter_button.setToolTip("すべての絞り込み条件を解除します")
        self.clear_filter_button.clicked.connect(self.clear_filters)
        filter_row.addWidget(self.ending_filter_button)
        filter_row.addWidget(self.heroine_filter_button)
        layout.addLayout(filter_row)
        detail_filter_row = QHBoxLayout()
        detail_filter_row.addWidget(self.personality_filter_button)
        detail_filter_row.addWidget(self.tag_filter_button)
        detail_filter_row.addStretch(1)
        detail_filter_row.addWidget(self.clear_filter_button)
        layout.addLayout(detail_filter_row)

        self.legend_tree = QTreeWidget()
        self.legend_tree.setObjectName("legendTree")
        self.legend_tree.setHeaderLabels(
            ["ED", "結縁", "性情", "処世", "品性", "道徳", "日時", "状態", "タグ"]
        )
        self.legend_tree.setRootIsDecorated(False)
        self.legend_tree.setAlternatingRowColors(True)
        self.legend_tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.legend_tree.setUniformRowHeights(False)
        self.legend_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        header = self.legend_tree.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setMinimumSectionSize(24)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self._change_sort)
        default_widths = [112, 58, 52, 52, 52, 52, 72, 38, 100]
        saved_widths = self.reader_settings_store.load_legend_column_widths(
            self.legend_tree.columnCount()
        )
        for column, width in enumerate(saved_widths or default_widths):
            self.legend_tree.setColumnWidth(column, width)
        self.column_width_save_timer = QTimer(self)
        self.column_width_save_timer.setSingleShot(True)
        self.column_width_save_timer.setInterval(250)
        self.column_width_save_timer.timeout.connect(self._save_legend_column_widths)
        header.sectionResized.connect(lambda *_args: self.column_width_save_timer.start())
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
        self.current_reader_html = render_reader_html("", self.reader_settings)
        self.current_reader_body_html = ""
        self.body_view.setHtml(self.current_reader_html)
        layout.addWidget(self.body_view, 1)

        file_action_row = QHBoxLayout()
        self.open_file_button = QPushButton("ファイルを開く")
        self.open_file_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        self.open_file_button.clicked.connect(self.open_current_file)
        self.rename_button = QPushButton("ED名と結縁相手でリネーム")
        self.rename_button.clicked.connect(self.rename_current)
        self.embed_button = QPushButton("確定情報を文頭に追記")
        self.embed_button.setObjectName("primaryButton")
        self.embed_button.clicked.connect(self.embed_current_tags)
        self.picture_button = QPushButton("ED画像表示")
        self.picture_button.clicked.connect(self.show_ending_picture)
        file_action_row.addWidget(self.open_file_button)
        file_action_row.addWidget(self.picture_button)
        file_action_row.addStretch(1)
        layout.addLayout(file_action_row)
        write_action_row = QHBoxLayout()
        write_action_row.addStretch(1)
        write_action_row.addWidget(self.rename_button)
        write_action_row.addWidget(self.embed_button)
        layout.addLayout(write_action_row)
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
            QTreeWidget#legendTree { font-size: 12px; }
            QTreeWidget#legendTree::item { padding: 3px 1px; }
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
        heroine_filter = set(self.heroine_filter)
        if 0 in heroine_filter:
            heroine_filter.add(20)
        rows = list(
            self.service.database.list_legends(
                self.search_edit.text(),
                None,
                self.service.paths.legend_directory,
                self.ending_filter,
                heroine_filter,
                self.tag_filter,
                self.tag_filter_require_all,
            )
        )
        rows = [row for row in rows if self._matches_personality_filter(row["parameters_json"])]
        rows.sort(key=self._legend_sort_key, reverse=self.sort_descending)
        blocker = QSignalBlocker(self.legend_tree)
        self.legend_tree.clear()
        target_item = None
        for row in rows:
            title = LIST_RUBY_PATTERN.sub("", row["title_name"] or "ED名不明")
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
            personality_values = self._personality_values(row["parameters_json"])
            item = QTreeWidgetItem(
                [
                    title,
                    heroine,
                    *(personality_values.get(label, "-") for label in PERSONALITY_LABELS),
                    exported,
                    " / ".join(states),
                    visible_tags,
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, int(row["id"]))
            item.setToolTip(0, row["current_file_name"])
            for column, label in enumerate(PERSONALITY_LABELS, start=2):
                display = personality_values.get(label)
                if display:
                    item.setToolTip(column, f"{label}: {display}")
            item.setToolTip(8, tags)
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

    @staticmethod
    def _personality_summary(parameters_json: str) -> tuple[str, str]:
        values = LegendMainWindow._personality_values(parameters_json)
        compact: list[str] = []
        details: list[str] = []
        for label in PERSONALITY_LABELS:
            display = values.get(label)
            if not display:
                continue
            compact.append(display)
            details.append(f"{label}: {display}")
        return (" / ".join(compact) if compact else "-", "\n".join(details))

    @staticmethod
    def _personality_values(parameters_json: str) -> dict[str, str]:
        try:
            parameters = json.loads(parameters_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        result: dict[str, str] = {}
        for value in parameters.get("personality") or []:
            if not isinstance(value, dict):
                continue
            label = str(value.get("label") or "")
            display = str(value.get("display_value") or "")
            if label in PERSONALITY_LABELS and display:
                result[label] = display
        return result

    def _matches_personality_filter(self, parameters_json: str) -> bool:
        if not self.personality_filter:
            return True
        values = self._personality_values(parameters_json)
        for label, selected in self.personality_filter.items():
            value = values.get(label, MISSING_PERSONALITY_VALUE)
            if selected and value not in selected:
                return False
        return True

    def _legend_sort_key(self, row) -> object:
        if self.sort_column == 0:
            return (row["title_id"] is None, row["title_id"] or 0, row["title_name"] or "")
        if self.sort_column == 1:
            return (row["heroine"] is None, row["heroine"] or "")
        if 2 <= self.sort_column <= 5:
            try:
                values = json.loads(row["parameters_json"] or "{}").get("personality") or []
                target_label = PERSONALITY_LABELS[self.sort_column - 2]
                for value in values:
                    if value.get("label") == target_label:
                        return (False, int(value.get("value") or 0))
                return (True, 0)
            except (TypeError, ValueError, json.JSONDecodeError):
                return (True, 0)
        if self.sort_column == 6:
            return row["exported_at"] or row["created_at"] or ""
        if self.sort_column == 7:
            return (int(row["file_missing"]), int(row["is_duplicate"]))
        return row["tag_labels"] or ""

    def _change_sort(self, column: int) -> None:
        if self.sort_column == column:
            self.sort_descending = not self.sort_descending
        else:
            self.sort_column = column
            self.sort_descending = column == 6
        self.legend_tree.header().setSortIndicator(
            column,
            Qt.SortOrder.DescendingOrder if self.sort_descending else Qt.SortOrder.AscendingOrder,
        )
        self.refresh_list()

    def _save_legend_column_widths(self) -> None:
        self.reader_settings_store.save_legend_column_widths(
            [self.legend_tree.columnWidth(column) for column in range(self.legend_tree.columnCount())]
        )

    def open_ending_filter(self) -> None:
        choices = [(None, "ED名不明")]
        choices.extend(
            (ending.title_id, f"{ending.file_prefix}  {ending.name}")
            for ending in sorted(self.service.catalog.endings.values(), key=lambda item: item.title_id)
        )
        dialog = MultiSelectFilterDialog("EDで絞り込み", choices, set(self.ending_filter), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.ending_filter = {
                value for value in dialog.selected_values() if value is None or isinstance(value, int)
            }
            self._update_filter_buttons()
            self.refresh_list()

    def open_heroine_filter(self) -> None:
        choices: list[tuple[object, str]] = [(None, "結縁相手不明")]
        choices.extend((heroine_id, HEROINE_BY_ID[heroine_id]) for heroine_id in HEROINE_SELECTION_IDS)
        dialog = MultiSelectFilterDialog("結縁相手で絞り込み", choices, set(self.heroine_filter), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.heroine_filter = {
                value for value in dialog.selected_values() if value is None or isinstance(value, int)
            }
            self._update_filter_buttons()
            self.refresh_list()

    def open_tag_filter(self) -> None:
        rows = self.service.database.get_assigned_tags(include_spoilers=True)
        choices = [(str(row["id"]), f"{row['label']}  ({row['legend_count']}件)") for row in rows]
        spoiler_values = {str(row["id"]) for row in rows if bool(row["is_spoiler"])}
        dialog = MultiSelectFilterDialog(
            "既知のタグで絞り込み",
            choices,
            set(self.tag_filter),
            self,
            show_match_mode=True,
            require_all=self.tag_filter_require_all,
            spoiler_values=spoiler_values,
            show_spoilers=self.show_spoiler_tag_filters,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.tag_filter = {str(value) for value in dialog.selected_values()}
            self.tag_filter_require_all = dialog.require_all()
            self.show_spoiler_tag_filters = dialog.show_spoilers()
            self._update_filter_buttons()
            self.refresh_list()

    def open_personality_filter(self) -> None:
        rows = self.service.database.list_legends(directory=self.service.paths.legend_directory)
        values_by_label: dict[str, set[str]] = {label: set() for label in PERSONALITY_LABELS}
        for row in rows:
            for label, value in self._personality_values(row["parameters_json"]).items():
                values_by_label[label].add(value)
        choices = {label: sorted(values) for label, values in values_by_label.items()}
        dialog = PersonalityFilterDialog(choices, self.personality_filter, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.personality_filter = dialog.selected_filters()
            self._update_filter_buttons()
            self.refresh_list()

    def clear_filters(self) -> None:
        self.ending_filter.clear()
        self.heroine_filter.clear()
        self.tag_filter.clear()
        self.personality_filter.clear()
        self.search_edit.clear()
        self._update_filter_buttons()
        self.refresh_list()

    def _update_filter_buttons(self) -> None:
        self.ending_filter_button.setText(
            f"ED: {len(self.ending_filter)}件選択" if self.ending_filter else "ED: すべて"
        )
        self.heroine_filter_button.setText(
            f"結縁: {len(self.heroine_filter)}件選択" if self.heroine_filter else "結縁: すべて"
        )
        mode = "すべて" if self.tag_filter_require_all else "いずれか"
        self.tag_filter_button.setText(
            f"タグ: {len(self.tag_filter)}件・{mode}" if self.tag_filter else "タグ: すべて"
        )
        selected_count = sum(len(values) for values in self.personality_filter.values())
        self.personality_filter_button.setText(
            f"人物傾向: {selected_count}件選択" if selected_count else "人物傾向: すべて"
        )

    def _on_legend_selected(
        self,
        current: QTreeWidgetItem | None,
        previous: QTreeWidgetItem | None,
    ) -> None:
        del previous
        if current is None:
            return
        self._capture_reader_position()
        self.show_legend(int(current.data(0, Qt.ItemDataRole.UserRole)))

    def show_legend(self, legend_id: int) -> None:
        legend = self.service.database.get_legend(legend_id)
        if legend is None:
            self.refresh_list()
            return
        self.current_legend_id = legend_id
        self.reader_settings_store.save_last_legend_id(legend_id)
        title = legend["title_name"] or "ED名不明"
        heroine = legend["heroine"] or "結縁相手不明"
        prefix = f"{legend['file_prefix']}  " if legend["file_prefix"] else ""
        self.title_label.setText(prefix + title)
        self.subtitle_label.setText(f"結縁相手: {heroine}    出力日時: {self._format_datetime(legend['exported_at'], True)}")
        self.current_body_text = legend.get("plain_text") or ""
        self.current_content_sha256 = str(legend.get("content_sha256") or "")
        self._pending_scroll_ratio = self.reader_settings_store.load_position(
            legend_id, self.current_content_sha256
        )
        reader_key = f"{legend_id}:{self.current_content_sha256}"
        self._set_reader_body(
            render_reader_body_html(self.current_body_text, self.reader_settings),
            reader_key,
            render_reader_html(self.current_body_text, self.reader_settings, reader_key),
        )
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
            states.append("確定情報追記済み")
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
        self.current_content_sha256 = ""
        self._pending_scroll_ratio = 0.0
        self._set_reader_document(render_reader_html("", self.reader_settings), "")
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
        available = {"metadata"}
        if any(tag.get("category") not in ("ending", "heroine") for tag in legend["tags"]):
            available.add("tags")
        parameters = legend.get("parameters") or {}
        available.update(key for key in ("abilities", "personality", "resources", "faction", "relationships", "skills") if parameters.get(key))
        defaults = {key for key, _ in ConfirmedInfoDialog.DEFINITIONS}
        selected = self.reader_settings_store.load_embed_categories(defaults)
        dialog = ConfirmedInfoDialog(selected, available, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        categories = dialog.selected_categories()
        if not categories:
            QMessageBox.information(self, "確定情報を追記", "追記するカテゴリを1つ以上選択してください。")
            return
        answer = QMessageBox.question(
            self,
            "確定情報を追記",
            "選択した確定情報をTXTの文頭へ書き込みます。\n"
            "既存の管理ブロックがある場合は置き換えます。伝説本文は変更しません。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            with self._busy("確定情報を書き込み中"):
                self.service.embed_information(self.current_legend_id, categories)
            self.reader_settings_store.save_embed_categories(categories)
            self.show_legend(self.current_legend_id)
            self.status_label.setText("確定情報を文頭に追記しました")
        except Exception as exception:
            self._show_error("確定情報を追記できませんでした", exception)

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
        self._set_reader_document(
            render_reader_html(
                self.current_body_text,
                self.reader_settings,
                document_key=self.current_reader_key,
            ),
            self.current_reader_key,
        )

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
        if not success:
            return
        self.body_view.page().runJavaScript(
            "document.body ? (document.body.dataset.legendKey || '') : ''",
            self._validate_reader_document,
        )

    def _set_reader_document(self, document_html: str, document_key: str) -> None:
        self.current_reader_html = document_html
        self.current_reader_key = document_key
        self.body_view.setHtml(document_html)

    def _set_reader_body(
        self,
        body_html: str,
        document_key: str,
        document_html: str,
    ) -> None:
        self.current_reader_body_html = body_html
        self.current_reader_html = document_html
        self.current_reader_key = document_key
        script = (
            "(() => {"
            "const body = document.body;"
            "if (!body) return null;"
            f"body.dataset.legendKey = {json.dumps(document_key, ensure_ascii=False)};"
            f"body.innerHTML = {json.dumps(body_html, ensure_ascii=False)};"
            "return body.dataset.legendKey;"
            "})()"
        )
        self.body_view.page().runJavaScript(script, self._validate_reader_document)

    def _validate_reader_document(self, actual_key: object) -> None:
        if actual_key is None:
            return
        if str(actual_key or "") != self.current_reader_key:
            if self.current_reader_body_html:
                self._set_reader_body(
                    self.current_reader_body_html,
                    self.current_reader_key,
                    self.current_reader_html,
                )
            return
        ratio = self._pending_scroll_ratio
        self._pending_scroll_ratio = 0.0
        if ratio > 0:
            self.body_view.page().runJavaScript(
                f"window.scrollTo(0, Math.max(0, document.documentElement.scrollHeight - window.innerHeight) * {ratio!r});"
            )
        if self.body_search_frame.isVisible():
            self._run_body_search()

    def _capture_reader_position(self) -> None:
        if self.current_legend_id is None or not self.current_content_sha256:
            return
        legend_id = self.current_legend_id
        content_sha256 = self.current_content_sha256
        script = """
            (() => {
                const maximum = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
                return maximum > 0 ? window.scrollY / maximum : 0;
            })()
        """

        def store_position(value: object) -> None:
            try:
                ratio = float(value)
            except (TypeError, ValueError):
                return
            self.reader_settings_store.save_position(legend_id, content_sha256, ratio)

        self.body_view.page().runJavaScript(script, store_position)

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

    def open_mod_settings(self) -> None:
        game_root = self.service.paths.game_root
        if game_root is None or not is_game_root(game_root):
            QMessageBox.warning(
                self,
                "MOD設定",
                "先に「パス設定」でゲーム本体の場所を指定してください。",
            )
            return
        config_path = game_root / "BepInEx" / "config" / "lom.jp.legendmanager.cfg"
        if not config_path.is_file():
            QMessageBox.warning(
                self,
                "MOD設定",
                "MOD設定ファイルがまだ生成されていません。\n"
                "LOM Legend Managerを配置した状態で、ゲームを一度起動してください。",
            )
            return
        try:
            values = read_mod_settings(config_path)
        except Exception as exception:
            self._show_error("MOD設定を読み込めませんでした", exception)
            return
        dialog = ModSettingsDialog(values, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if is_game_running():
            QMessageBox.warning(
                self,
                "MOD設定",
                "ゲームの実行中はMOD設定を書き換えません。\nゲームを終了してから保存してください。",
            )
            return
        try:
            backup = write_mod_settings(config_path, dialog.values())
            QMessageBox.information(
                self,
                "MOD設定",
                "MOD設定を保存しました。変更は次回ゲーム起動時から反映されます。\n"
                f"バックアップ: {backup.name}",
            )
        except Exception as exception:
            self._show_error("MOD設定を保存できませんでした", exception)

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
