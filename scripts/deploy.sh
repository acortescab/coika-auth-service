#!/bin/bash
# Deploys IMAGE_TAG on the EC2 host (piped over ssh: `bash -s < scripts/deploy.sh`).
#
# State files in ~/codename_rats-auth_service:
#   .current-image-tag   tag of the image that is running AND passed the health check
#   .previous-image-tag  the tag that was current before it (target of rollback.sh)
#   .last-backup-file    pre-deploy database dump (only set when the dump succeeded)
set -euo pipefail

# Everything lives in main() so bash parses the whole script before running any of it, and stdin is
# closed for all commands: when the script is piped over ssh (`bash -s`), a command that reads stdin,
# such as `docker compose exec -T`, would otherwise swallow the rest of the script and end it silently
# with exit code 0.
main() {
  exec < /dev/null

  : "${ECR_REGISTRY:?ECR_REGISTRY is required}"
  : "${ECR_REPOSITORY:?ECR_REPOSITORY is required}"
  : "${IMAGE_TAG:?IMAGE_TAG is required}"
  : "${DB_USER:?DB_USER is required}"
  : "${DB_NAME:?DB_NAME is required}"

  REPO="${GITHUB_REPOSITORY:-acortescab/codename_rats-auth_service}"
  HEALTH_URL="${HEALTH_URL:-http://localhost:8000/v0/health/}"
  HEALTH_RETRIES="${HEALTH_RETRIES:-30}"
  KEEP_BACKUPS="${KEEP_BACKUPS:-5}"
  COMPOSE="docker compose -f docker-compose-prod.yml"

  mkdir -p ~/codename_rats-auth_service
  cd ~/codename_rats-auth_service

  # Fetch the compose file that belongs to the commit being deployed (IMAGE_TAG is the commit SHA),
  # not whatever is currently on main.
  fetch_compose() {
    curl -fsSL "https://raw.githubusercontent.com/$REPO/$1/docker-compose-prod.yml" -o docker-compose-prod.yml.new
    mv docker-compose-prod.yml.new docker-compose-prod.yml
  }

  wait_healthy() {
    for _ in $(seq 1 "$HEALTH_RETRIES"); do
      if curl -fsS "$HEALTH_URL" > /dev/null 2>&1; then
        return 0
      fi
      sleep 2
    done
    return 1
  }

  aws ecr get-login-password --region eu-west-1 | docker login --username AWS --password-stdin "$ECR_REGISTRY"

  PREVIOUS_TAG=""
  if [ -f .current-image-tag ]; then
    PREVIOUS_TAG="$(cat .current-image-tag)"
  fi

  # Backup the database before touching anything. A failed dump must not leave a stale pointer behind,
  # otherwise a later rollback could restore an unrelated, older dump.
  rm -f .last-backup-file
  if [ -f docker-compose-prod.yml ] && [ -n "$PREVIOUS_TAG" ]; then
    mkdir -p backups
    BACKUP_FILE="backups/db_backup_$(date +%s).sql"
    echo "Info: Creating database backup at $BACKUP_FILE"
    if $COMPOSE exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" > "$BACKUP_FILE" && [ -s "$BACKUP_FILE" ]; then
      echo "$BACKUP_FILE" > .last-backup-file
    else
      echo "Warning: Database backup failed; continuing without a backup"
      rm -f "$BACKUP_FILE"
    fi
    # keep only the newest backups
    (ls -1t backups/db_backup_*.sql 2>/dev/null || true) | tail -n +"$((KEEP_BACKUPS + 1))" | xargs -r rm -f --
  fi

  export IMAGE_TAG
  echo "Info: Deploying image tag $IMAGE_TAG"
  fetch_compose "$IMAGE_TAG"
  $COMPOSE pull api
  $COMPOSE up -d

  if wait_healthy; then
    if [ -n "$PREVIOUS_TAG" ] && [ "$PREVIOUS_TAG" != "$IMAGE_TAG" ]; then
      echo "$PREVIOUS_TAG" > .previous-image-tag
    fi
    echo "$IMAGE_TAG" > .current-image-tag
    echo "Success: $IMAGE_TAG is healthy"
    exit 0
  fi

  echo "Error: $IMAGE_TAG did not become healthy at $HEALTH_URL"
  $COMPOSE logs --tail 50 api || true

  # Put the last known-good image back (image only; the database is left untouched).
  if [ -n "$PREVIOUS_TAG" ]; then
    echo "Info: Reverting to previous image $PREVIOUS_TAG"
    export IMAGE_TAG="$PREVIOUS_TAG"
    fetch_compose "$PREVIOUS_TAG"
    $COMPOSE up -d
    if wait_healthy; then
      echo "Info: Previous image $PREVIOUS_TAG is healthy again"
    else
      echo "Error: Previous image $PREVIOUS_TAG is not healthy either; manual intervention required"
    fi
  else
    echo "Error: No previous image to revert to; manual intervention required"
  fi

  exit 1
}

main "$@"
