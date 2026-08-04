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

namespace LegendManager.Plugin
{
    [BepInPlugin(PluginGuid, PluginName, PluginVersion)]
    public sealed class Plugin : BaseUnityPlugin
    {
        public const string PluginGuid = "lom.jp.legendmanager";
        public const string PluginName = "LOM Legend Manager";
        public const string PluginVersion = "0.2.0";

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

            ConfigEntry<bool> autoExportOnSave = Config.Bind(
                "Export",
                "AutoExportOnSave",
                true,
                "伝説の保存時にTXTを自動エクスポートします。");

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
                    autoExportOnSave.Value,
                    Math.Max(1, existingSlotScanLimit.Value),
                    Math.Max(250, debounceMilliseconds.Value));

                _harmony = new Harmony(PluginGuid);
                _harmony.PatchAll(typeof(Plugin).Assembly);
                Service.Start();
                if (Service.UsingLegendDirectoryFallback)
                {
                    _pendingFallbackNotification = true;
                }
                Logger.LogInfo("LOM Legend Manager 0.2.0 loaded.");
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

                Type panelType = AccessTools.TypeByName("Mortal.Core.GameMessagePanel");
                Type floatingType = AccessTools.TypeByName("Mortal.Core.FloatingText");
                if (panelType == null || floatingType == null)
                {
                    Logger.LogInfo(message);
                    return;
                }

                var existing = new System.Collections.Generic.HashSet<int>();
                foreach (UnityEngine.Object item in UnityEngine.Object.FindObjectsOfType(floatingType))
                {
                    existing.Add(item.GetInstanceID());
                }

                UnityEngine.Object panel = UnityEngine.Object.FindObjectOfType(panelType);
                var displayMethod = AccessTools.Method(panelType, "DisplayMessage", new[] { typeof(string) });
                if (panel == null || displayMethod == null)
                {
                    Logger.LogInfo(message);
                    return;
                }

                displayMethod.Invoke(panel, new object[] { message });
                foreach (UnityEngine.Object item in UnityEngine.Object.FindObjectsOfType(floatingType))
                {
                    if (!existing.Contains(item.GetInstanceID()) && item is Component component)
                    {
                        _autoExportToast = component.gameObject;
                        break;
                    }
                }
            }
            catch (Exception exception)
            {
                Logger.LogWarning("自動エクスポート通知を表示できませんでした。");
                Logger.LogWarning(exception);
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
