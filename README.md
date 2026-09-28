# nexa-eng/.github

組織プロフィール（[github.com/nexa-eng](https://github.com/nexa-eng) の上部に表示される README）と、活動ヒートマップの自動生成を置くリポジトリです。

| パス | 役割 |
|------|------|
| `profile/README.md` | 組織トップページに表示されるプロフィール |
| `profile/activity-{light,dark}.svg` | 直近52週の組織全体のコミット活動ヒートマップ（自動生成・ライト／ダーク） |
| `scripts/build_activity.py` | 組織内の全リポジトリの `stats/commit_activity` を集計して SVG を描画（標準ライブラリのみ） |
| `.github/workflows/activity.yml` | 毎日 06:00 JST に SVG を再生成してコミット |

## セットアップ（1回だけ）

ワークフロー既定の `GITHUB_TOKEN` はこのリポジトリしか読めないため、組織の非公開リポジトリを集計するにはトークンをシークレット `ORG_STATS_TOKEN` に登録します。

1. GitHub → Settings → Developer settings → Fine-grained personal access tokens → Generate new token
   - Resource owner: `nexa-eng`
   - Repository access: All repositories
   - Permissions: Repository permissions → **Contents: Read-only**（Metadata は自動で付きます）
2. 登録:
   ```sh
   gh secret set ORG_STATS_TOKEN --repo nexa-eng/.github
   ```
3. 動作確認:
   ```sh
   gh workflow run activity.yml --repo nexa-eng/.github
   ```

公開されるのは日別の合計コミット数だけで、リポジトリ名は SVG に含まれません。集計はデフォルトブランチのみ、フォークと本リポジトリ自身は除外します。

## 手元で生成する

```sh
GITHUB_TOKEN=$(gh auth token) python3 scripts/build_activity.py
```
