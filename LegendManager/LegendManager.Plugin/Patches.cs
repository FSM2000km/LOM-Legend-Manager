using System;
using HarmonyLib;
using Mortal.Core;

namespace LegendManager.Plugin
{
    [HarmonyPatch(typeof(SaveSystem), nameof(SaveSystem.SaveLegendData))]
    internal static class SaveLegendDataPatch
    {
        private static void Postfix(SaveSystem __instance, int slot, string endKey)
        {
            try
            {
                Plugin.Service?.CaptureSlotMetadata(__instance, slot, endKey);
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

        private static void Postfix(ExportContext __state)
        {
            if (__state == null)
            {
                return;
            }

            try
            {
                Plugin.Service?.CompleteExport(__state);
            }
            catch (Exception exception)
            {
                Plugin.Log?.LogError("伝説エクスポート後処理に失敗しました。");
                Plugin.Log?.LogError(exception);
            }
        }
    }
}
