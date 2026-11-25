#!/usr/bin/env bash
#
# Управление docker-контейнером бота-напоминальщика.
#
#   ./deploy.sh            — собрать образ и (пере)запустить контейнер
#   ./deploy.sh up         — то же самое
#   ./deploy.sh rebuild    — пересобрать без кэша и перезапустить
#   ./deploy.sh logs       — смотреть логи
#   ./deploy.sh status     — состояние контейнера
#   ./deploy.sh stop       — остановить и удалить контейнер (том с БД сохраняется)
#
set -euo pipefail

IMAGE="reminder-bot"
CONTAINER="reminder-bot"
VOLUME="reminder_bot_data"
ENV_FILE=".env"
DATA_DIR="/app/data"

cd "$(dirname "$0")"

usage() {
    sed -n '3,11p' "$0" | sed 's/^# \{0,1\}//'
}

check_env() {
    if [[ ! -f "$ENV_FILE" ]]; then
        echo "Ошибка: не найден $ENV_FILE." >&2
        echo "Скопируйте .env.example в .env и укажите BOT_TOKEN." >&2
        exit 1
    fi
    if ! grep -Eq '^[[:space:]]*BOT_TOKEN=[^[:space:]]+' "$ENV_FILE"; then
        echo "Ошибка: в $ENV_FILE не задан BOT_TOKEN." >&2
        exit 1
    fi
}

up() {
    local build_args="${1:-}"

    if ! command -v docker >/dev/null 2>&1; then
        echo "Ошибка: docker не установлен или недоступен." >&2
        exit 1
    fi

    check_env

    echo "Сборка образа ${IMAGE}..."
    # shellcheck disable=SC2086
    docker build ${build_args} -t "$IMAGE" .

    if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
        echo "Удаляю старый контейнер ${CONTAINER}..."
        docker rm -f "$CONTAINER" >/dev/null
    fi

    echo "Запуск контейнера ${CONTAINER}..."
    docker run -d \
        --name "$CONTAINER" \
        --restart unless-stopped \
        --env-file "$ENV_FILE" \
        -v "${VOLUME}:${DATA_DIR}" \
        "$IMAGE" >/dev/null

    echo
    echo "Готово. Контейнер ${CONTAINER} запущен."
    docker ps --filter "name=^/${CONTAINER}$"
    echo
    echo "Логи:  ./deploy.sh logs"
    echo "Стоп:  ./deploy.sh stop"
}

case "${1:-up}" in
    up)
        up
        ;;
    rebuild)
        up "--no-cache"
        ;;
    logs)
        docker logs -f "$CONTAINER"
        ;;
    status)
        docker ps -a --filter "name=^/${CONTAINER}$"
        ;;
    stop)
        docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
        echo "Контейнер ${CONTAINER} остановлен. База в томе ${VOLUME} сохранена."
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        echo "Неизвестная команда: $1" >&2
        echo
        usage >&2
        exit 1
        ;;
esac
