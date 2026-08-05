using System;
using System.Collections;
using System.IO;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using BepInEx.Unity.Mono;
using HarmonyLib;
using Mortal.Core;
using UnityEngine;
using UnityEngine.UI;

namespace LegendManager.Plugin
{
    [BepInPlugin(PluginGuid, PluginName, PluginVersion)]
    public sealed class Plugin : BaseUnityPlugin
    {
        public const string PluginGuid = "lom.jp.legendmanager";
        public const string PluginName = "LOM Legend Manager";
        public const string PluginVersion = "0.3.0";

        private Harmony _harmony;
        private GameObject _autoExportToast;
        private bool _toastDismissArmed;
        private bool _pendingFallbackNotification;

        internal static LegendManagerService Service { get; private set; }
        internal static ManualLogSource Log { get; private set; }
        internal static Plugin Instance { get; private set; }
        internal static bool ShowManualExportFileName { get; private set; }
        internal static bool ShowAutoExportFileName { get; private set; }

        private void Awake()
        {
            Log = Logger;
            Instance = this;

            ConfigEntry<bool> enabled = Config.Bind(
                "General",
                "Enabled",
                true,
                "伝説エクスポートの監視と管理を有効にします。");

            ConfigEntry<bool> renameFiles = Config.Bind(
                "General",
                "RenameFiles",
                true,
                "新しくエクスポートされた伝説TXTをED名と結縁相手でリネームします。");

            ConfigEntry<bool> processExisting = Config.Bind(
                "General",
                "ProcessExistingFiles",
                false,
                "起動時に未処理のLOM_Legend_*.txtを登録します。既存ファイルは自動リネームしません。");

            ConfigEntry<bool> matchExistingFiles = Config.Bind(
                "General",
                "MatchExistingFiles",
                true,
                "既存TXTの本文を伝説スロットと照合し、一致したEDを確定します。既存ファイルはリネームしません。");

            ConfigEntry<int> existingSlotScanLimit = Config.Bind(
                "General",
                "ExistingSlotScanLimit",
                200,
                "既存TXTとの照合対象として確認する伝説スロット番号の上限です。");

            ConfigEntry<int> debounceMilliseconds = Config.Bind(
                "General",
                "DebounceMilliseconds",
                750,
                "ファイル監視イベント後に書き込み完了を待つ時間です。");

            AutoExportTiming defaultAutoExportTiming = ResolveDefaultAutoExportTiming(Config.ConfigFilePath);
            ConfigEntry<AutoExportTiming> autoExportTiming = Config.Bind(
                "Export",
                "AutoExportTiming",
                defaultAutoExportTiming,
                "自動エクスポートの時機です。LegendSaved=書庫への保存時、EndingDisplayed=ED画面表示時、Disabled=無効です。");

            ConfigEntry<bool> showManualExportFileName = Config.Bind(
                "Export",
                "ShowManualExportFileName",
                true,
                "手動エクスポート時に最終的なファイル名を表示します。");

            ConfigEntry<bool> showAutoExportFileName = Config.Bind(
                "Export",
                "ShowAutoExportFileName",
                true,
                "自動エクスポート時に最終的なファイル名を一時表示します。");

            ShowManualExportFileName = showManualExportFileName.Value;
            ShowAutoExportFileName = showAutoExportFileName.Value;

            if (!enabled.Value)
            {
                Logger.LogInfo("Legend Manager is disabled by configuration.");
                return;
            }

            string pluginDirectory = Path.GetDirectoryName(Info.Location) ?? Paths.PluginPath;
            string presetPath = Path.Combine(pluginDirectory, "data", "jp_v2_4_presets.json");
            string tagCatalogPath = Path.Combine(pluginDirectory, "data", "tags_catalog.json");
            string persistentRoot = UnityEngine.Application.persistentDataPath;

            try
            {
                Service = new LegendManagerService(
                    Logger,
                    presetPath,
                    tagCatalogPath,
                    persistentRoot,
                    renameFiles.Value,
                    processExisting.Value,
                    matchExistingFiles.Value,
                    autoExportTiming.Value,
                    Math.Max(1, existingSlotScanLimit.Value),
                    Math.Max(250, debounceMilliseconds.Value));

                _harmony = new Harmony(PluginGuid);
                _harmony.PatchAll(typeof(Plugin).Assembly);
                Service.Start();
                if (Service.UsingLegendDirectoryFallback)
                {
                    _pendingFallbackNotification = true;
                }
                Logger.LogInfo("LOM Legend Manager " + PluginVersion + " loaded. AutoExportTiming=" + autoExportTiming.Value);
            }
            catch (Exception exception)
            {
                Logger.LogError("Legend Managerの初期化に失敗しました。");
                Logger.LogError(exception);
                Service?.Dispose();
                Service = null;
                _harmony?.UnpatchSelf();
                _harmony = null;
            }
        }

