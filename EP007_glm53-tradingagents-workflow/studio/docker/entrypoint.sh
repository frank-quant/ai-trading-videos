#!/bin/sh
set -e

# studio 容器入口：
#   默认/`cron`   -> 报告服务(后台) + 常驻调度器(前台)
#   其他命令      -> 透传给 studio（如 docker compose run studio studio doctor）
if [ "$#" -eq 0 ] || { [ "$#" -eq 1 ] && [ "$1" = "cron" ]; }; then
    studio report serve --port "${STUDIO_REPORT_PORT:-8890}" &
    exec studio cron
fi

exec studio "$@"
