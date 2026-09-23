-- テスト専用: SourceBans++ の必要テーブル（本番スキーマの抜粋）とテストデータ
-- 全テストユーザーのパスワードは testpass（legacy のみ旧形式ハッシュ）
DROP DATABASE IF EXISTS sourcebans;
CREATE DATABASE sourcebans CHARACTER SET utf8mb4;
USE sourcebans;
CREATE TABLE sb_admins (aid int(6) NOT NULL auto_increment, user varchar(64) NOT NULL, authid varchar(64) NOT NULL default '', password varchar(128) NOT NULL, gid int(6) NOT NULL, email varchar(128) NOT NULL default '', extraflags int(10) UNSIGNED NOT NULL, PRIMARY KEY(aid), UNIQUE KEY user(user)) ENGINE=InnoDB;
CREATE TABLE sb_groups (gid int(6) NOT NULL auto_increment, type smallint NOT NULL default 0, name varchar(128) NOT NULL default 'unnamed', flags int(10) UNSIGNED NOT NULL, PRIMARY KEY(gid)) ENGINE=InnoDB;
CREATE TABLE sb_servers (sid int(6) NOT NULL auto_increment, ip varchar(64) NOT NULL, port int(5) NOT NULL, rcon varchar(64) NOT NULL, modid int(10) NOT NULL, enabled TINYINT NOT NULL DEFAULT 1, PRIMARY KEY(sid)) ENGINE=InnoDB;
CREATE TABLE sb_submissions (subid int(6) NOT NULL auto_increment, submitted int(11) NOT NULL, ModID int(6) NOT NULL, SteamId varchar(64) NOT NULL default 'unnamed', name varchar(128) NOT NULL, email varchar(128) NOT NULL, reason text NOT NULL, ip varchar(64) NOT NULL, subname varchar(128) default NULL, sip varchar(64) default NULL, archiv tinyint(1) default '0', archivedby INT(11) NULL, server tinyint(3) default NULL, PRIMARY KEY (subid)) ENGINE=InnoDB;
SET SESSION sql_mode = CONCAT(@@sql_mode, ',NO_AUTO_VALUE_ON_ZERO');
INSERT INTO sb_admins (aid,user,password,gid,extraflags) VALUES
 (0,'CONSOLE','',-1,0),
 (1,'motoki2','$2y$10$1CCeTDn82NAM1PfpCDWah.oSfnS3Wxp3K3PK33QoOL4cFX5tVltli',-1,16777216),
 (2,'noperm','$2y$10$RZFEj6lUKH4TO2Z8GcARWeM0BSfOLTmGLos5obe9p8rxyGKjfO9CO',-1,256),
 (3,'grpuser','$2y$10$iP9iUNhKBF3yHLYjmXJWH.PDpi3SVHATMtAlFzyXpA.TMvWVN2At2',1,0),
 (4,'legacy','11f6ad8ec52a2984abaafd7c3b516503785c2072',-1,16777216);
INSERT INTO sb_groups (gid,type,name,flags) VALUES (1,1,'websettings',524288);
INSERT INTO sb_servers (sid,ip,port,rcon,modid) VALUES (1,'127.0.0.1',27999,'rconpass',17);
