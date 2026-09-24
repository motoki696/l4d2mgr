CREATE TABLE `l4d2mgr`.`country_filter_blocklist` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `country_code` CHAR(2) NOT NULL UNIQUE,
    `added_by` VARCHAR(64) NOT NULL,
    `added_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

GRANT SELECT ON `l4d2mgr`.`country_filter_blocklist` TO 'l4d2mgr_game'@'__GAME_SERVER_IP__';
GRANT SELECT, INSERT, DELETE ON `l4d2mgr`.`country_filter_blocklist` TO 'l4d2mgr_web'@'localhost';
FLUSH PRIVILEGES;