        private IEnumerator Start()
        {
            for (int attempt = 0; attempt < 30; attempt++)
            {
                yield return new UnityEngine.WaitForSeconds(2f);
                if (_pendingFallbackNotification)
                {
                    _pendingFallbackNotification = false;
                    ShowAutoExportNotification("指定保存先を使用できないため標準のLegendフォルダへ保存します。");
                }
                if (Service == null || Service.TryMatchExistingFilesToSlots())
                {
                    yield break;
                }
            }

            Logger.LogWarning("既存伝説のスロット照合を開始できませんでした。伝説画面を開いたときに再試行します。");
        }

        private void Update()
        {
            if (_autoExportToast == null)
            {
                return;
            }
            if (!_toastDismissArmed)
            {
                if (!Input.GetMouseButton(0) && !Input.GetMouseButton(1) && !Input.GetMouseButton(2) && Input.touchCount == 0)
                {
                    _toastDismissArmed = true;
                }
                return;
            }
            if (Input.GetMouseButtonDown(0) || Input.GetMouseButtonDown(1) || Input.GetMouseButtonDown(2) || Input.touchCount > 0)
            {
                Destroy(_autoExportToast);
                _autoExportToast = null;
            }
        }

        internal static void ShowAutoExportNotification(string message)
        {
            Instance?.ShowGameMessage(message);
        }

