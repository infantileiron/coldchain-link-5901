-- 班次归档功能升级（对应 SQLAlchemy 模型 entities.py 中的 ArchiveTask / ArchivedShipment / ArchivedSample
-- 以及 shipments / samples 新增的 archive_task_id 列）。
-- 新建部署由 Base.metadata.create_all 自动建表，无需执行本脚本；
-- 已有数据的部署因 create_all 不会 ALTER 既有表，需按下列语句手工升级（MySQL 8.0）。

ALTER TABLE shipments ADD COLUMN archive_task_id INT NULL;
CREATE INDEX ix_shipments_archive_task_id ON shipments (archive_task_id);

ALTER TABLE samples ADD COLUMN archive_task_id INT NULL;
CREATE INDEX ix_samples_archive_task_id ON samples (archive_task_id);

CREATE TABLE archive_tasks (
  id INT NOT NULL AUTO_INCREMENT,
  kind VARCHAR(20) NOT NULL,
  state VARCHAR(20) NOT NULL DEFAULT 'queued',
  stage VARCHAR(30) NOT NULL DEFAULT '',
  shipment_ids JSON NULL,
  package_path VARCHAR(260) NOT NULL DEFAULT '',
  checksum VARCHAR(64) NOT NULL DEFAULT '',
  progress JSON NULL,
  error TEXT NULL,
  actor VARCHAR(100) NOT NULL DEFAULT '',
  created VARCHAR(40) NULL,
  updated VARCHAR(40) NULL,
  PRIMARY KEY (id)
);

CREATE TABLE archived_shipments (
  id INT NOT NULL AUTO_INCREMENT,
  task_id INT NOT NULL,
  origin_shipment_id INT NOT NULL,
  code VARCHAR(60) NOT NULL,
  route VARCHAR(60) NOT NULL,
  zone VARCHAR(20) NOT NULL,
  driver VARCHAR(60) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_archived_shipment_task_origin (task_id, origin_shipment_id),
  KEY ix_archived_shipments_task_id (task_id),
  KEY ix_archived_shipments_origin (origin_shipment_id)
);

CREATE TABLE archived_samples (
  id INT NOT NULL AUTO_INCREMENT,
  task_id INT NOT NULL,
  origin_sample_id INT NOT NULL,
  origin_shipment_id INT NOT NULL,
  code VARCHAR(60) NOT NULL,
  exposure FLOAT NULL,
  excursions INT NULL,
  loss FLOAT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_archived_sample_task_origin (task_id, origin_sample_id),
  KEY ix_archived_samples_task_id (task_id),
  KEY ix_archived_samples_origin (origin_shipment_id)
);
