using System;
using System.Globalization;
using System.IO;
using System.Text;
using Mortal.Core;
using Newtonsoft.Json;
using UnityEngine;

namespace LegendManager.Plugin
{
    internal sealed class EndingPictureExporter
    {
        private static readonly Encoding Utf8WithoutBom = new UTF8Encoding(false);
        private readonly string _picturesDirectory;
        private readonly string _indexPath;

        public EndingPictureExporter(string legendDirectory)
        {
            _picturesDirectory = Path.Combine(legendDirectory, "Pictures");
            _indexPath = Path.Combine(_picturesDirectory, "index.json");
        }

        public void Export(string endKey, int titleId)
        {
            LibrarySystem library = LibrarySystem.Instance;
            LibraryItemData item = library?.EndGame?.Get(endKey);
            Sprite sprite = item?.Picture;
            if (sprite == null)
            {
                throw new InvalidOperationException("ED画像をゲームデータから取得できません: " + endKey);
            }

            byte[] png = EncodeSprite(sprite);
            SavePng(titleId, png);
        }

        public void SavePng(int titleId, byte[] png)
        {
            if (png == null || png.Length == 0)
            {
                throw new ArgumentException("ED画像データが空です。", nameof(png));
            }
            string sha256 = TextFileOperations.ComputeSha256(png);
            string fileName = sha256 + ".png";
            Directory.CreateDirectory(_picturesDirectory);
            string imagePath = Path.Combine(_picturesDirectory, fileName);
            if (!File.Exists(imagePath))
            {
                AtomicWriteBytes(imagePath, png);
            }

            PictureIndex index = ReadIndex();
            index.Endings[titleId.ToString(CultureInfo.InvariantCulture)] = new PictureIndexEntry
            {
                File = fileName,
                Sha256 = sha256,
                UpdatedAt = DateTimeOffset.Now.ToString("o", CultureInfo.InvariantCulture)
            };
            AtomicWriteBytes(
                _indexPath,
                Utf8WithoutBom.GetBytes(JsonConvert.SerializeObject(index, Formatting.Indented)));
        }

        private PictureIndex ReadIndex()
        {
            if (!File.Exists(_indexPath))
            {
                return new PictureIndex();
            }

            try
            {
                PictureIndex index = JsonConvert.DeserializeObject<PictureIndex>(
                    File.ReadAllText(_indexPath, Utf8WithoutBom));
                if (index == null)
                {
                    return new PictureIndex();
                }
                if (index.Endings == null)
                {
                    index.Endings = new System.Collections.Generic.Dictionary<string, PictureIndexEntry>();
                }
                return index;
            }
            catch (Exception)
            {
                return new PictureIndex();
            }
        }

        private static byte[] EncodeSprite(Sprite sprite)
        {
            Rect rect = sprite.textureRect;
            int width = Math.Max(1, Mathf.RoundToInt(rect.width));
            int height = Math.Max(1, Mathf.RoundToInt(rect.height));
            Texture source = sprite.texture;
            var scale = new Vector2(rect.width / source.width, rect.height / source.height);
            var offset = new Vector2(rect.x / source.width, rect.y / source.height);
            RenderTexture render = RenderTexture.GetTemporary(
                width,
                height,
                0,
                RenderTextureFormat.ARGB32,
                RenderTextureReadWrite.sRGB);
            RenderTexture previous = RenderTexture.active;
            Texture2D output = null;
            try
            {
                Graphics.Blit(source, render, scale, offset);
                RenderTexture.active = render;
                output = new Texture2D(width, height, TextureFormat.RGBA32, false);
                output.ReadPixels(new Rect(0, 0, width, height), 0, 0);
                output.Apply(false, false);
                return output.EncodeToPNG();
            }
            finally
            {
                RenderTexture.active = previous;
                RenderTexture.ReleaseTemporary(render);
                if (output != null)
                {
                    UnityEngine.Object.Destroy(output);
                }
            }
        }

        private static void AtomicWriteBytes(string path, byte[] bytes)
        {
            string temporaryPath = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                using (var stream = new FileStream(temporaryPath, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    stream.Write(bytes, 0, bytes.Length);
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
    }
}
