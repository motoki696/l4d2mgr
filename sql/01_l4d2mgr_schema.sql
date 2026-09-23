-- l4d2mgr: SourceMod管理WebGUI用DB（SourceBans++と同居のMariaDB）
-- 実行: sudo mysql < l4d2mgr_schema.sql
-- パスワードは実行前に置き換えること（このファイルに実値を残さない）

CREATE DATABASE IF NOT EXISTS l4d2mgr
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE l4d2mgr;

-- キャンペーンローテーション（1行 = 1キャンペーンの第1マップ）
CREATE TABLE IF NOT EXISTS rotation (
  id        INT AUTO_INCREMENT PRIMARY KEY,
  server_id INT NOT NULL,
  position  INT NOT NULL,
  map       VARCHAR(64) NOT NULL,
  enabled   TINYINT(1) NOT NULL DEFAULT 1,
  UNIQUE KEY uq_server_position (server_id, position)
) ENGINE=InnoDB;

-- 初期データ: 公式14キャンペーン（server_id 1 = L4D2, SourceBans++のServer IDと揃える）
INSERT IGNORE INTO rotation (server_id, position, map) VALUES
 (1, 1,  'c1m1_hotel'),
 (1, 2,  'c2m1_highway'),
 (1, 3,  'c3m1_plankcountry'),
 (1, 4,  'c4m1_milltown_a'),
 (1, 5,  'c5m1_waterfront'),
 (1, 6,  'c6m1_riverbank'),
 (1, 7,  'c7m1_docks'),
 (1, 8,  'c8m1_apartment'),
 (1, 9,  'c9m1_alleys'),
 (1, 10, 'c10m1_caves'),
 (1, 11, 'c11m1_greenhouse'),
 (1, 12, 'c12m1_hilltop'),
 (1, 13, 'c13m1_alpinecreek'),
 (1, 14, 'c14m1_junkyard');

-- ゲームサーバー用ユーザー: 読み取り専用（プラグインはSELECTのみ）
CREATE USER IF NOT EXISTS 'l4d2mgr_game'@'__GAME_SERVER_IP__' IDENTIFIED BY '__CHANGE_ME_GAME__';
GRANT SELECT ON l4d2mgr.rotation TO 'l4d2mgr_game'@'__GAME_SERVER_IP__';

-- WebGUI用ユーザーは第2版で作成（書き込み権限はWebGUI側のみに付与する）

FLUSH PRIVILEGES;
