using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using BepInEx.Logging;
using HarmonyLib;
using Mortal.Core;
using Newtonsoft.Json;

namespace LegendManager.Plugin
{
    internal sealed class LegendManagerService : IDisposable
    {
        private static readonly Encoding Utf8WithoutBom = new UTF8Encoding(false);
        private static readonly System.Reflection.FieldInfo CurrentLegendSlotField =
            AccessTools.Field(typeof(LibraryPanel), "_currentLegendSlot");
        private static readonly System.Reflection.MethodInfo GetLegendDataFileMethod =
            AccessTools.Method(typeof(SaveSystem), "GetLegendDataFile", new[] { typeof(int) });
        private static readonly Dictionary<int, string> RelationshipNames = new Dictionary<int, string>
        {
            { 0, "小師妹" }, { 1, "大師兄" }, { 2, "二師兄" }, { 3, "三師兄" },
            { 4, "四師兄" }, { 5, "掌門人" }, { 6, "瑞杏" }, { 7, "葉雲舟" },
            { 8, "葉雲裳" }, { 9, "樊嘯天" }, { 10, "万里鵬程" }, { 11, "劉顎" },
            { 12, "龍湘" }, { 13, "龍淵" }, { 14, "石公遠" }, { 102, "南宮深" },
            { 103, "南宮浅" }, { 205, "尹志平" }, { 206, "福韞" }, { 401, "王二壮" },
            { 403, "趙逵" }, { 404, "丹霞子" }, { 405, "申屠龍" }, { 409, "車軒轅" },
            { 605, "虞小梅" }, { 606, "夏侯蘭" }, { 607, "郁竹" }, { 608, "魏菊" },
            { 609, "上官螢" }, { 800, "宋悲" }, { 808, "解無塵" }, { 809, "李富貴" },
            { 825, "夏霊犀" }, { 999, "瑞笙" }, { 990, "葉雲啾" }, { 991, "葉雲啾" }
        };
        private static readonly int[] AbilityStatTypes =
        {
            0, 1, 2, 5, 6, 12, 17, 18, 20, 22, 23, 100, 101, 102
        };

        private readonly ManualLogSource _logger;
        private readonly Catalog _catalog;
        private EndingPictureExporter _pictureExporter;
        private readonly string _nativeLegendDirectory;
        private string _legendDirectory;
        private readonly string _managerDirectory;
        private readonly string _inboxDirectory;
        private readonly string _processedDirectory;
        private readonly string _slotMetadataDirectory;
        private readonly string _autoExportDirectory;
        private readonly bool _renameFiles;
        private readonly bool _processExisting;
        private readonly bool _matchExistingFiles;
        private readonly bool _autoExportOnSave;
        private readonly int _existingSlotScanLimit;
        private readonly int _debounceMilliseconds;
        private readonly object _existingMatchLock = new object();
        private readonly ConcurrentDictionary<string, long> _pendingFiles =
            new ConcurrentDictionary<string, long>(StringComparer.OrdinalIgnoreCase);
        private readonly ConcurrentDictionary<string, string> _processedFileStates =
            new ConcurrentDictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        private readonly CancellationTokenSource _cancellation = new CancellationTokenSource();

        private FileSystemWatcher _watcher;
        private bool _existingMatchCompleted;
        private bool _disposed;

        public bool UsingLegendDirectoryFallback { get; private set; }

        public LegendManagerService(
            ManualLogSource logger,
            string presetPath,
            string tagCatalogPath,
            string persistentRoot,
            bool renameFiles,
            bool processExisting,
            bool matchExistingFiles,
            bool autoExportOnSave,
            int existingSlotScanLimit,
            int debounceMilliseconds)
        {
            _logger = logger;
            _catalog = Catalog.Load(presetPath, tagCatalogPath);
            _nativeLegendDirectory = Path.Combine(persistentRoot, "Legend");
            _managerDirectory = Path.Combine(persistentRoot, "LegendManager");
            _inboxDirectory = Path.Combine(_managerDirectory, "inbox");
            _processedDirectory = Path.Combine(_managerDirectory, "processed");
            _slotMetadataDirectory = Path.Combine(_managerDirectory, "slots");
            _autoExportDirectory = Path.Combine(_managerDirectory, "auto-export-temp");
            _legendDirectory = ResolveLegendDirectory();
            _pictureExporter = new EndingPictureExporter(_legendDirectory);
            _renameFiles = renameFiles;
            _processExisting = processExisting;
            _matchExistingFiles = matchExistingFiles;
            _autoExportOnSave = autoExportOnSave;
            _existingSlotScanLimit = existingSlotScanLimit;
            _debounceMilliseconds = debounceMilliseconds;
        }

