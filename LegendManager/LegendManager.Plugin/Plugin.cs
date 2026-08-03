using System;
using System.Collections;
using System.IO;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using BepInEx.Unity.Mono;
using HarmonyLib;

namespace LegendManager.Plugin
{
    [BepInPlugin(PluginGuid, PluginName, PluginVersion)]
    public sealed class Plugin : BaseUnityPlugin
    {
        public const string PluginGuid = "lom.jp.legendmanager";
        public const string PluginName = "LOM Legend Manager";
        public const string PluginVersion = "0.1.4";

        private Harmony _harmony;

        internal static LegendManagerService Service { get; private set; }
        internal static ManualLogSource Log { get; private set; }

        private void Awake()
        {
            Log = Logger;

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
                    Math.Max(1, existingSlotScanLimit.Value),
                    Math.Max(250, debounceMilliseconds.Value));

                _harmony = new Harmony(PluginGuid);
                _harmony.PatchAll(typeof(Plugin).Assembly);
                Service.Start();
                Logger.LogInfo("LOM Legend Manager 0.1.4 loaded.");
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
                if (Service == null || Service.TryMatchExistingFilesToSlots())
                {
                    yield break;
                }
            }

            Logger.LogWarning("既存伝説のスロット照合を開始できませんでした。伝説画面を開いたときに再試行します。");
        }

        private void OnDestroy()
        {
            Service?.Dispose();
            Service = null;
            _harmony?.UnpatchSelf();
            _harmony = null;
        }
    }
}
