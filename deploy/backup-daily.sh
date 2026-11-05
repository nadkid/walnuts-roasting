#!/bin/sh
set -eu
umask 077
backup_stamp=$(date -u +%Y%m%dT%H%M%SZ)
exec /usr/bin/python3 /opt/walnuts-roastery/scripts/backup.py /var/lib/walnuts/production.sqlite "/var/lib/walnuts/backups/production-${backup_stamp}.sqlite"