        public void Start()
        {
            Directory.CreateDirectory(_nativeLegendDirectory);
            Directory.CreateDirectory(_legendDirectory);
            Directory.CreateDirectory(_inboxDirectory);
            Directory.CreateDirectory(_processedDirectory);
            Directory.CreateDirectory(_slotMetadataDirectory);
            Directory.CreateDirectory(_autoExportDirectory);

            _watcher = new FileSystemWatcher(_nativeLegendDirectory, "LOM_Legend_*.txt")
            {
                IncludeSubdirectories = false,
                NotifyFilter = NotifyFilters.FileName | NotifyFilters.CreationTime | NotifyFilters.LastWrite | NotifyFilters.Size
            };
            _watcher.Created += OnFileChanged;
            _watcher.Changed += OnFileChanged;
            _watcher.Renamed += OnFileRenamed;
            _watcher.Error += OnWatcherError;
            _watcher.EnableRaisingEvents = true;

            _logger.LogInfo("Native legend directory: " + _nativeLegendDirectory);
            _logger.LogInfo("Legend output directory: " + _legendDirectory);
            _logger.LogInfo("Legend Manager inbox: " + _inboxDirectory);

            if (_processExisting)
            {
                QueueExistingFiles();
            }
        }

        public bool TryMatchExistingFilesToSlots()
        {
            if (!_matchExistingFiles || _existingMatchCompleted || _disposed)
            {
                return true;
            }

            lock (_existingMatchLock)
            {
                if (_existingMatchCompleted || _disposed)
                {
                    return true;
                }

                try
                {
                    SaveSystem saveSystem = SaveSystem.Instance;
                    ILocaleResolver resolver = LocalizationManager.Instance?.LocaleResolver;
                    if (saveSystem == null || resolver == null)
                    {
                        return false;
                    }
                    if (GetLegendDataFileMethod == null)
                    {
                        throw new MissingMethodException(typeof(SaveSystem).FullName, "GetLegendDataFile");
                    }

                    var candidatesByHash = new Dictionary<string, List<ExistingSlotCandidate>>(StringComparer.OrdinalIgnoreCase);
                    int loadedSlots = 0;
                    for (int slot = 1; slot <= _existingSlotScanLimit; slot++)
                    {
                        string dataPath = (string)GetLegendDataFileMethod.Invoke(saveSystem, new object[] { slot });
                        if (string.IsNullOrWhiteSpace(dataPath) || !File.Exists(dataPath))
                        {
                            continue;
                        }

                        LegendSave legend = saveSystem.GetLegendSaveData(slot);
                        if (legend == null)
                        {
                            continue;
                        }

                        loadedSlots++;
                        List<string> storyKeys = GetStoryKeys(legend);
                        string body = BuildLegendBody(storyKeys, resolver);
                        string hash = TextFileOperations.ComputeSha256(Utf8WithoutBom.GetBytes(body));
                        var candidate = new ExistingSlotCandidate
                        {
                            Slot = slot,
                            EndKey = legend.EndKey,
                            TimeTick = legend.TimeTick,
                            StoryKeys = storyKeys,
                            StoryKeySha256 = TextFileOperations.ComputeStoryKeySha256(storyKeys)
                        };

                        if (!candidatesByHash.TryGetValue(hash, out List<ExistingSlotCandidate> candidates))
                        {
                            candidates = new List<ExistingSlotCandidate>();
                            candidatesByHash.Add(hash, candidates);
                        }
                        candidates.Add(candidate);
                    }

                    if (loadedSlots == 0)
                    {
                        return false;
                    }

                    int matchedFiles = 0;
                    int ambiguousFiles = 0;
                    foreach (string path in Directory.EnumerateFiles(_legendDirectory, "*.txt"))
                    {
                        TextDocumentInfo document;
                        try
                        {
                            document = TextFileOperations.Read(path);
                        }
                        catch (Exception exception)
                        {
                            _logger.LogWarning("既存伝説TXTを読み込めませんでした: " + path);
                            _logger.LogWarning(exception);
                            continue;
                        }

                        if (!candidatesByHash.TryGetValue(document.ContentSha256, out List<ExistingSlotCandidate> matches))
                        {
                            continue;
                        }

                        List<string> endKeys = matches
                            .Select(match => match.EndKey)
                            .Distinct(StringComparer.Ordinal)
                            .ToList();
                        if (endKeys.Count != 1)
                        {
                            ambiguousFiles++;
                            _logger.LogWarning("同じ本文に複数のED候補があるため確定しません: " + Path.GetFileName(path));
                            continue;
                        }

                        ExistingSlotCandidate selected = matches[0];
                        if (!_catalog.TryGetEnding(selected.EndKey, out TitleInfo title))
                        {
                            _logger.LogWarning("プリセットにないEDのため確定できません: " + selected.EndKey);
                            continue;
                        }

                        WriteExistingMatchEvent(
                            path,
                            document,
                            selected,
                            title,
                            "existing_slot_exact",
                            "saved_legend_body",
                            "exact");
                        matchedFiles++;
                    }

                    _existingMatchCompleted = true;
                    _logger.LogInfo(
                        "Existing legend match completed. slots=" + loadedSlots.ToString(CultureInfo.InvariantCulture) +
                        ", matched=" + matchedFiles.ToString(CultureInfo.InvariantCulture) +
                        ", ambiguous=" + ambiguousFiles.ToString(CultureInfo.InvariantCulture));
                    return true;
                }
                catch (Exception exception)
                {
                    _logger.LogWarning("既存伝説のスロット照合を再試行します。");
                    _logger.LogWarning(exception);
                    return false;
                }
            }
        }

