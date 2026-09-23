# l4d2mgr

Left 4 Dead 2 専用サーバー（SourceMod 1.12）向けの管理ツール群。
SourceBans++ と同じ MariaDB を共有し、1つの WebGUI からプラグインを管理する。

## 構成

| パス | 内容 |
|---|---|
| `sourcemod/scripting/l4d2mgr_rotation.sp` | キャンペーンローテーション。`finale_win` 後に次キャンペーンへ `ForceChangeLevel`。DB → キャッシュファイル → 公式14キャンペーンの順にフォールバック |
| `sourcemod/scripting/l4d2mgr_ac_core.sp` | 検知基盤。native `L4D2AC_Report()` を受けて DB 記録・ファイルログ・管理者通知。**自動BANはしない** |
| `sourcemod/scripting/l4d2mgr_ac_speedhack.sp` | 検知アドオン: usercmd/秒 と tickrate の比でスピードハックを検知 |
| `sourcemod/scripting/include/l4d2mgr_ac.inc` | 検知アドオン用 API |
| `web/l4d2mgr_web/` | WebGUI（FastAPI）。SourceBans++ 管理者アカウントでログイン、サーバー状態、ローテーション編集、マップ変更、検知一覧、SourceBans++ への BAN申請 |
| `sql/` | DB スキーマと最小権限 GRANT（01 → 02 → 03 の順に適用） |
| `tests/` | WebGUI 結合テスト（MariaDB + 偽RCONサーバー）、RCON クライアント単体テスト |

```
[検知アドオン] --L4D2AC_Report()--> [ac_core] --INSERT--> l4d2mgr.detections
                                                            │
[WebGUI /detections] --BAN申請--> sourcebans.sb_submissions --> SourceBans++ で最終判断
[WebGUI /] --DB--> l4d2mgr.rotation <--SELECT-- [rotation]
          --RCON--> changelevel / sm_rotation_reload / sm_rotation_next
```

## 検知アドオンの追加

```sourcepawn
#include <l4d2mgr_ac>
// ...
L4D2AC_Report(client, "detector_name", severity /*1-3*/, "evidence text");
```
DB・通知・クールダウンは ac_core が処理する。

## セットアップ概要

1. **DB**（SourceBans++ の MariaDB）: `sql/01` → `02` → `03` の `__CHANGE_ME_*__` と `__GAME_SERVER_IP__` を置換して適用。`SHOW GRANTS` で権限を確認。
2. **プラグイン**: `SPCOMP=<sourcemod>/scripting/spcomp64 ./scripts/build_plugins.sh` でビルドし、`sourcemod/plugins/*.smx` を配置。`sourcemod/configs/databases.cfg.example` を `databases.cfg` に追記。
3. **WebGUI**: `web/deploy/` の systemd ユニット・nginx 設定・`env.example` を使用。Python venv に `web/requirements.txt` をインストール。

## セキュリティ設計

- DB ユーザーは用途別に分離（ゲームサーバー: rotation SELECT / detections INSERT のみ。WebGUI: SourceBans++ は必要列のみ SELECT、sb_submissions は INSERT のみ）
- WebGUI: bcrypt 照合（SourceBans++ の `$2y$` ハッシュ）、Owner / Web Settings 権限必須、リクエスト毎に権限再検証、CSRF トークン、ログイン試行制限、CSP 等のセキュリティヘッダ、監査ログ
- RCON に渡すマップ名は `^[A-Za-z0-9_]{1,64}$` のみ許可
- 認証情報はリポジトリに含めない（`env.example` / `databases.cfg.example` は空欄）

## 既知の制約

- L4D2 は無人時にハイバネーションし、SourceMod の非同期DB処理が進まない。`sm_rotation_reload` は次にプレイヤーが入った時点で反映される（`changelevel` は無人でも即時）。
- speedhack の閾値（ratio 1.25 × 5秒窓 × 3回連続）は未較正。`l4d2mgr_ac_speed_debug 1` で窓ごとの ratio / スキップ理由を SourceMod ログに出力できるので、実プレイの分布を見て調整すること。
- 記録経路の疎通確認: ゲーム内で Root 管理者が `sm_l4d2ac_selftest` を実行すると `selftest` 検知が1件記録される（WebGUI で却下して処理）。

## テスト（開発VM専用）

```bash
# 1回だけ: テスト用DBを初期化（sourcebans / l4d2mgr を作り直すので本番では実行しないこと）
sudo ./tests/setup_test_db.sh "$USER"

# Python 3.12 の venv（uv 利用例）
uv venv -p 3.12 .venv && uv pip install -p .venv -r web/requirements-dev.txt

.venv/bin/python tests/test_app.py                               # WebGUI 結合テスト
(cd web && ../.venv/bin/python ../tests/test_rcon.py l4d2mgr_web/rcon.py)   # RCON 単体テスト
SPCOMP=/opt/sourcemod-1.12.0-7253/addons/sourcemod/scripting/spcomp64 ./scripts/build_plugins.sh
```

## 開発体制

コードは主にローカル LLM（Ollama: gpt-oss:20b / qwen3.8:27b）が生成し、Claude が仕様策定・レビュー・コンパイル/結合テストによる検証と修正を担当した。
