#!/usr/bin/env bash
# Сборка OBD-II Analyzer в Docker
# Запускать из корня проекта: bash docker/build.sh

set -e

IMAGE="obd-analyzer"

echo "Building $IMAGE..."
docker build -f docker/Dockerfile -t "$IMAGE" .

echo ""
echo "Done. Usage examples:"
echo ""
echo "  # Анализ одного файла (результаты рядом с CSV)"
echo "  docker run --rm -v \"/path/to/csvs:/data\" $IMAGE /data/log.csv -lang en"
echo ""
echo "  # Анализ директории"
echo "  docker run --rm -v \"/path/to/csvs:/data\" $IMAGE /data -lang ru"
echo ""
echo "  # Без PDF и Excel"
echo "  docker run --rm -v \"/path/to/csvs:/data\" $IMAGE /data -nopdf -noxls -lang en"
echo ""
echo "  # Пропустить уже обработанные"
echo "  docker run --rm -v \"/path/to/csvs:/data\" $IMAGE /data -continue -lang ru"