        public ExportResult HandleLegendSaved(SaveSystem saveSystem, int slot, string endKey)
        {
            LegendSave legend = saveSystem.GetLegendSaveData(slot);
            if (legend == null)
            {
                _logger.LogWarning("保存後の伝説データを取得できませんでした。slot=" + slot);
                return null;
            }

            List<string> storyKeys = GetStoryKeys(legend);
            ParameterSnapshot parameters = CaptureParameters();
            string storyKeySha256 = TextFileOperations.ComputeStoryKeySha256(storyKeys);
            SlotMetadata previousMetadata = ReadSlotMetadata(slot);
            var metadata = new SlotMetadata
            {
                Slot = slot,
                EndKey = endKey,
                TitlePartner = saveSystem.TitlePartner,
                TimeTick = legend.TimeTick,
                StoryKeySha256 = storyKeySha256,
                CapturedAt = DateTimeOffset.Now.ToString("o", CultureInfo.InvariantCulture),
                Parameters = parameters
            };
            if (previousMetadata != null &&
                previousMetadata.EndKey == endKey &&
                previousMetadata.TimeTick == legend.TimeTick &&
                previousMetadata.StoryKeySha256 == storyKeySha256)
            {
                metadata.LastExportFullPath = previousMetadata.LastExportFullPath;
                metadata.LastExportContentSha256 = previousMetadata.LastExportContentSha256;
            }

            string path = GetSlotMetadataPath(slot);
            AtomicWriteJson(path, metadata);
            _logger.LogInfo(
                "Legend slot metadata captured. slot=" + slot +
                ", endKey=" + endKey +
                ", partner=" + metadata.TitlePartner);

            if (!_autoExportOnSave)
            {
                return null;
            }

            ExportContext context = CreateExportContext(saveSystem, slot, legend);
            context.Parameters = parameters;
            context.ExistingExportPath = metadata.LastExportFullPath;
            context.ExistingExportContentSha256 = metadata.LastExportContentSha256;
            string sourcePath = WriteExportFile(context, _autoExportDirectory);
            return ProcessFile(sourcePath, context, "auto_save");
        }

        public void SaveDisplayedEndingPicture(int slot, byte[] png)
        {
            LegendSave legend = SaveSystem.Instance?.GetLegendSaveData(slot);
            if (legend == null || !_catalog.TryGetEnding(legend.EndKey, out TitleInfo title))
            {
                return;
            }

            _pictureExporter.SavePng(title.TitleId, png);
            _logger.LogInfo("Displayed ED picture captured: " + title.TitleId);
        }

        public ExportContext BeginExport(LibraryPanel panel)
        {
            if (CurrentLegendSlotField == null)
            {
                throw new MissingFieldException(typeof(LibraryPanel).FullName, "_currentLegendSlot");
            }

            int slot = (int)CurrentLegendSlotField.GetValue(panel);
            SaveSystem saveSystem = SaveSystem.Instance;
            LegendSave legend = saveSystem.GetLegendSaveData(slot);
            if (legend == null)
            {
                throw new InvalidOperationException("選択中の伝説スロットを読み込めません。slot=" + slot);
            }

            ExportContext context = CreateExportContext(saveSystem, slot, legend);

            SlotMetadata metadata = ReadSlotMetadata(slot);
            if (metadata != null &&
                metadata.EndKey == context.EndKey &&
                metadata.TimeTick == context.TimeTick &&
                metadata.StoryKeySha256 == context.StoryKeySha256)
            {
                context.PartnerId = metadata.TitlePartner;
                context.Parameters = metadata.Parameters;
                context.ExistingExportPath = metadata.LastExportFullPath;
                context.ExistingExportContentSha256 = metadata.LastExportContentSha256;
            }

            return context;
        }

        private ExportContext CreateExportContext(SaveSystem saveSystem, int slot, LegendSave legend)
        {
            List<string> storyKeys = GetStoryKeys(legend);
            return new ExportContext
            {
                StartedAt = DateTime.Now,
                Slot = slot,
                EndKey = legend.EndKey,
                TimeTick = legend.TimeTick,
                StoryKeys = storyKeys,
                StoryKeySha256 = TextFileOperations.ComputeStoryKeySha256(storyKeys),
                PartnerId = saveSystem.TitlePartner,
                ExistingFiles = new HashSet<string>(
                    Directory.EnumerateFiles(_nativeLegendDirectory, "LOM_Legend_*.txt")
                        .Select(Path.GetFullPath),
                    StringComparer.OrdinalIgnoreCase)
            };
        }

        public ExportResult CompleteExport(ExportContext context)
        {
            List<string> newFiles = Directory
                .EnumerateFiles(_nativeLegendDirectory, "LOM_Legend_*.txt")
                .Select(Path.GetFullPath)
                .Where(path => !context.ExistingFiles.Contains(path))
                .ToList();

            if (newFiles.Count == 0)
            {
                string fallback = WriteFallbackExport(context);
                newFiles.Add(fallback);
                _logger.LogWarning("同一秒のファイル名衝突を検出し、別名でエクスポートしました。");
            }

            ExportResult result = null;
            foreach (string path in newFiles)
            {
                result = ProcessFile(path, context, "manual_export");
            }
            return result;
        }

