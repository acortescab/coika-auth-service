#!/bin/bash
# Rolls the running deployment back to the previous image (piped over ssh: `bash -s < scripts/rollback.sh`).
#
# By default only the image is rolled back; the database is left as it is, so no user data is lost.
# Set RESTORE_DB=1 to also restore the pre-deploy dump (.last-backup-file). Do that only when the failed
# release ran a destructive migration: everything written since that dump is discarded.
set -euo pipefail

# Everything lives in main() so bash parses the whole script before running any of it, and stdin is
# closed for all commands: when the script is piped over ssh (`bash -s`), a command that reads stdin,
# such as `docker compose exec -T`, would otherwise swallow the rest of the script and end it silently
# with exit code 0.
main() {
  exec < /dev/null

  : "${ECR_REGISTRY:?ECR_REGISTRY is required}"
  : "${ECR_REPOSITORY:?ECR_REPOSITORY is required}"
  : "${DB_USER:?DB_USER is required}"
  : "${DB_NAME:?DB_NAME is required}"

  REPO="${GITHUB_REPOSITORY:-acortescab/codename_rats-auth_service}"
  HEALTH_URL="${HEALTH_URL:-http://localhost:8000/v0/health/}"
  HEALTH_RETRIES="${HEALTH_RETRIES:-30}"
  RESTORE_DB="${RESTORE_DB:-0}"
  COMPOSE="docker compose -f docker-compose-prod.yml"

  mkdir -p ~/codename_rats-auth_service
  cd ~/codename_rats-auth_service

  if [ ! -f .previous-image-tag ]; then
    echo "Error: .previous-image-tag not found; there is no earlier release to roll back to."
    exit 1
  fi

  ROLLBACK_TAG="$(cat .previous-image-tag)"

  if [ -z "$ROLLBACK_TAG" ]; then
    echo "Error: Rollback tag is empty."
    exit 1
  fi

  aws ecr get-login-password --region eu-west-1 | docker login --username AWS --password-stdin "$ECR_REGISTRY"

  echo "Info: Rolling back to image: $ROLLBACK_TAG"

  # Use the compose file from the release being restored.
  curl -fsSL "https://raw.githubusercontent.com/$REPO/$ROLLBACK_TAG/docker-compose-prod.yml" -o docker-compose-prod.yml.new
  mv docker-compose-prod.yml.new docker-compose-prod.yml

  if [ "$RESTORE_DB" = "1" ]; then
    BACKUP_FILE=""
    [ -f .last-backup-file ] && BACKUP_FILE="$(cat .last-backup-file)"

    if [ -z "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ]; then
      echo "Error: RESTORE_DB=1 but no valid backup file was found; aborting before changing anything."
      exit 1
    fi

    echo "Info: Restoring database from: $BACKUP_FILE (data written since this dump will be lost)"
    export IMAGE_TAG="$ROLLBACK_TAG"
    $COMPOSE stop api
    $COMPOSE up -d db

    for _ in $(seq 1 30); do
      $COMPOSE exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" > /dev/null 2>&1 && break
      sleep 2
    done

    # Restore into a clean schema through a single transaction so a bad dump does not leave a half-restored DB.
    $COMPOSE exec -T db psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
      -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
    $COMPOSE exec -T db psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 --single-transaction < "$BACKUP_FILE"
    echo "Success: Database restored"
  else
    echo "Info: Leaving the database untouched (set RESTORE_DB=1 to restore the last backup)"
  fi

  export IMAGE_TAG="$ROLLBACK_TAG"
  $COMPOSE pull api
  $COMPOSE up -d

  for _ in $(seq 1 "$HEALTH_RETRIES"); do
    if curl -fsS "$HEALTH_URL" > /dev/null 2>&1; then
      # the release we rolled back to is now current; nothing earlier is known-good
      echo "$ROLLBACK_TAG" > .current-image-tag
      rm -f .previous-image-tag
      echo "Success: Application rolled back to $ROLLBACK_TAG"
      exit 0
    fi
    sleep 2
  done

  echo "Error: $ROLLBACK_TAG did not become healthy after rollback; manual intervention required"
  $COMPOSE logs --tail 50 api || true
  exit 1
}

main "$@"
