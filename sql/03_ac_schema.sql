-- 検知基盤（DBサーバーで sudo mysql < このファイル）
USE l4d2mgr;

CREATE TABLE IF NOT EXISTS detections (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  ts          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  server_id   INT NOT NULL,
  detector    VARCHAR(32) NOT NULL,
  severity    TINYINT NOT NULL,
  steamid     VARCHAR(32) NOT NULL,
  steamid64   VARCHAR(20) NOT NULL,
  name        VARCHAR(128) NOT NULL,
  map         VARCHAR(64) NOT NULL,
  detail      VARCHAR(255) NOT NULL,
  status      ENUM('new','dismissed','submitted') NOT NULL DEFAULT 'new',
  reviewed_by VARCHAR(64) NULL,
  reviewed_at TIMESTAMP NULL,
  KEY idx_status_ts (status, ts),
  KEY idx_steamid (steamid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ゲームサーバー: detections は書き込みのみ（rotation の SELECT は 01 で付与済み）
GRANT INSERT ON l4d2mgr.detections TO 'l4d2mgr_game'@'__GAME_SERVER_IP__';

-- WebGUI: 閲覧と判定結果の更新のみ
GRANT SELECT ON l4d2mgr.detections TO 'l4d2mgr_web'@'localhost';
GRANT UPDATE (status, reviewed_by, reviewed_at) ON l4d2mgr.detections TO 'l4d2mgr_web'@'localhost';

-- WebGUI: SourceBans++ へ BAN申請(Submission)を登録するための最小権限
GRANT SELECT (sid, ip, port, rcon, modid) ON sourcebans.sb_servers TO 'l4d2mgr_web'@'localhost';
GRANT INSERT (submitted, ModID, SteamId, name, email, reason, ip, subname, sip, archiv, server)
  ON sourcebans.sb_submissions TO 'l4d2mgr_web'@'localhost';

FLUSH PRIVILEGES;