        private string WriteFallbackExport(ExportContext context)
        {
            string stem = "LOM_Legend_" + DateTime.Now.ToString("yyyyMMddHHmmss", CultureInfo.InvariantCulture);
            string path = Path.Combine(_nativeLegendDirectory, stem + "_2.txt");
            int suffix = 2;
            while (File.Exists(path))
            {
                suffix++;
                path = Path.Combine(_nativeLegendDirectory, stem + "_" + suffix.ToString(CultureInfo.InvariantCulture) + ".txt");
            }

            ILocaleResolver resolver = LocalizationManager.Instance.LocaleResolver;
            using (var writer = new StreamWriter(path, false, Utf8WithoutBom))
            {
                foreach (string storyKey in context.StoryKeys)
                {
                    string text = resolver.GetString("LegendInfo/" + storyKey);
                    if (!string.IsNullOrEmpty(text))
                    {
                        writer.WriteLine(text);
                    }
                }
            }

            return path;
        }

        private string WriteExportFile(ExportContext context, string directory)
        {
            Directory.CreateDirectory(directory);
            string stem = "LOM_Legend_" + DateTime.Now.ToString("yyyyMMddHHmmss", CultureInfo.InvariantCulture);
            string path = Path.Combine(directory, stem + ".txt");
            int suffix = 1;
            while (File.Exists(path))
            {
                suffix++;
                path = Path.Combine(directory, stem + "_" + suffix.ToString(CultureInfo.InvariantCulture) + ".txt");
            }

            ILocaleResolver resolver = LocalizationManager.Instance.LocaleResolver;
            using (var writer = new StreamWriter(path, false, Utf8WithoutBom))
            {
                foreach (string storyKey in context.StoryKeys)
                {
                    string text = resolver.GetString("LegendInfo/" + storyKey);
                    if (!string.IsNullOrEmpty(text))
                    {
                        writer.WriteLine(text);
                    }
                }
            }
            return path;
        }

        private static string FindExistingContentPath(
            string contentSha256,
            string sourcePath,
            ExportContext context)
        {
            if (context == null ||
                string.IsNullOrWhiteSpace(context.ExistingExportPath) ||
                !string.Equals(
                    context.ExistingExportContentSha256,
                    contentSha256,
                    StringComparison.OrdinalIgnoreCase))
            {
                return null;
            }

            string candidate = Path.GetFullPath(context.ExistingExportPath);
            if (string.Equals(candidate, Path.GetFullPath(sourcePath), StringComparison.OrdinalIgnoreCase) ||
                !File.Exists(candidate))
            {
                return null;
            }
            return string.Equals(
                TextFileOperations.Read(candidate).ContentSha256,
                contentSha256,
                StringComparison.OrdinalIgnoreCase)
                ? candidate
                : null;
        }

        private string BuildUnrenamedTargetPath(string fileName)
        {
            string candidate = Path.Combine(_legendDirectory, fileName);
            if (!File.Exists(candidate))
            {
                return candidate;
            }

            string stem = Path.GetFileNameWithoutExtension(fileName);
            string extension = Path.GetExtension(fileName);
            for (int suffix = 2; suffix < 10000; suffix++)
            {
                candidate = Path.Combine(
                    _legendDirectory,
                    stem + "_" + suffix.ToString(CultureInfo.InvariantCulture) + extension);
                if (!File.Exists(candidate))
                {
                    return candidate;
                }
            }
            throw new IOException("エクスポート先の空きファイル名を確保できませんでした。");
        }

        private static void MoveFile(string sourcePath, string targetPath)
        {
            string directory = Path.GetDirectoryName(targetPath);
            if (!string.IsNullOrEmpty(directory))
            {
                Directory.CreateDirectory(directory);
            }

            try
            {
                File.Move(sourcePath, targetPath);
            }
            catch (IOException)
            {
                File.Copy(sourcePath, targetPath, false);
                File.Delete(sourcePath);
            }
        }

        private string MoveToOutputDirectory(
            string sourcePath,
            string originalFileName,
            TitleInfo title,
            string titleName,
            string heroine,
            DateTime exportedAt,
            string hash8)
        {
            for (int attempt = 0; attempt < 2; attempt++)
            {
                string targetPath = _renameFiles
                    ? TextFileOperations.BuildTargetPath(
                        sourcePath,
                        _legendDirectory,
                        title?.FilePrefix,
                        titleName,
                        heroine,
                        exportedAt,
                        hash8)
                    : BuildUnrenamedTargetPath(originalFileName);
                if (string.Equals(sourcePath, targetPath, StringComparison.OrdinalIgnoreCase))
                {
                    return sourcePath;
                }

                try
                {
                    MoveFile(sourcePath, targetPath);
                    return targetPath;
                }
                catch (Exception exception) when (
                    (exception is IOException || exception is UnauthorizedAccessException) &&
                    !string.Equals(_legendDirectory, _nativeLegendDirectory, StringComparison.OrdinalIgnoreCase))
                {
                    ActivateRuntimeFallback(exception);
                }
            }
            throw new IOException("標準のLegendフォルダへエクスポートできませんでした。");
        }

