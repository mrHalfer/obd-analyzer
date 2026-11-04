@echo off
rem Сборка OBD-II Analyzer в Docker
rem Запускать из корня проекта: docker\build.bat

set IMAGE=obd-analyzer

echo Building %IMAGE%...
docker build -f docker/Dockerfile -t %IMAGE% .

echo.
echo Done. Usage examples:
echo.
echo   Анализ одного файла:
echo   docker run --rm -v "C:\path\to\csvs:/data" %IMAGE% /data/log.csv -lang en
echo.
echo   Анализ директории:
echo   docker run --rm -v "C:\path\to\csvs:/data" %IMAGE% /data -lang ru
echo.
echo   Без PDF и Excel:
echo   docker run --rm -v "C:\path\to\csvs:/data" %IMAGE% /data -nopdf -noxls -lang en
echo.
echo   Пропустить уже обработанные:
echo   docker run --rm -v "C:\path\to\csvs:/data" %IMAGE% /data -continue -lang ru
