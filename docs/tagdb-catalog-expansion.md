# Tag DB カタログ拡充記録

- 実施日: 2026-09-12
- ブランチ: `feat/tagdb-workbench-catalog`
- 対象: `ComfyUI-Prompt-Workbench`

## 実施内容

`genai-tag-db-tools` の SQLite データベースから Danbooru 形式のタグを抽出し、Prompt Workbench のカタログ形式へ変換した。
既存の `data/tag_catalog.json` は保持し、DB 由来のタグを既存名と照合して重複を除外したうえで追加した。

変換処理は [`scripts/export_tagdb_catalog.py`](../scripts/export_tagdb_catalog.py) に追加した。DB は読み取り専用で開き、翻訳、使用数、別名、非推奨状態を扱える。デフォルトでは正規タグだけを出力し、`--include-aliases` を指定した場合だけ別名を `aliases` に出力する。

## カタログ階層

DB に Workbench 固有のカテゴリ情報はないため、次の階層に写像した。

```text
format: danbooru
└── type: general / artist / character / ...
    └── 未分類
```

この構造で Workbench が要求する大分類・中分類・小分類を満たしている。意味的なカテゴリ分類は追加していない。

## 結果

- 変更ファイル: `data/tag_catalog.json`
- 既存タグ: 2,921 件
- DB から追加: 6,304 件
- 合計: 9,225 件
- 大分類: 9
- 中分類: 38
- 小分類: 156
- JSON サイズ: 約 2.79 MB

## 検証

- `python -m py_compile scripts/export_tagdb_catalog.py`
- `routes.validate_user_catalog()` によるカタログ検証
- `git diff --check`

すべて通過した。Workbench のタグ上限 10,000 件とカタログサイズ上限 4 MB の範囲内に収まっている。

## 再生成例

```powershell
python scripts/export_tagdb_catalog.py `
  --database <genai-tag-db.sqlite> `
  --output data/tagdb_danbooru_catalog.json `
  --format danbooru `
  --limit 7000
```

既存カタログとの統合は現時点では生成後の処理で行っている。DB の更新時に同じ統合処理を再実行する必要がある。
