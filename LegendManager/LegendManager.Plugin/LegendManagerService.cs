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

        private readonly ManualLogSource _logger;
        private readonly Catalog _catalog;
        private readonly string _legendDirectory;
        private readonly string _managerDirectory;
        private readonly string _inboxDirectory;
        private readonly string _processedDirectory;
        private readonly string _slotMetadataDirectory;
        private readonly bool _renameFiles;
        private readonly bool _processExisting;
        private readonly bool _matchExistingFiles;
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

        public LegendManagerService(
            ManualLogSource logger,
            string presetPath,
            string tagCatalogPath,
            string persistentRoot,
            bool renameFiles,
            bool processExisting,
            bool matchExistingFiles,
            int existingSlotScanLimit,
            int debounceMilliseconds)
        {
            _logger = logger;
            _catalog = Catalog.Load(presetPath, tagCatalogPath);
            _legendDirectory = Path.Combine(persistentRoot, "Legend");
            _managerDirectory = Path.Combine(persistentRoot, "LegendManager");
            _inboxDirectory = Path.Combine(_managerDirectory, "inbox");
            _processedDirectory = Path.Combine(_managerDirectory, "processed");
            _slotMetadataDirectory = Path.Combine(_managerDirectory, "slots");
            _renameFiles = renameFiles;
            _processExisting = processExisting;
            _matchExistingFiles = matchExistingFiles;
            _existingSlotScanLimit = existingSlotScanLimit;
            _debounceMilliseconds = debounceMilliseconds;
        }

        public void Start()
        {
            Directory.CreateDirectory(_legendDirectory);
            Directory.CreateDirectory(_inboxDirectory);
            Directory.CreateDirectory(_processedDirectory);
            Directory.CreateDirectory(_slotMetadataDirectory);

            _watcher = new FileSystemWatcher(_legendDirectory, "LOM_Legend_*.txt")
            {
                IncludeSubdirectories = false,
                NotifyFilter = NotifyFilters.FileName | NotifyFilters.CreationTime | NotifyFilters.LastWrite | NotifyFilters.Size
            };
            _watcher.Created += OnFileChanged;
            _watcher.Changed += OnFileChanged;
            _watcher.Renamed += OnFileRenamed;
            _watcher.Error += OnWatcherError;
            _watcher.EnableRaisingEvents = true;

            _logger.LogInfo("Legend directory: " + _legendDirectory);
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

        public void CaptureSlotMetadata(SaveSystem saveSystem, int slot, string endKey)
        {
            LegendSave legend = saveSystem.GetLegendSaveData(slot);
            if (legend == null)
            {
                _logger.LogWarning("保存後の伝説データを取得できませんでした。slot=" + slot);
                return;
            }

            List<string> storyKeys = GetStoryKeys(legend);
            var metadata = new SlotMetadata
            {
                Slot = slot,
                EndKey = endKey,
                TitlePartner = saveSystem.TitlePartner,
                TimeTick = legend.TimeTick,
                StoryKeySha256 = TextFileOperations.ComputeStoryKeySha256(storyKeys),
                CapturedAt = DateTimeOffset.Now.ToString("o", CultureInfo.InvariantCulture)
            };

            string path = GetSlotMetadataPath(slot);
            AtomicWriteJson(path, metadata);
            _logger.LogInfo(
                "Legend slot metadata captured. slot=" + slot +
                ", endKey=" + endKey +
                ", partner=" + metadata.TitlePartner);
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

            List<string> storyKeys = GetStoryKeys(legend);
            string storyHash = TextFileOperations.ComputeStoryKeySha256(storyKeys);
            var context = new ExportContext
            {
                StartedAt = DateTime.Now,
                Slot = slot,
                EndKey = legend.EndKey,
                TimeTick = legend.TimeTick,
                StoryKeys = storyKeys,
                StoryKeySha256 = storyHash,
                ExistingFiles = new HashSet<string>(
                    Directory.EnumerateFiles(_legendDirectory, "LOM_Legend_*.txt").Select(Path.GetFullPath),
                    StringComparer.OrdinalIgnoreCase)
            };

            SlotMetadata metadata = ReadSlotMetadata(slot);
            if (metadata != null &&
                metadata.EndKey == context.EndKey &&
                metadata.TimeTick == context.TimeTick &&
                metadata.StoryKeySha256 == context.StoryKeySha256)
            {
                context.PartnerId = metadata.TitlePartner;
            }

            return context;
        }

        public void CompleteExport(ExportContext context)
        {
            List<string> newFiles = Directory
                .EnumerateFiles(_legendDirectory, "LOM_Legend_*.txt")
                .Select(Path.GetFullPath)
                .Where(path => !context.ExistingFiles.Contains(path))
                .ToList();

            if (newFiles.Count == 0)
            {
                string fallback = WriteFallbackExport(context);
                newFiles.Add(fallback);
                _logger.LogWarning("同一秒のファイル名衝突を検出し、別名でエクスポートしました。");
            }

            foreach (string path in newFiles)
            {
                ProcessFile(path, context, "bepinex");
            }
        }

        private string WriteFallbackExport(ExportContext context)
        {
            string stem = "LOM_Legend_" + DateTime.Now.ToString("yyyyMMddHHmmss", CultureInfo.InvariantCulture);
            string path = Path.Combine(_legendDirectory, stem + "_2.txt");
            int suffix = 2;
            while (File.Exists(path))
            {
                suffix++;
                path = Path.Combine(_legendDirectory, stem + "_" + suffix.ToString(CultureInfo.InvariantCulture) + ".txt");
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

        private void ProcessFile(string sourcePath, ExportContext context, string source)
        {
            if (!File.Exists(sourcePath))
            {
                return;
            }

            FileInfo sourceInfo = new FileInfo(sourcePath);
            string state = sourceInfo.Length.ToString(CultureInfo.InvariantCulture) + ":" +
                           sourceInfo.LastWriteTimeUtc.Ticks.ToString(CultureInfo.InvariantCulture);
            if (context == null && _processedFileStates.TryGetValue(sourcePath, out string previousState) && previousState == state)
            {
                return;
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
            if (_renameFiles && context != null)
            {
                string targetPath = TextFileOperations.BuildTargetPath(
                    sourcePath,
                    title?.FilePrefix,
                    titleName,
                    heroine,
                    exportedAt,
                    document.ContentSha256.Substring(0, 8));

                if (!string.Equals(sourcePath, targetPath, StringComparison.OrdinalIgnoreCase))
                {
                    File.Move(sourcePath, targetPath);
                    currentPath = targetPath;
                }
            }

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
                NormalizedSha256 = document.NormalizedSha256,
                FileSha256 = document.FileSha256,
                Hash8 = document.ContentSha256.Substring(0, 8),
                FileSize = document.FileSize,
                StoryKeys = context?.StoryKeys ?? new List<string>(),
                StoryKeySha256 = context?.StoryKeySha256
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

            string eventPath = Path.Combine(
                _inboxDirectory,
                DateTime.Now.ToString("yyyyMMddHHmmssfff", CultureInfo.InvariantCulture) + "_" + exportEvent.EventId + ".json");
            AtomicWriteJson(eventPath, exportEvent);

            _processedFileStates[currentPath] = state;
            _logger.LogInfo("Legend processed: " + exportEvent.CurrentFileName);
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
            foreach (string path in Directory.EnumerateFiles(_legendDirectory, "LOM_Legend_*.txt"))
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

        private string GetSlotMetadataPath(int slot)
        {
            return Path.Combine(_slotMetadataDirectory, "slot_" + slot.ToString("D3", CultureInfo.InvariantCulture) + ".json");
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