        private void ActivateRuntimeFallback(Exception exception)
        {
            UsingLegendDirectoryFallback = true;
            _logger.LogWarning("指定保存先を使用できないため標準のLegendフォルダへ切り替えます。");
            _logger.LogWarning(exception);
            _legendDirectory = _nativeLegendDirectory;
            Directory.CreateDirectory(_legendDirectory);
            _pictureExporter = new EndingPictureExporter(_legendDirectory);
            Plugin.ShowAutoExportNotification("指定保存先を使用できないため標準のLegendフォルダへ保存します。");
        }

        private string ResolveLegendDirectory()
        {
            string configured = null;
            string settingsPath = Path.Combine(_managerDirectory, "settings.json");
            try
            {
                if (File.Exists(settingsPath))
                {
                    SharedPathSettings settings = JsonConvert.DeserializeObject<SharedPathSettings>(
                        File.ReadAllText(settingsPath, Utf8WithoutBom));
                    configured = settings?.LegendDirectory;
                }
            }
            catch (Exception exception)
            {
                _logger.LogWarning("共有パス設定を読み込めないため標準保存先を使用します。");
                _logger.LogWarning(exception);
            }

            if (string.IsNullOrWhiteSpace(configured))
            {
                return _nativeLegendDirectory;
            }

            try
            {
                string resolved = Path.GetFullPath(configured);
                Directory.CreateDirectory(resolved);
                string marker = Path.Combine(resolved, ".lom_write_test_" + Guid.NewGuid().ToString("N") + ".tmp");
                File.WriteAllText(marker, "ok", Utf8WithoutBom);
                File.Delete(marker);
                return resolved;
            }
            catch (Exception exception)
            {
                UsingLegendDirectoryFallback = true;
                _logger.LogWarning("指定された伝説保存先を使用できないため標準保存先へフォールバックします: " + configured);
                _logger.LogWarning(exception);
                return _nativeLegendDirectory;
            }
        }

        private ExportResult ProcessFile(string sourcePath, ExportContext context, string source)
        {
            if (!File.Exists(sourcePath))
            {
                return null;
            }

            FileInfo sourceInfo = new FileInfo(sourcePath);
            string state = sourceInfo.Length.ToString(CultureInfo.InvariantCulture) + ":" +
                           sourceInfo.LastWriteTimeUtc.Ticks.ToString(CultureInfo.InvariantCulture);
            if (context == null && _processedFileStates.TryGetValue(sourcePath, out string previousState) && previousState == state)
            {
                return null;
            }

            TextDocumentInfo document = TextFileOperations.Read(sourcePath);
            DateTime exportedAt = TextFileOperations.GetExportedAt(sourceInfo.Name, sourceInfo.LastWriteTime);

            TitleInfo title = null;
            string endKey = context?.EndKey;
            if (context != null)
            {
                _catalog.TryGetEnding(context.EndKey, out title);
            }

            string heroine;
            string heroineTagId;
            string heroineBasis;
            bool heroineKnown = _catalog.TryResolveUnion(
                context?.StoryKeys,
                title,
                out heroine,
                out heroineTagId,
                out heroineBasis);
            if (!heroineKnown)
            {
                heroine = "結縁相手不明";
            }

            string titlePartnerName;
            Catalog.TryGetHeroine(context?.PartnerId, out titlePartnerName);

            string titleName = title?.JpName ?? "ED名不明";
            string currentPath = sourcePath;
            bool reusedExisting = false;
            if (context != null)
            {
                string existingPath = FindExistingContentPath(document.ContentSha256, sourcePath, context);
                if (existingPath != null)
                {
                    File.Delete(sourcePath);
                    currentPath = existingPath;
                    reusedExisting = true;
                }
                else
                {
                    currentPath = MoveToOutputDirectory(
                        sourcePath,
                        sourceInfo.Name,
                        title,
                        titleName,
                        heroine,
                        exportedAt,
                        document.ContentSha256.Substring(0, 8));
                }
            }

            TextDocumentInfo currentDocument = string.Equals(
                sourcePath,
                currentPath,
                StringComparison.OrdinalIgnoreCase)
                ? document
                : TextFileOperations.Read(currentPath);

            var exportEvent = new ExportEvent
            {
                EventId = Guid.NewGuid().ToString("N"),
                Source = source,
                Slot = context?.Slot,
                EndKey = endKey,
                TitleId = title?.TitleId,
                FilePrefix = title?.FilePrefix,
                TitleName = titleName,
                TitleTag = title?.TagLabel,
                PartnerId = context?.PartnerId,
                TitlePartnerName = titlePartnerName,
                Heroine = heroine,
                ExportedAt = new DateTimeOffset(exportedAt).ToString("o", CultureInfo.InvariantCulture),
                OriginalFileName = sourceInfo.Name,
                CurrentFileName = Path.GetFileName(currentPath),
                FullPath = Path.GetFullPath(currentPath),
                ContentSha256 = document.ContentSha256,
                NormalizedSha256 = currentDocument.NormalizedSha256,
                FileSha256 = currentDocument.FileSha256,
                Hash8 = document.ContentSha256.Substring(0, 8),
                FileSize = currentDocument.FileSize,
                StoryKeys = context?.StoryKeys ?? new List<string>(),
                StoryKeySha256 = context?.StoryKeySha256,
                Parameters = context?.Parameters
            };

            if (title != null)
            {
                exportEvent.ConfirmedTags.Add(new ConfirmedTag
                {
                    Id = "ending." + title.TitleId.ToString(CultureInfo.InvariantCulture),
                    Label = title.TagLabel,
                    Category = "ending",
                    Basis = "game_end_key",
                    Confidence = "exact"
                });
            }
            else
            {
                exportEvent.Warnings.Add("ED名を確定できませんでした。");
            }

            if (heroineKnown)
            {
                exportEvent.ConfirmedTags.Add(new ConfirmedTag
                {
                    Id = heroineTagId,
                    Label = heroine,
                    Category = "heroine",
                    Basis = heroineBasis,
                    Confidence = "exact"
                });
            }
            else
            {
                exportEvent.Warnings.Add("結縁成立を確定できるStory keyがありません。");
            }

            if (context != null && title != null)
            {
                try
                {
                    _pictureExporter.Export(context.EndKey, title.TitleId);
                }
                catch (Exception exception)
                {
                    exportEvent.Warnings.Add("ED画像を回収できませんでした。");
                    _logger.LogWarning("ED画像の回収に失敗しました: " + context.EndKey);
                    _logger.LogWarning(exception);
                }
            }

            string eventPath = Path.Combine(
                _inboxDirectory,
                DateTime.Now.ToString("yyyyMMddHHmmssfff", CultureInfo.InvariantCulture) + "_" + exportEvent.EventId + ".json");
            AtomicWriteJson(eventPath, exportEvent);

            _processedFileStates[currentPath] = state;
            if (context != null)
            {
                RememberExport(context, currentPath, document.ContentSha256);
            }
            _logger.LogInfo("Legend processed: " + exportEvent.CurrentFileName);
            return new ExportResult { FullPath = currentPath, ReusedExisting = reusedExisting };
        }

