import os
ROLES=('admin','analyst','viewer')
STATES=('queued','running','done','failed')
ZONES=('冷藏','冷冻','常温对照')
# 班次归档任务：archiving=归档流程，restoring=恢复流程
ARCHIVE_KINDS=('archiving','restoring')
ARCHIVE_STATES=('queued','running','done','failed')
ARCHIVE_STAGES=('packing','verifying','cleaning','finished')
RESTORE_STAGES=('verifying','restoring','finished')
ACTIVE_ARCHIVE_STATES=('queued','running')
ARCHIVE_PACKAGE_VERSION='archive-package-1.0'
ARCHIVE_QUEUE='archives'
RESTORE_QUEUE='restores'
ARTIFACT_DIR=os.environ.get('ARCHIVE_ARTIFACT_DIR','/artifacts')
