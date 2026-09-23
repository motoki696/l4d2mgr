-- l4d2mgr WebGUI 用追加スキーマ（DBサーバーで sudo mysql < このファイル）
-- 実行前に __CHANGE_ME_WEB__ を置換すること

USE l4d2mgr;

CREATE TABLE IF NOT EXISTS audit_log (
  id      BIGINT AUTO_INCREMENT PRIMARY KEY,
  ts      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  aid     INT NULL,
  user    VARCHAR(64) NULL,
  action  VARCHAR(64) NOT NULL,
  detail  VARCHAR(255) NULL,
  ip      VARCHAR(45) NULL,
  KEY idx_ts (ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- WebGUIは同一VM上で動くので localhost 限定
CREATE USER IF NOT EXISTS 'l4d2mgr_web'@'localhost' IDENTIFIED BY '__CHANGE_ME_WEB__';

-- 自DB: 読み書き
GRANT SELECT, INSERT, UPDATE, DELETE ON l4d2mgr.rotation  TO 'l4d2mgr_web'@'localhost';
GRANT SELECT, INSERT                 ON l4d2mgr.audit_log TO 'l4d2mgr_web'@'localhost';

-- SourceBans++: 必要な列だけ読み取り（書き込み権限なし）
GRANT SELECT (aid, user, password, gid, extraflags) ON sourcebans.sb_admins  TO 'l4d2mgr_web'@'localhost';
GRANT SELECT (gid, flags)                           ON sourcebans.sb_groups  TO 'l4d2mgr_web'@'localhost';
GRANT SELECT (sid, ip, port, rcon)                  ON sourcebans.sb_servers TO 'l4d2mgr_web'@'localhost';

FLUSH PRIVILEGES;
