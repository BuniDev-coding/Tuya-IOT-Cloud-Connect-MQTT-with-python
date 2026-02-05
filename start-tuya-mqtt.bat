@echo off
echo Starting Tuya Cloud to MQTT Bridge...
echo.

REM Set your Tuya Cloud API credentials here
set TUYA_REGION=sg
set TUYA_API_KEY=pq7h5aw3q99qp9rnkfa3
set TUYA_API_SECRET=e7b1d65f2d7a48d6ac2acbffb8677594
set TUYA_DEVICE_ID=a316b14c8d5efb6070abkd

REM MQTT Broker settings
set MQTT_BROKER=localhost
set MQTT_PORT=1883

REM MongoDB Atlas Configuration
REM ⚠️ PASTE YOUR CONNECTION STRING BELOW (Replace the line)
set MONGO_URI=mongodb+srv://user:password@cluster.mongodb.net/?retryWrites=true^&w=majority
set MONGO_DB=smart_office
set MONGO_COLLECTION=device_raw_data

echo Configuration:
echo   Region: %TUYA_REGION%
echo   Device ID: %TUYA_DEVICE_ID%
echo   MQTT Broker: %MQTT_BROKER%:%MQTT_PORT%
echo.

if "%TUYA_API_KEY%"=="" (
    echo ERROR: TUYA_API_KEY not set!
    echo Please edit this file and add your credentials.
    pause
    exit /b 1
)

if "%TUYA_API_SECRET%"=="" (
    echo ERROR: TUYA_API_SECRET not set!
    echo Please edit this file and add your credentials.
    pause
    exit /b 1
)

echo Starting bridge...
echo Press Ctrl+C to stop
echo.

python tuya_cloud_mqtt_all.py

pause
