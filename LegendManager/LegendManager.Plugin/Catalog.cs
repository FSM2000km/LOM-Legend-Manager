using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using Newtonsoft.Json.Linq;

namespace LegendManager.Plugin
{
    internal sealed class Catalog
    {
        private static readonly Dictionary<int, string> PartnerNames = new Dictionary<int, string>
        {
            { 0, "無結縁" },
            { 1, "小師妹" },
            { 2, "龍湘" },
            { 3, "葉雲裳" },
            { 4, "上官螢" },
            { 5, "夏侯蘭" },
            { 6, "虞小梅" },
            { 7, "魏菊" },
            { 8, "郁竹" },
            { 20, "無結縁" }
        };

        private static readonly Dictionary<string, string> HeroineTagIds = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { "無結縁", "heroine.none" },
            { "小師妹", "heroine.1" },
            { "龍湘", "heroine.2" },
            { "葉雲裳", "heroine.3" },
            { "上官螢", "heroine.4" },
            { "夏侯蘭", "heroine.5" },
            { "虞小梅", "heroine.6" },
            { "魏菊", "heroine.7" },
            { "郁竹", "heroine.8" },
            { "唐嬌嬌", "heroine.tang_jiaojiao" }
        };

        private readonly Dictionary<int, TitleInfo> _endings;
        private readonly Dictionary<string, KeyValuePair<string, string>> _unionsByStoryKey;

        private Catalog(
            Dictionary<int, TitleInfo> endings,
            Dictionary<string, KeyValuePair<string, string>> unionsByStoryKey)
        {
            _endings = endings;
            _unionsByStoryKey = unionsByStoryKey;
        }

        public static Catalog Load(string path, string tagCatalogPath)
        {
            if (!File.Exists(path))
            {
                throw new FileNotFoundException("JP v2.4プリセットが見つかりません。", path);
            }

            JObject root = JObject.Parse(File.ReadAllText(path));
            JArray endings = (JArray)root["titles"]?["endings"];
            if (endings == null || endings.Count == 0)
            {
                throw new InvalidDataException("JP v2.4プリセットにEDタイトルがありません。");
            }

            var result = new Dictionary<int, TitleInfo>();
            foreach (JToken token in endings)
            {
                int titleId = token.Value<int>("titleId");
                result[titleId] = new TitleInfo
                {
                    TitleId = titleId,
                    FilePrefix = token.Value<string>("filePrefix"),
                    JpName = token.Value<string>("jpName"),
                    Heroine = token.Value<string>("heroine")
                };
            }

            if (!File.Exists(tagCatalogPath))
            {
                throw new FileNotFoundException("タグカタログが見つかりません。", tagCatalogPath);
            }

            JObject tagRoot = JObject.Parse(File.ReadAllText(tagCatalogPath));
            JArray tags = (JArray)tagRoot["tags"];
            if (tags == null)
            {
                throw new InvalidDataException("タグカタログにタグ一覧がありません。");
            }

            var unionsByStoryKey = new Dictionary<string, KeyValuePair<string, string>>(StringComparer.Ordinal);
            foreach (JToken token in tags)
            {
                string label = token.Value<string>("label");
                if (string.IsNullOrEmpty(label) || !label.EndsWith("結縁", StringComparison.Ordinal))
                {
                    continue;
                }

                string heroine = label.Substring(0, label.Length - "結縁".Length);
                if (!TryGetHeroineTagId(heroine, out string heroineTagId))
                {
                    continue;
                }

                foreach (JToken keyToken in token["story_keys_any"] ?? new JArray())
                {
                    string storyKey = keyToken.Value<string>();
                    if (storyKey != null && storyKey.StartsWith("LegendInfo/", StringComparison.Ordinal))
                    {
                        storyKey = storyKey.Substring("LegendInfo/".Length);
                    }
                    if (string.IsNullOrWhiteSpace(storyKey))
                    {
                        continue;
                    }

                    var candidate = new KeyValuePair<string, string>(heroine, heroineTagId);
                    if (unionsByStoryKey.TryGetValue(storyKey, out KeyValuePair<string, string> existing) &&
                        !string.Equals(existing.Key, heroine, StringComparison.Ordinal))
                    {
                        throw new InvalidDataException("同じStory keyに複数の結縁相手が設定されています: " + storyKey);
                    }
                    unionsByStoryKey[storyKey] = candidate;
                }
            }

            return new Catalog(result, unionsByStoryKey);
        }

        public bool TryGetEnding(string endKey, out TitleInfo title)
        {
            title = null;
            if (!int.TryParse(endKey, NumberStyles.Integer, CultureInfo.InvariantCulture, out int titleId))
            {
                return false;
            }

            return _endings.TryGetValue(titleId, out title);
        }

        public static bool TryGetHeroine(int? partnerId, out string heroine)
        {
            heroine = null;
            return partnerId.HasValue && PartnerNames.TryGetValue(partnerId.Value, out heroine);
        }

        public static bool TryGetHeroineTagId(string heroine, out string tagId)
        {
            tagId = null;
            return !string.IsNullOrWhiteSpace(heroine) && HeroineTagIds.TryGetValue(heroine, out tagId);
        }

        public bool TryResolveUnion(
            IEnumerable<string> storyKeys,
            TitleInfo title,
            out string heroine,
            out string tagId,
            out string basis)
        {
            heroine = null;
            tagId = null;
            basis = null;

            foreach (string rawKey in storyKeys ?? new string[0])
            {
                string storyKey = rawKey != null && rawKey.StartsWith("LegendInfo/", StringComparison.Ordinal)
                    ? rawKey.Substring("LegendInfo/".Length)
                    : rawKey;
                if (!_unionsByStoryKey.TryGetValue(storyKey ?? string.Empty, out KeyValuePair<string, string> candidate))
                {
                    continue;
                }

                if (heroine != null && !string.Equals(heroine, candidate.Key, StringComparison.Ordinal))
                {
                    heroine = null;
                    tagId = null;
                    basis = null;
                    return false;
                }

                heroine = candidate.Key;
                tagId = candidate.Value;
                basis = "story_rule";
            }

            if (heroine != null)
            {
                return true;
            }

            if (title != null && string.Equals(title.Heroine, "無結縁", StringComparison.Ordinal))
            {
                heroine = "無結縁";
                tagId = "heroine.none";
                basis = "ending_preset";
                return true;
            }

            return false;
        }
    }
}