        private static AutoExportTiming ResolveDefaultAutoExportTiming(string configPath)
        {
            try
            {
                if (!File.Exists(configPath))
                {
                    return AutoExportTiming.EndingDisplayed;
                }
                string section = string.Empty;
                foreach (string rawLine in File.ReadAllLines(configPath))
                {
                    string line = rawLine.Trim();
                    if (line.StartsWith("[") && line.EndsWith("]"))
                    {
                        section = line.Substring(1, line.Length - 2);
                        continue;
                    }
                    if (!string.Equals(section, "Export", StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }
                    int separator = line.IndexOf('=');
                    if (separator < 0)
                    {
                        continue;
                    }
                    string key = line.Substring(0, separator).Trim();
                    string value = line.Substring(separator + 1).Trim();
                    if (string.Equals(key, "AutoExportOnSave", StringComparison.OrdinalIgnoreCase) &&
                        string.Equals(value, "false", StringComparison.OrdinalIgnoreCase))
                    {
                        return AutoExportTiming.Disabled;
                    }
                }
            }
            catch
            {
                // BepInEx will still validate the newly bound setting.
            }
            return AutoExportTiming.EndingDisplayed;
        }

        internal void QueueEndingDisplayedExport(string endKey)
        {
            StartCoroutine(ExportDisplayedEndingAtEndOfFrame(endKey));
        }

        private IEnumerator ExportDisplayedEndingAtEndOfFrame(string endKey)
        {
            yield return new WaitForEndOfFrame();
            try
            {
                ExportResult result = Service?.HandleEndingDisplayed(SaveSystem.Instance, endKey);
                if (result != null && ShowAutoExportFileName)
                {
                    ShowGameMessage("伝説を自動エクスポートしました: " + Path.GetFileName(result.FullPath));
                }
            }
            catch (Exception exception)
            {
                Logger.LogError("ED表示時の自動エクスポートに失敗しました。");
                Logger.LogError(exception);
            }
        }

        private void ShowGameMessage(string message)
        {
            try
            {
                if (_autoExportToast != null)
                {
                    Destroy(_autoExportToast);
                    _autoExportToast = null;
                }
                _toastDismissArmed = false;

                _autoExportToast = new GameObject(
                    "LOM_AutoExportToast",
                    typeof(RectTransform),
                    typeof(Canvas),
                    typeof(CanvasScaler),
                    typeof(GraphicRaycaster));
                Canvas canvas = _autoExportToast.GetComponent<Canvas>();
                canvas.renderMode = RenderMode.ScreenSpaceOverlay;
                canvas.sortingOrder = short.MaxValue;

                CanvasScaler scaler = _autoExportToast.GetComponent<CanvasScaler>();
                scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
                scaler.referenceResolution = new Vector2(1920f, 1080f);
                scaler.matchWidthOrHeight = 1f;

                var background = new GameObject("Background", typeof(RectTransform), typeof(Image));
                background.transform.SetParent(_autoExportToast.transform, false);
                RectTransform backgroundRect = background.GetComponent<RectTransform>();
                backgroundRect.anchorMin = new Vector2(0.5f, 1f);
                backgroundRect.anchorMax = new Vector2(0.5f, 1f);
                backgroundRect.pivot = new Vector2(0.5f, 1f);
                backgroundRect.anchoredPosition = new Vector2(0f, -42f);
                backgroundRect.sizeDelta = new Vector2(1060f, 86f);
                background.GetComponent<Image>().color = new Color(0.08f, 0.12f, 0.09f, 0.94f);

                Text sample = UnityEngine.Object.FindObjectOfType<Text>();
                var labelObject = new GameObject("Message", typeof(RectTransform), typeof(Text));
                labelObject.transform.SetParent(background.transform, false);
                RectTransform labelRect = labelObject.GetComponent<RectTransform>();
                labelRect.anchorMin = Vector2.zero;
                labelRect.anchorMax = Vector2.one;
                labelRect.offsetMin = new Vector2(24f, 8f);
                labelRect.offsetMax = new Vector2(-24f, -8f);

                Text label = labelObject.GetComponent<Text>();
                label.font = sample != null && sample.font != null
                    ? sample.font
                    : Resources.GetBuiltinResource<Font>("Arial.ttf");
                label.fontSize = 25;
                label.resizeTextForBestFit = true;
                label.resizeTextMinSize = 16;
                label.resizeTextMaxSize = 25;
                label.alignment = TextAnchor.MiddleCenter;
                label.color = Color.white;
                label.text = message;

                StartCoroutine(DestroyToastAfterDelay(_autoExportToast, 6f));
                Logger.LogInfo(message);
            }
            catch (Exception exception)
            {
                Logger.LogWarning("自動エクスポート通知を表示できませんでした。");
                Logger.LogWarning(exception);
            }
        }

        private IEnumerator DestroyToastAfterDelay(GameObject toast, float delay)
        {
            yield return new WaitForSecondsRealtime(delay);
            if (toast != null)
            {
                Destroy(toast);
            }
            if (_autoExportToast == toast)
            {
                _autoExportToast = null;
            }
        }

        internal void CaptureDisplayedEndingPicture(LibraryPanel panel, int slot)
        {
            StartCoroutine(CaptureDisplayedEndingPictureAtEndOfFrame(panel, slot));
        }

        private IEnumerator CaptureDisplayedEndingPictureAtEndOfFrame(LibraryPanel panel, int slot)
        {
            yield return new WaitForEndOfFrame();
            Texture2D output = null;
            try
            {
                var pictureField = AccessTools.Field(typeof(LibraryPanel), "_legendDetailPicture");
                var picture = pictureField?.GetValue(panel) as UnityEngine.UI.Image;
                RectTransform rectTransform = picture?.rectTransform;
                if (rectTransform == null || !rectTransform.gameObject.activeInHierarchy)
                {
                    yield break;
                }

                var corners = new Vector3[4];
                rectTransform.GetWorldCorners(corners);
                Canvas canvas = picture.canvas;
                Camera camera = canvas != null && canvas.renderMode != RenderMode.ScreenSpaceOverlay
                    ? canvas.worldCamera
                    : null;
                Vector2 bottomLeft = RectTransformUtility.WorldToScreenPoint(camera, corners[0]);
                Vector2 topRight = RectTransformUtility.WorldToScreenPoint(camera, corners[2]);
                int left = Mathf.Clamp(Mathf.FloorToInt(bottomLeft.x), 0, Screen.width - 1);
                int bottom = Mathf.Clamp(Mathf.FloorToInt(bottomLeft.y), 0, Screen.height - 1);
                int right = Mathf.Clamp(Mathf.CeilToInt(topRight.x), left + 1, Screen.width);
                int top = Mathf.Clamp(Mathf.CeilToInt(topRight.y), bottom + 1, Screen.height);
                int width = right - left;
                int height = top - bottom;
                if (width < 32 || height < 32)
                {
                    yield break;
                }

                output = new Texture2D(width, height, TextureFormat.RGBA32, false);
                output.ReadPixels(new Rect(left, bottom, width, height), 0, 0);
                output.Apply(false, false);
                Service?.SaveDisplayedEndingPicture(slot, output.EncodeToPNG());
            }
            catch (Exception exception)
            {
                Logger.LogWarning("表示中のED画像を回収できませんでした。");
                Logger.LogWarning(exception);
            }
            finally
            {
                if (output != null)
                {
                    Destroy(output);
                }
            }
        }

        private void OnDestroy()
        {
            Service?.Dispose();
            Service = null;
            _harmony?.UnpatchSelf();
            _harmony = null;
            Instance = null;
        }
    }
}