        private void WriteExistingMatchEvent(
            string path,
            TextDocumentInfo document,
            ExistingSlotCandidate candidate,
            TitleInfo title,
            string source,
            string basis,
            string confidence)
        {
            string eventId = TextFileOperations.ComputeSha256(Utf8WithoutBom.GetBytes(
                source + "\0" + Path.GetFullPath(path) + "\0" + document.ContentSha256 + "\0" + candidate.EndKey));
            string eventFileName = "existing_" + eventId + ".json";
            if (File.Exists(Path.Combine(_inboxDirectory, eventFileName)) ||
                File.Exists(Path.Combine(_processedDirectory, eventFileName)))
            {
                return;
            }

            int? partnerId = null;
            SlotMetadata metadata = ReadSlotMetadata(candidate.Slot);
            if (metadata != null &&
                metadata.EndKey == candidate.EndKey &&
                metadata.TimeTick == candidate.TimeTick &&
                metadata.StoryKeySha256 == candidate.StoryKeySha256)
            {
                partnerId = metadata.TitlePartner;
            }

            string heroine;
            string heroineTagId;
            string heroineBasis;
            bool heroineKnown = _catalog.TryResolveUnion(
                candidate.StoryKeys,
                title,
                out heroine,
                out heroineTagId,
                out heroineBasis);
            if (!heroineKnown)
            {
                heroine = "結縁相手不明";
            }


            string titlePartnerName;
            Catalog.TryGetHeroine(partnerId, out titlePartnerName);

            var info = new FileInfo(path);
            DateTime exportedAt = TextFileOperations.GetExportedAt(info.Name, info.LastWriteTime);
            var exportEvent = new ExportEvent
            {
                EventId = eventId,
                Source = source,
                Slot = candidate.Slot,
                EndKey = candidate.EndKey,
                TitleId = title.TitleId,
                FilePrefix = title.FilePrefix,
                TitleName = title.JpName,
                TitleTag = title.TagLabel,
                PartnerId = partnerId,
                TitlePartnerName = titlePartnerName,
                Heroine = heroine,
                ExportedAt = new DateTimeOffset(exportedAt).ToString("o", CultureInfo.InvariantCulture),
                OriginalFileName = info.Name,
                CurrentFileName = info.Name,
                FullPath = Path.GetFullPath(path),
                ContentSha256 = document.ContentSha256,
                NormalizedSha256 = document.NormalizedSha256,
                FileSha256 = document.FileSha256,
                Hash8 = document.ContentSha256.Substring(0, 8),
                FileSize = document.FileSize,
                StoryKeys = candidate.StoryKeys,
                StoryKeySha256 = candidate.StoryKeySha256
            };
            exportEvent.ConfirmedTags.Add(new ConfirmedTag
            {
                Id = "ending." + title.TitleId.ToString(CultureInfo.InvariantCulture),
                Label = title.TagLabel,
                Category = "ending",
                Basis = basis,
                Confidence = confidence
            });
            if (heroineKnown)
            {
                exportEvent.ConfirmedTags.Add(new ConfirmedTag
                {
                    Id = heroineTagId,
                    Label = heroine,
                    Category = "heroine",
                    Basis = heroineBasis,
                    Confidence = "exact"
                });
            }
            else
            {
                exportEvent.Warnings.Add("結縁成立を確定できるStory keyがありません。");
            }

            AtomicWriteJson(Path.Combine(_inboxDirectory, eventFileName), exportEvent);
        }

