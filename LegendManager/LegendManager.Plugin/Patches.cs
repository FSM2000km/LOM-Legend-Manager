using System;
using HarmonyLib;
using Mortal.Core;

namespace LegendManager.Plugin
{
    [HarmonyPatch(typeof(EndGamePanel), nameof(EndGamePanel.Open))]
    internal static class EndGamePanelOpenPatch
    {
        private static void Prefix(string key)
        {
            Plugin.Instance?.QueueEndingDisplayedExport(key);
        }
    }

    [HarmonyPatch(typeof(SaveSystem), nameof(SaveSystem.SaveLegendData))]
    internal static class SaveLegendDataPatch
    {
        private static void Postfix(SaveSystem __instance, int slot, string endKey)
        {
            try
            {
                ExportResult result = Plugin.Service?.HandleLegendSaved(__instance, slot, endKey);
                if (result != null && Plugin.ShowAutoExportFileName)
                {
                    Plugin.ShowAutoExportNotification("伝説を自動エクスポートしました: " + System.IO.Path.GetFileName(result.FullPath));
                }
            }
            catch (Exception exception)
            {
                Plugin.Log?.LogError("伝説スロットのメタデータ保存に失敗しました。");
                Plugin.Log?.LogError(exception);
            }
        }
    }

    [HarmonyPatch(typeof(LibraryPanel), nameof(LibraryPanel.OnLegendPanelOpen))]
    internal static class LegendPanelOpenPatch
    {
        private static void Postfix()
        {
            try
            {
                Plugin.Service?.TryMatchExistingFilesToSlots();
            }
            catch (Exception exception)
            {
                Plugin.Log?.LogError("既存伝説のスロット照合に失敗しました。");
                Plugin.Log?.LogError(exception);
            }
        }
    }

    [HarmonyPatch(typeof(LibraryPanel), nameof(LibraryPanel.OnLegendSlotClickHandler))]
    internal static class LegendSlotClickPatch
    {
        private static void Postfix(LibraryPanel __instance, int slot)
        {
            Plugin.Instance?.CaptureDisplayedEndingPicture(__instance, slot);
        }
    }

    [HarmonyPatch(typeof(LibraryPanel), nameof(LibraryPanel.PrintLegendStory))]
    internal static class PrintLegendStoryPatch
    {
        private static void Prefix(LibraryPanel __instance, out ExportContext __state)
        {
            __state = null;
            try
            {
                __state = Plugin.Service?.BeginExport(__instance);
            }
            catch (Exception exception)
            {
                Plugin.Log?.LogError("伝説エクスポート前情報の取得に失敗しました。");
                Plugin.Log?.LogError(exception);
            }
        }

        private static void Postfix(LibraryPanel __instance, ExportContext __state)
        {
            if (__state == null)
            {
                return;
            }

            try
            {
                ExportResult result = Plugin.Service?.CompleteExport(__state);
                UpdateExportPanel(__instance, result);
            }
            catch (Exception exception)
            {
                Plugin.Log?.LogError("伝説エクスポート後処理に失敗しました。");
                Plugin.Log?.LogError(exception);
            }
        }

        private static void UpdateExportPanel(LibraryPanel panel, ExportResult result)
        {
            var panelField = AccessTools.Field(typeof(LibraryPanel), "_exportPanel");
            var textField = AccessTools.Field(typeof(LibraryPanel), "_exportText");
            var exportPanel = panelField?.GetValue(panel) as UnityEngine.GameObject;

            if (!Plugin.ShowManualExportFileName)
            {
                exportPanel?.SetActive(false);
                return;
            }
            if (result == null)
            {
                return;
            }

            object exportText = textField?.GetValue(panel);
            var textProperty = exportText == null ? null : AccessTools.Property(exportText.GetType(), "text");
            if (textProperty != null)
            {
                string fileName = System.IO.Path.GetFileName(result.FullPath);
                string template = LocalizationManager.Instance?.LocaleResolver?.GetString("System/ExportSuccess");
                string message;
                try
                {
                    message = string.IsNullOrWhiteSpace(template)
                        ? "エクスポートしました: " + fileName
                        : string.Format(template, fileName);
                }
                catch (FormatException)
                {
                    message = "エクスポートしました: " + fileName;
                }
                textProperty.SetValue(exportText, message, null);
            }
            exportPanel?.SetActive(true);
        }
    }
}
