using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace LegendManager.Plugin
{
    internal enum AutoExportTiming
    {
        LegendSaved,
        EndingDisplayed,
        Disabled
    }

    internal sealed class TitleInfo
    {
        public int TitleId { get; set; }
        public string FilePrefix { get; set; }
        public string JpName { get; set; }
        public string Heroine { get; set; }

        [JsonIgnore]
        public string TagLabel => FilePrefix + " " + JpName;
    }

    internal sealed class SlotMetadata
    {
        [JsonProperty("schema_version")]
        public int SchemaVersion { get; set; } = 1;

        [JsonProperty("slot")]
        public int Slot { get; set; }

        [JsonProperty("end_key")]
        public string EndKey { get; set; }

        [JsonProperty("title_partner")]
        public int TitlePartner { get; set; }

        [JsonProperty("time_tick")]
        public long TimeTick { get; set; }

        [JsonProperty("story_key_sha256")]
        public string StoryKeySha256 { get; set; }

        [JsonProperty("captured_at")]
        public string CapturedAt { get; set; }

        [JsonProperty("parameters")]
        public ParameterSnapshot Parameters { get; set; }

        [JsonProperty("last_export_full_path")]
        public string LastExportFullPath { get; set; }

        [JsonProperty("last_export_content_sha256")]
        public string LastExportContentSha256 { get; set; }
    }

    internal sealed class ConfirmedTag
    {
        [JsonProperty("id")]
        public string Id { get; set; }

        [JsonProperty("label")]
        public string Label { get; set; }

        [JsonProperty("category")]
        public string Category { get; set; }

        [JsonProperty("basis")]
        public string Basis { get; set; }

        [JsonProperty("confidence")]
        public string Confidence { get; set; }
    }

    internal sealed class ExportEvent
    {
        [JsonProperty("schema_version")]
        public int SchemaVersion { get; set; } = 1;

        [JsonProperty("event_id")]
        public string EventId { get; set; }

        [JsonProperty("event_type")]
        public string EventType { get; set; } = "legend_exported";

        [JsonProperty("source")]
        public string Source { get; set; }

        [JsonProperty("slot")]
        public int? Slot { get; set; }

        [JsonProperty("end_key")]
        public string EndKey { get; set; }

        [JsonProperty("title_id")]
        public int? TitleId { get; set; }

        [JsonProperty("file_prefix")]
        public string FilePrefix { get; set; }

        [JsonProperty("title_name")]
        public string TitleName { get; set; }

        [JsonProperty("title_tag")]
        public string TitleTag { get; set; }

        [JsonProperty("partner_id")]
        public int? PartnerId { get; set; }

        [JsonProperty("title_partner_name")]
        public string TitlePartnerName { get; set; }

        [JsonProperty("heroine")]
        public string Heroine { get; set; }

        [JsonProperty("exported_at")]
        public string ExportedAt { get; set; }

        [JsonProperty("original_file_name")]
        public string OriginalFileName { get; set; }

        [JsonProperty("current_file_name")]
        public string CurrentFileName { get; set; }

        [JsonProperty("full_path")]
        public string FullPath { get; set; }

        [JsonProperty("content_sha256")]
        public string ContentSha256 { get; set; }

        [JsonProperty("normalized_sha256")]
        public string NormalizedSha256 { get; set; }

        [JsonProperty("file_sha256")]
        public string FileSha256 { get; set; }

        [JsonProperty("hash8")]
        public string Hash8 { get; set; }

        [JsonProperty("file_size")]
        public long FileSize { get; set; }

        [JsonProperty("story_keys")]
        public List<string> StoryKeys { get; set; } = new List<string>();

        [JsonProperty("story_key_sha256")]
        public string StoryKeySha256 { get; set; }

        [JsonProperty("confirmed_tags")]
        public List<ConfirmedTag> ConfirmedTags { get; set; } = new List<ConfirmedTag>();

        [JsonProperty("warnings")]
        public List<string> Warnings { get; set; } = new List<string>();

        [JsonProperty("parameters")]
        public ParameterSnapshot Parameters { get; set; }
    }

    internal sealed class ExportContext
    {
        public DateTime StartedAt { get; set; }
        public int? Slot { get; set; }
        public string EndKey { get; set; }
        public long TimeTick { get; set; }
        public List<string> StoryKeys { get; set; } = new List<string>();
        public string StoryKeySha256 { get; set; }
        public int? PartnerId { get; set; }
        public ParameterSnapshot Parameters { get; set; }
        public string ExistingExportPath { get; set; }
        public string ExistingExportContentSha256 { get; set; }
        public HashSet<string> ExistingFiles { get; set; } = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    }

    internal sealed class ParameterSnapshot
    {
        [JsonProperty("abilities")]
        public List<ParameterValue> Abilities { get; set; } = new List<ParameterValue>();

        [JsonProperty("personality")]
        public List<ParameterValue> Personality { get; set; } = new List<ParameterValue>();

        [JsonProperty("resources")]
        public List<ParameterValue> Resources { get; set; } = new List<ParameterValue>();

        [JsonProperty("faction")]
        public List<ParameterValue> Faction { get; set; } = new List<ParameterValue>();

        [JsonProperty("relationships")]
        public List<ParameterValue> Relationships { get; set; } = new List<ParameterValue>();

        [JsonProperty("skills")]
        public List<SkillParameterValue> Skills { get; set; } = new List<SkillParameterValue>();
    }

    internal sealed class ParameterValue
    {
        [JsonProperty("key")]
        public string Key { get; set; }

        [JsonProperty("label")]
        public string Label { get; set; }

        [JsonProperty("value")]
        public int Value { get; set; }

        [JsonProperty("display_value", NullValueHandling = NullValueHandling.Ignore)]
        public string DisplayValue { get; set; }
    }

    internal sealed class SkillParameterValue
    {
        [JsonProperty("key")]
        public string Key { get; set; }

        [JsonProperty("label")]
        public string Label { get; set; }

        [JsonProperty("level")]
        public int Level { get; set; }
    }

    internal sealed class ExportResult
    {
        public string FullPath { get; set; }
        public bool ReusedExisting { get; set; }
    }

    internal sealed class SharedPathSettings
    {
        [JsonProperty("schema_version")]
        public int SchemaVersion { get; set; }

        [JsonProperty("game_root")]
        public string GameRoot { get; set; }

        [JsonProperty("legend_directory")]
        public string LegendDirectory { get; set; }
    }

    internal sealed class PictureIndex
    {
        [JsonProperty("schema_version")]
        public int SchemaVersion { get; set; } = 1;

        [JsonProperty("endings")]
        public Dictionary<string, PictureIndexEntry> Endings { get; set; } =
            new Dictionary<string, PictureIndexEntry>();
    }

    internal sealed class PictureIndexEntry
    {
        [JsonProperty("file")]
        public string File { get; set; }

        [JsonProperty("sha256")]
        public string Sha256 { get; set; }

        [JsonProperty("updated_at")]
        public string UpdatedAt { get; set; }
    }
}
