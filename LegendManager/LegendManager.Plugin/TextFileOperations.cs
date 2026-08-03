using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace LegendManager.Plugin
{
    internal sealed class TextDocumentInfo
    {
        public string Text { get; set; }
        public string BodyText { get; set; }
        public bool HasUtf8Bom { get; set; }
        public string NewLine { get; set; }
        public string ContentSha256 { get; set; }
        public string NormalizedSha256 { get; set; }
        public string FileSha256 { get; set; }
        public long FileSize { get; set; }
    }

    internal static class TextFileOperations
    {
        internal const string ManagedTagStart = "【確定済みタグ】";
        internal const string ManagedTagEnd = "【確定済みタグここまで】";

        private static readonly UTF8Encoding StrictUtf8 = new UTF8Encoding(false, true);
        private static readonly UTF8Encoding Utf8WithoutBom = new UTF8Encoding(false);
        private static readonly Regex ManagedBlockPattern = new Regex(
            @"\A【確定済みタグ】\r?\n[\s\S]*?\r?\n【確定済みタグここまで】(?:\r?\n){1,2}",
            RegexOptions.Compiled | RegexOptions.CultureInvariant);
        private static readonly Regex RubyPattern = new Regex(
            @"[（(][ぁ-ゖァ-ヺー・]+[）)]",
            RegexOptions.Compiled | RegexOptions.CultureInvariant);
        private static readonly Regex WhitespacePattern = new Regex(
            @"\s+",
            RegexOptions.Compiled | RegexOptions.CultureInvariant);
        private static readonly Regex ExportTimestampPattern = new Regex(
            @"LOM_Legend_(?<timestamp>\d{14})",
            RegexOptions.Compiled | RegexOptions.CultureInvariant | RegexOptions.IgnoreCase);
        private static readonly HashSet<string> ReservedNames = new HashSet<string>(
            new[]
            {
                "CON", "PRN", "AUX", "NUL",
                "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
                "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
            },
            StringComparer.OrdinalIgnoreCase);

        public static TextDocumentInfo Read(string path)
        {
            byte[] raw = File.ReadAllBytes(path);
            bool hasBom = raw.Length >= 3 && raw[0] == 0xef && raw[1] == 0xbb && raw[2] == 0xbf;
            int offset = hasBom ? 3 : 0;
            string text = StrictUtf8.GetString(raw, offset, raw.Length - offset);
            string body = ManagedBlockPattern.Replace(text, string.Empty, 1);
            string normalized = NormalizeForMatching(body);

            return new TextDocumentInfo
            {
                Text = text,
                BodyText = body,
                HasUtf8Bom = hasBom,
                NewLine = text.Contains("\r\n") ? "\r\n" : "\n",
                ContentSha256 = ComputeSha256(Utf8WithoutBom.GetBytes(body)),
                NormalizedSha256 = ComputeSha256(Utf8WithoutBom.GetBytes(normalized)),
                FileSha256 = ComputeSha256(raw),
                FileSize = raw.LongLength
            };
        }

        public static string NormalizeForMatching(string text)
        {
            if (text == null)
            {
                return string.Empty;
            }

            string normalized = text.Normalize(NormalizationForm.FormKC).Replace("帮", "幇");
            normalized = RubyPattern.Replace(normalized, string.Empty);
            return WhitespacePattern.Replace(normalized, " ").Trim();
        }

        public static string ComputeStoryKeySha256(IEnumerable<string> storyKeys)
        {
            string joined = string.Join("\0", storyKeys ?? Enumerable.Empty<string>());
            return ComputeSha256(Utf8WithoutBom.GetBytes(joined));
        }

        public static string ComputeSha256(byte[] bytes)
        {
            using (SHA256 sha256 = SHA256.Create())
            {
                byte[] hash = sha256.ComputeHash(bytes);
                var builder = new StringBuilder(hash.Length * 2);
                foreach (byte value in hash)
                {
                    builder.Append(value.ToString("x2", CultureInfo.InvariantCulture));
                }

                return builder.ToString();
            }
        }

        public static DateTime GetExportedAt(string fileName, DateTime fallback)
        {
            Match match = ExportTimestampPattern.Match(fileName ?? string.Empty);
            if (match.Success && DateTime.TryParseExact(
                match.Groups["timestamp"].Value,
                "yyyyMMddHHmmss",
                CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeLocal,
                out DateTime parsed))
            {
                return parsed;
            }

            return fallback;
        }

        public static string BuildTargetPath(
            string sourcePath,
            string filePrefix,
            string titleName,
            string heroine,
            DateTime exportedAt,
            string hash8)
        {
            string directory = Path.GetDirectoryName(sourcePath) ?? string.Empty;
            string safePrefix = string.IsNullOrWhiteSpace(filePrefix)
                ? string.Empty
                : SanitizeComponent(filePrefix);
            string safeTitle = SanitizeComponent(titleName);
            string safeHeroine = SanitizeComponent(heroine);
            string timestamp = exportedAt.ToString("yyyyMMddHHmmss", CultureInfo.InvariantCulture);

            string baseName = string.IsNullOrEmpty(safePrefix)
                ? safeTitle + "_" + safeHeroine + "_" + timestamp + "_" + hash8
                : safePrefix + "_" + safeTitle + "_" + safeHeroine + "_" + timestamp + "_" + hash8;

            const int preferredPathLimit = 240;
            while (Path.Combine(directory, baseName + ".txt").Length > preferredPathLimit && safeTitle.Length > 8)
            {
                safeTitle = safeTitle.Substring(0, safeTitle.Length - 1);
                baseName = string.IsNullOrEmpty(safePrefix)
                    ? safeTitle + "_" + safeHeroine + "_" + timestamp + "_" + hash8
                    : safePrefix + "_" + safeTitle + "_" + safeHeroine + "_" + timestamp + "_" + hash8;
            }

            string candidate = Path.Combine(directory, baseName + ".txt");
            if (string.Equals(candidate, sourcePath, StringComparison.OrdinalIgnoreCase) || !File.Exists(candidate))
            {
                return candidate;
            }

            for (int suffix = 2; suffix < 10000; suffix++)
            {
                candidate = Path.Combine(directory, baseName + "_" + suffix.ToString(CultureInfo.InvariantCulture) + ".txt");
                if (!File.Exists(candidate))
                {
                    return candidate;
                }
            }

            throw new IOException("リネーム先の空きファイル名を確保できませんでした。");
        }

        public static string SanitizeComponent(string value)
        {
            string source = (value ?? string.Empty).Normalize(NormalizationForm.FormC);
            var builder = new StringBuilder(source.Length);
            foreach (char character in source)
            {
                switch (character)
                {
                    case '\\': builder.Append('￥'); break;
                    case '/': builder.Append('／'); break;
                    case ':': builder.Append('：'); break;
                    case '*': builder.Append('＊'); break;
                    case '?': builder.Append('？'); break;
                    case '"': builder.Append('”'); break;
                    case '<': builder.Append('＜'); break;
                    case '>': builder.Append('＞'); break;
                    case '|': builder.Append('｜'); break;
                    case '\r':
                    case '\n':
                    case '\t': builder.Append(' '); break;
                    default:
                        if (!char.IsControl(character))
                        {
                            builder.Append(character);
                        }
                        break;
                }
            }

            string result = Regex.Replace(builder.ToString(), @"\s+", " ").Trim().TrimEnd('.', ' ');
            if (string.IsNullOrWhiteSpace(result))
            {
                result = "不明";
            }

            if (ReservedNames.Contains(result))
            {
                result += "_";
            }

            return result;
        }
    }
}