        private static string BuildLegendBody(IEnumerable<string> storyKeys, ILocaleResolver resolver)
        {
            var builder = new StringBuilder();
            foreach (string storyKey in storyKeys)
            {
                string text = resolver.GetString("LegendInfo/" + storyKey);
                if (!string.IsNullOrEmpty(text))
                {
                    builder.AppendLine(text);
                }
            }
            return builder.ToString();
        }

        private void QueueExistingFiles()
        {
            foreach (string path in Directory.EnumerateFiles(_nativeLegendDirectory, "LOM_Legend_*.txt"))
            {
                QueueObservedFile(path);
            }
        }

        private void OnFileChanged(object sender, FileSystemEventArgs args)
        {
            QueueObservedFile(args.FullPath);
        }

        private void OnFileRenamed(object sender, RenamedEventArgs args)
        {
            if (Path.GetFileName(args.FullPath).StartsWith("LOM_Legend_", StringComparison.OrdinalIgnoreCase))
            {
                QueueObservedFile(args.FullPath);
            }
        }

        private void OnWatcherError(object sender, ErrorEventArgs args)
        {
            _logger.LogError("伝説フォルダの監視でエラーが発生しました。未処理ファイルを再走査します。");
            _logger.LogError(args.GetException());
            QueueExistingFiles();
        }

        private void QueueObservedFile(string path)
        {
            if (_disposed)
            {
                return;
            }

            long token = DateTime.UtcNow.Ticks;
            _pendingFiles[path] = token;
            Task.Run(async () =>
            {
                try
                {
                    await Task.Delay(_debounceMilliseconds, _cancellation.Token).ConfigureAwait(false);
                    if (_pendingFiles.TryGetValue(path, out long currentToken) && currentToken == token)
                    {
                        _pendingFiles.TryRemove(path, out currentToken);
                        ProcessObservedFile(path);
                    }
                }
                catch (OperationCanceledException)
                {
                }
                catch (Exception exception)
                {
                    _logger.LogError("監視対象ファイルの処理に失敗しました: " + path);
                    _logger.LogError(exception);
                }
            }, _cancellation.Token);
        }

        private void ProcessObservedFile(string path)
        {
            if (!WaitUntilStable(path))
            {
                return;
            }

            ProcessFile(path, null, "watcher");
        }

        private bool WaitUntilStable(string path)
        {
            long previousLength = -1;
            DateTime previousWrite = DateTime.MinValue;
            for (int attempt = 0; attempt < 10; attempt++)
            {
                if (!File.Exists(path))
                {
                    return false;
                }

                try
                {
                    var info = new FileInfo(path);
                    if (attempt > 0 && info.Length == previousLength && info.LastWriteTimeUtc == previousWrite)
                    {
                        using (FileStream stream = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.Read))
                        {
                            return stream.Length == info.Length;
                        }
                    }

                    previousLength = info.Length;
                    previousWrite = info.LastWriteTimeUtc;
                }
                catch (IOException)
                {
                }
                catch (UnauthorizedAccessException)
                {
                }

                Thread.Sleep(200);
            }

            _logger.LogWarning("ファイルが安定しないため処理を見送りました: " + path);
            return false;
        }

        private SlotMetadata ReadSlotMetadata(int slot)
        {
            string path = GetSlotMetadataPath(slot);
            if (!File.Exists(path))
            {
                return null;
            }

            try
            {
                return JsonConvert.DeserializeObject<SlotMetadata>(File.ReadAllText(path, Utf8WithoutBom));
            }
            catch (Exception exception)
            {
                _logger.LogWarning("スロットメタデータを読み込めませんでした: " + path);
                _logger.LogWarning(exception);
                return null;
            }
        }

        private void RememberExport(ExportContext context, string fullPath, string contentSha256)
        {
            try
            {
                SlotMetadata metadata = ReadSlotMetadata(context.Slot);
                if (metadata == null ||
                    metadata.EndKey != context.EndKey ||
                    metadata.TimeTick != context.TimeTick ||
                    metadata.StoryKeySha256 != context.StoryKeySha256)
                {
                    return;
                }

                metadata.LastExportFullPath = Path.GetFullPath(fullPath);
                metadata.LastExportContentSha256 = contentSha256;
                AtomicWriteJson(GetSlotMetadataPath(context.Slot), metadata);
            }
            catch (Exception exception)
            {
                _logger.LogWarning("同一スロットの重複防止情報を保存できませんでした。");
                _logger.LogWarning(exception);
            }
        }

        private string GetSlotMetadataPath(int slot)
        {
            return Path.Combine(_slotMetadataDirectory, "slot_" + slot.ToString("D3", CultureInfo.InvariantCulture) + ".json");
        }

