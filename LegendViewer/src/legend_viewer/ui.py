from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from PySide6.QtCore import QSignalBlocker, QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStyle,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .catalog import TagDefinition
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


class SpoilerTagDialog(QDialog):
    def __init__(
        self,
        tags: list[TagDefinition],
        assigned_ids: set[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ネタバレタグを追加")
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


class LegendMainWindow(QMainWindow):
    def __init__(self, service: LegendService) -> None:
        super().__init__()
        self.service = service
        self.current_legend_id: int | None = None
        self._directory_signature: tuple[int, int, int] | None = None
        self._refreshing = False

        self.setWindowTitle("活俠伝 伝説管理")
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
        self.category_combo.currentIndexChanged.connect(self.refresh_list)

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

    def _build_ui(self) -> None:
        toolbar = QToolBar("メイン", self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.addAction(self.sync_action)
        toolbar.addAction(self.open_folder_action)
        toolbar.addSeparator()
        toolbar.addAction(self.backup_action)
        self.addToolBar(toolbar)

        root_splitter = QSplitter(Qt.Orientation.Horizontal)
        root_splitter.setChildrenCollapsible(False)
        root_splitter.addWidget(self._build_library_panel())
        root_splitter.addWidget(self._build_reader_panel())
        root_splitter.addWidget(self._build_detail_panel())
        root_splitter.setSizes([360, 700, 420])
        root_splitter.setStretchFactor(0, 0)
        root_splitter.setStretchFactor(1, 1)
        root_splitter.setStretchFactor(2, 0)
        self.setCentralWidget(root_splitter)

        self.status_label = QLabel("準備中")
        self.statusBar().addPermanentWidget(self.status_label)

    def _build_library_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("libraryPanel")
        panel.setMinimumWidth(300)
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

        self.category_combo = QComboBox()
        self._constrain_combo(self.category_combo, 14)
        self.category_combo.addItem("すべてのタグ", None)
        for category in self.service.catalog.categories:
            self.category_combo.addItem(category["label"], category["id"])
        layout.addWidget(self.category_combo)

        self.legend_tree = QTreeWidget()
        self.legend_tree.setHeaderLabels(["ED", "結縁", "日時", "状態"])
        self.legend_tree.setRootIsDecorated(False)
        self.legend_tree.setAlternatingRowColors(True)
        self.legend_tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.legend_tree.setUniformRowHeights(True)
        self.legend_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header = self.legend_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
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

        self.body_edit = QPlainTextEdit()
        self.body_edit.setReadOnly(True)
        self.body_edit.setPlaceholderText("選択した伝説の本文がここに表示されます。")
        self.body_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.body_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.body_edit, 1)

        action_row = QHBoxLayout()
        self.open_file_button = QPushButton("ファイルを開く")
        self.open_file_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        self.open_file_button.clicked.connect(self.open_current_file)
        self.rename_button = QPushButton("ED名と結縁相手でリネーム")
        self.rename_button.clicked.connect(self.rename_current)
        self.embed_button = QPushButton("確定済みのタグを文頭に追記")
        self.embed_button.setObjectName("primaryButton")
        self.embed_button.clicked.connect(self.embed_current_tags)
        action_row.addWidget(self.open_file_button)
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

        tag_group = QGroupBox("タグ")
        tag_layout = QVBoxLayout(tag_group)
        self.tag_list = QListWidget()
        self.tag_list.setMinimumHeight(180)
        tag_layout.addWidget(self.tag_list)

        add_tag_row = QHBoxLayout()
        self.tag_combo = QComboBox()
        self._constrain_combo(self.tag_combo, 18)
        self.add_tag_button = QPushButton("追加")
        self.add_tag_button.clicked.connect(self.add_selected_tag)
        add_tag_row.addWidget(self.tag_combo, 1)
        add_tag_row.addWidget(self.add_tag_button)
        tag_layout.addLayout(add_tag_row)

        tag_command_row = QHBoxLayout()
        self.remove_tag_button = QPushButton("選択タグを外す")
        self.remove_tag_button.clicked.connect(self.remove_selected_tag)
        self.spoiler_button = QPushButton("ネタバレタグを追加")
        self.spoiler_button.setObjectName("spoilerButton")
        self.spoiler_button.clicked.connect(self.add_spoiler_tags)
        tag_command_row.addWidget(self.remove_tag_button)
        tag_command_row.addStretch(1)
        tag_command_row.addWidget(self.spoiler_button)
        tag_layout.addLayout(tag_command_row)

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
            #panelHeading { font-size: 18px; font-weight: 700; }
            #readerTitle { font-size: 21px; font-weight: 700; }
            #dialogHeading { font-size: 16px; font-weight: 700; }
            #mutedLabel { color: #637064; }
            QLineEdit, QComboBox, QPlainTextEdit, QListWidget, QTreeWidget {
                background: #ffffff; border: 1px solid #cfd7d0; border-radius: 5px; padding: 5px;
                selection-background-color: #2d6f5b; selection-color: #ffffff;
            }
            QTreeWidget { padding: 0; alternate-background-color: #f4f7f4; }
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
            self.search_edit.text(), self.category_combo.currentData()
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
            item = QTreeWidgetItem([title, heroine, exported, " / ".join(states)])
            item.setData(0, Qt.ItemDataRole.UserRole, int(row["id"]))
            item.setToolTip(0, row["current_file_name"])
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
        self.body_edit.setPlainText(legend.get("plain_text") or "")

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
        self._fill_tag_combo(legend)
        enabled = not bool(legend["file_missing"])
        for button in (self.open_file_button, self.rename_button, self.embed_button):
            button.setEnabled(enabled)

    def _fill_tag_list(self, legend: dict) -> None:
        self.tag_list.clear()
        for tag in legend["tags"]:
            source = self._source_label(tag["source"])
            category = CATEGORY_LABELS.get(tag["category"], tag["category"])
            item = QListWidgetItem(f"{tag['label']}    [{category} / {source}]")
            item.setData(Qt.ItemDataRole.UserRole, tag["id"])
            self.tag_list.addItem(item)

    def _fill_tag_combo(self, legend: dict) -> None:
        assigned = {tag["id"] for tag in legend["tags"]}
        blocker = QSignalBlocker(self.tag_combo)
        self.tag_combo.clear()
        self.tag_combo.addItem("追加するタグを選択", None)
        for tag in self.service.catalog.ordered_tags(include_spoilers=False):
            if tag.category in ("ending", "heroine") or tag.id in assigned:
                continue
            category = CATEGORY_LABELS.get(tag.category, tag.category)
            self.tag_combo.addItem(f"[{category}] {tag.label}", tag.id)
        del blocker

    def _clear_detail(self) -> None:
        self.title_label.setText("伝説がありません")
        self.subtitle_label.clear()
        self.body_edit.clear()
        self.tag_list.clear()
        self.tag_combo.clear()
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

    def add_selected_tag(self) -> None:
        if self.current_legend_id is None or self.tag_combo.currentData() is None:
            return
        try:
            self.service.add_tag(self.current_legend_id, str(self.tag_combo.currentData()))
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
        dialog = SpoilerTagDialog(candidates, assigned, self)
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
        if self.current_legend_id is None or self.tag_list.currentItem() is None:
            return
        tag_id = str(self.tag_list.currentItem().data(Qt.ItemDataRole.UserRole))
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

    def open_legend_directory(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.service.paths.legend_directory)))

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
