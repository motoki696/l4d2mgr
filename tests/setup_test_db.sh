#!/usr/bin/env bash
# ローカル開発VM専用: テスト用DBを初期化する（本番では絶対に実行しないこと）
# Usage: sudo ./tests/setup_test_db.sh <テストを実行するOSユーザー名>
set -euo pipefail
TEST_USER="${1:?usage: sudo $0 <os-user>}"
cd "$(dirname "$0")/.."
mysql -e "DROP DATABASE IF EXISTS l4d2mgr; DROP USER IF EXISTS 'l4d2mgr_web'@'localhost'; DROP USER IF EXISTS 'l4d2mgr_game'@'localhost';"
mysql < tests/fixtures/sourcebans_test.sql
for f in sql/0*.sql; do
  sed "s/__CHANGE_ME_GAME__/gamepw/; s/__CHANGE_ME_WEB__/webpw/; s/'__GAME_SERVER_IP__'/'localhost'/g" "$f" | mysql
done
# テスト実行ユーザー: unix_socket 認証でテスト用DBのみ操作可能
mysql -e "CREATE USER IF NOT EXISTS '${TEST_USER}'@'localhost' IDENTIFIED VIA unix_socket;
GRANT ALL ON sourcebans.* TO '${TEST_USER}'@'localhost';
GRANT ALL ON l4d2mgr.* TO '${TEST_USER}'@'localhost';
FLUSH PRIVILEGES;"
echo "test DB ready (run tests as: ${TEST_USER})"