        private static ParameterSnapshot CaptureParameters()
        {
            var snapshot = new ParameterSnapshot();
            PlayerStatManagerData manager = PlayerStatManagerData.Instance;
            ILocaleResolver resolver = LocalizationManager.Instance?.LocaleResolver;
            if (manager == null)
            {
                return snapshot;
            }

            foreach (int typeValue in AbilityStatTypes)
            {
                AddStat(snapshot.Abilities, manager, resolver, typeValue, null);
            }
            AddStat(snapshot.Personality, manager, resolver, 8, "性情");
            AddStat(snapshot.Personality, manager, resolver, 9, "処世");
            AddStat(snapshot.Personality, manager, resolver, 10, "品性", true);
            AddStat(snapshot.Personality, manager, resolver, 11, "道徳", true);
            AddStat(snapshot.Resources, manager, resolver, 3, "所持金");
            AddStat(snapshot.Faction, manager, resolver, 14, "名声");
            AddStat(snapshot.Faction, manager, resolver, 16, "団結");

            if (manager.Relationships?.List != null)
            {
                foreach (RelationshipStat relationship in manager.Relationships.List)
                {
                    if (relationship == null || !relationship.Active)
                    {
                        continue;
                    }

                    int typeValue = (int)relationship.Type;
                    string label = RelationshipNames.TryGetValue(typeValue, out string knownName)
                        ? knownName
                        : relationship.Type.ToString();
                    snapshot.Relationships.Add(new ParameterValue
                    {
                        Key = typeValue.ToString(CultureInfo.InvariantCulture),
                        Label = label,
                        Value = relationship.Value
                    });
                }
            }

            if (manager.Talents?.List != null)
            {
                foreach (PlayerTalentData skill in manager.Talents.List)
                {
                    if (skill == null || skill.Level <= 0)
                    {
                        continue;
                    }

                    snapshot.Skills.Add(new SkillParameterValue
                    {
                        Key = skill.Id,
                        Label = ResolveLabel(resolver, skill.GetIdKey(), skill.Id),
                        Level = skill.Level
                    });
                }
            }
            return snapshot;
        }

        private static void AddStat(
            List<ParameterValue> destination,
            PlayerStatManagerData manager,
            ILocaleResolver resolver,
            int typeValue,
            string fallback,
            bool includeLevelText = false)
        {
            GameStat stat = manager.Stats?.Get((GameStatType)typeValue);
            if (stat == null)
            {
                return;
            }
            var value = new ParameterValue
            {
                Key = typeValue.ToString(CultureInfo.InvariantCulture),
                Label = ResolveLabel(resolver, stat.GetLocaleKey(), fallback ?? stat.StatType.ToString()),
                Value = stat.FinalValue
            };
            if ((includeLevelText || typeValue == 8 || typeValue == 9) && stat.LevelLength > 0)
            {
                int level = GameStatUtils.GetGameStatLevel(stat.FinalValue, stat.Max, stat.LevelLength);
                value.DisplayValue = ResolveLabel(resolver, stat.GetLevelText(level), null);
            }
            destination.Add(value);
        }

        private static string ResolveLabel(ILocaleResolver resolver, string key, string fallback)
        {
            if (resolver == null || string.IsNullOrWhiteSpace(key))
            {
                return fallback;
            }
            string localized = resolver.GetString(key);
            return string.IsNullOrWhiteSpace(localized) || string.Equals(localized, key, StringComparison.Ordinal)
                ? fallback
                : localized;
        }

        private static List<string> GetStoryKeys(LegendSave legend)
        {
            if (legend?.Story == null)
            {
                return new List<string>();
            }

            return legend.Story
                .Where(story => story != null && !string.IsNullOrWhiteSpace(story.Key))
                .Select(story => story.Key)
                .ToList();
        }

        private static void AtomicWriteJson(string path, object value)
        {
            string directory = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(directory))
            {
                Directory.CreateDirectory(directory);
            }

            string temporaryPath = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            string json = JsonConvert.SerializeObject(value, Formatting.Indented);
            try
            {
                using (var stream = new FileStream(temporaryPath, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                using (var writer = new StreamWriter(stream, Utf8WithoutBom))
                {
                    writer.Write(json);
                    writer.Flush();
                    stream.Flush(true);
                }

                if (File.Exists(path))
                {
                    File.Replace(temporaryPath, path, null);
                }
                else
                {
                    File.Move(temporaryPath, path);
                }
            }
            finally
            {
                if (File.Exists(temporaryPath))
                {
                    File.Delete(temporaryPath);
                }
            }
        }

        public void Dispose()
        {
            if (_disposed)
            {
                return;
            }

            _disposed = true;
            _cancellation.Cancel();
            if (_watcher != null)
            {
                _watcher.EnableRaisingEvents = false;
                _watcher.Dispose();
                _watcher = null;
            }
            _cancellation.Dispose();
        }

        private sealed class ExistingSlotCandidate
        {
            public int Slot { get; set; }
            public string EndKey { get; set; }
            public long TimeTick { get; set; }
            public List<string> StoryKeys { get; set; }
            public string StoryKeySha256 { get; set; }
        }
    }
}
