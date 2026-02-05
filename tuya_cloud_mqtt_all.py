#!/usr/bin/env python3
"""
Tuya Cloud to MQTT Bridge - All Devices
Fetches ALL devices from Tuya Cloud API and publishes to MQTT
"""

import os
import sys
import time
import json
import tinytuya
import paho.mqtt.client as mqtt
from datetime import datetime

# Handle library installation
try:
    import pymongo
    import certifi
except ImportError:
    print("Installing dependencies (pymongo, certifi)...")
    os.system("pip install pymongo certifi")    
    import pymongo
    import certifi

# ===== Configuration =====
# Tuya Cloud API
TUYA_REGION = os.getenv("TUYA_REGION", "sg")
TUYA_API_KEY = os.getenv("TUYA_API_KEY", "")
TUYA_API_SECRET = os.getenv("TUYA_API_SECRET", "")

# MQTT Broker
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC_PREFIX = "tuya"

# MongoDB Atlas
MONGO_URI = "Mongo Name & Password"
DB_NAME = os.getenv("MONGO_DB", "smart_office")
COLLECTION_NAME = os.getenv("MONGO_COLLECTION", "device_raw_data")

# Polling interval (seconds)
POLL_INTERVAL = 2

print("="*60)
print("Tuya Cloud → MQTT Bridge (ALL DEVICES)")
print("="*60)
print(f"Region: {TUYA_REGION}")
print(f"MQTT Broker: {MQTT_BROKER}:{MQTT_PORT}")
print(f"Poll Interval: {POLL_INTERVAL}s")
print("="*60)

# ===== Initialize Tuya Cloud =====
if not TUYA_API_KEY or not TUYA_API_SECRET:
    print("\nError: Missing API credentials!")
    print("Set environment variables:")
    print("  TUYA_API_KEY=your_access_id")
    print("  TUYA_API_SECRET=your_access_secret")
    sys.exit(1)

try:
    cloud = tinytuya.Cloud(
        apiRegion=TUYA_REGION,
        apiKey=TUYA_API_KEY,
        apiSecret=TUYA_API_SECRET
    )
    print("\nTuya Cloud API initialized")
except Exception as e:
    print(f"\nFailed to initialize Tuya Cloud: {e}")
    sys.exit(1)

# ===== Get All Devices =====
print("\n🔍 Fetching device list...")
try:
    devices = cloud.getdevices()
    
    if isinstance(devices, list):
        device_count = len(devices)
        print(f"Found {device_count} devices:")
        for i, device in enumerate(devices, 1):
            device_id = device.get('id', 'unknown')
            device_name = device.get('name', 'Unknown')
            device_online = device.get('online', False)
            status = "Online" if device_online else "Offline"
            print(f"   {i}. {device_name} ({device_id}) - {status}")
    else:
        print(f"Unexpected response: {devices}")
        device_count = 0
        devices = []
except Exception as e:
    print(f"Failed to get devices: {e}")
    sys.exit(1)

if device_count == 0:
    print("\nNo devices found!")
    print("Make sure you've linked your Tuya App account in IoT Platform")
    sys.exit(1)

# ===== Initialize MongoDB =====
try:
    if MONGO_URI:
        print("\n1. Connecting to MongoDB Atlas...")
        mongo_client = pymongo.MongoClient(MONGO_URI, tlsCAFile=certifi.where())
        db = mongo_client[DB_NAME]
        collection = db[COLLECTION_NAME]
        # Test connection
        mongo_client.admin.command('ping')
        print("   Connected to MongoDB Atlas")
    else:
        print("\n⚠️ MongoDB URI not set. Logging disabled.")
        collection = None
except Exception as e:
    print(f"\nMongoDB Connection Error: {e}")
    collection = None

# ===== Initialize MQTT =====
# Fix DeprecationWarning
try:
    from paho.mqtt.enums import CallbackAPIVersion
    mqtt_client = mqtt.Client(CallbackAPIVersion.VERSION2)
except ImportError:
    mqtt_client = mqtt.Client()

device_commands = {}  # Store device IDs by topic

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"\nConnected to MQTT Broker: {MQTT_BROKER}:{MQTT_PORT}")
        
        # Subscribe to command topics for all devices
        client.subscribe(f"{MQTT_TOPIC_PREFIX}/+/+/set")
        client.subscribe(f"{MQTT_TOPIC_PREFIX}/+/set")  # New: Base set topic
        print(f"Subscribed to: {MQTT_TOPIC_PREFIX}/+/+/set AND {MQTT_TOPIC_PREFIX}/+/set")
    else:
        print(f"MQTT Connection failed with code {rc}")

def on_message(client, userdata, msg):
    """Handle MQTT commands and send to Tuya Cloud"""
    topic = msg.topic
    payload = msg.payload.decode()
    
    print(f"DEBUG: Message received topic={topic}")
    print(f"DEBUG: Message payload={payload}")
    
    print(f"\n Command received: {topic} = {payload}")
    
    try:
        # Format: tuya/{device_id}/{code}/set OR tuya/{device_id}/set (JSON)
        parts = topic.split('/')
        
        # CASE 1: Specific Code Topic -> tuya/{device_id}/{code}/set
        if len(parts) >= 4:
            device_id = parts[1]
            code = parts[2]
            
            commands = {
                'commands': [{
                    'code': code,
                    'value': payload.upper() == "ON" if payload.upper() in ["ON", "OFF"] else payload
                }]
            }
            
            result = cloud.sendcommand(device_id, commands)
            
            # Prepare response payload
            resp_topic = f"{MQTT_TOPIC_PREFIX}/{device_id}/response"
            
            if result.get('success'):
                msg = f"Command sent: {device_id}/{code} = {payload}"
                print(msg)
                mqtt_client.publish(resp_topic, json.dumps({"status": "success", "msg": msg, "code": code, "value": payload}))
                
                # ✨ Optimistic Update: Update UI immediately
                state_val = "ON" if payload.upper() == "ON" else "OFF"
                mqtt_client.publish(f"{MQTT_TOPIC_PREFIX}/{device_id}/{code}/state", state_val, retain=True)
            else:
                msg = f"Command failed: {result}"
                print(msg)
                mqtt_client.publish(resp_topic, json.dumps({"status": "error", "msg": msg, "result": result}))

        # CASE 2: Base Topic (JSON) -> tuya/{device_id}/set
        elif len(parts) == 3 and parts[2] == 'set':
            device_id = parts[1]
            try:
                # Try parsing JSON payload
                import json
                data = json.loads(payload)
                
                command_list = []
                for k, v in data.items():
                    if k.startswith('switch') or k.startswith('countdown'):
                        val = v
                        if str(v).upper() == "ON": val = True
                        if str(v).upper() == "OFF": val = False
                        command_list.append({'code': k, 'value': val})
                
                if command_list:
                    commands = {'commands': command_list}
                    result = cloud.sendcommand(device_id, commands)
                    
                    # Prepare response payload
                    resp_topic = f"{MQTT_TOPIC_PREFIX}/{device_id}/response"
                    
                    if result.get('success'):
                        msg = f"JSON Command sent: {command_list}"
                        print(msg)
                        mqtt_client.publish(resp_topic, json.dumps({"status": "success", "msg": msg, "cmd": command_list}))
                        
                        # ✨ Optimistic Update: Update UI immediately for all commands in batch
                        for cmd in command_list:
                             c_code = cmd['code']
                             c_val = cmd['value']
                             state_val = "ON" if c_val is True else "OFF" if c_val is False else str(c_val)
                             mqtt_client.publish(f"{MQTT_TOPIC_PREFIX}/{device_id}/{c_code}/state", state_val, retain=True)

                    else:
                        msg = f"JSON Command failed: {result}"
                        print(msg)
                        mqtt_client.publish(resp_topic, json.dumps({"status": "error", "msg": msg, "result": result}))
                else:
                    print(f"No valid commands found in JSON: {payload}")
                    
            except json.JSONDecodeError:
                print(f"Failed to parse JSON command: {payload}")

    except Exception as e:
        print(f"Error handling command: {e}")

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

try:
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.loop_start()
except Exception as e:
    print(f"\nFailed to connect to MQTT: {e}")
    sys.exit(1)

# ===== Global State Tracker =====
din_rail_is_on = True # Default to True (ON) so we log until proven OFF

# ===== Main Loop: Fetch ALL Devices → Publish to MQTT =====
print("\n Starting data polling loop...")
print("Press Ctrl+C to stop\n")

try:
    while True:
        try:
            for device in devices:
                device_id = device.get('id')
                device_name = device.get('name', 'Unknown')
                
                if not device_id:
                    continue
                
                # Fetch device status from Tuya Cloud
                data = cloud.getstatus(device_id)
                
                if isinstance(data, dict) and 'result' in data:
                    status_list = data['result']
                    
                    # Separator per device
                    current_time_str = time.strftime('%H:%M:%S')
                    print(f"\n{'='*50}")
                    print(f"📦 Device: {device_name} (Updated: {current_time_str})")
                    print(f"{'-'*50}")
                    
                    # Parse and publish each status
                    device_data = {}
                    
                    for item in status_list:
                        if isinstance(item, dict) and 'code' in item:
                            code = item['code']
                            value = item['value']
                            # Scaling Logic
                            if code == 'cur_voltage':
                                value = value / 10.0
                            elif code == 'cur_power':
                                value = value / 10.0
                            elif code == 'add_ele':
                                value = value / 1000.0
                            
                            device_data[code] = value
                            
                            # Publish to MQTT: tuya/{device_id}/{code}/state
                            topic = f"{MQTT_TOPIC_PREFIX}/{device_id}/{code}/state"
                            
                            # Format value
                            if isinstance(value, bool):
                                payload = "ON" if value else "OFF"
                            else:
                                payload = str(value)
                            
                            mqtt_client.publish(topic, payload, retain=True)
                            
                            # Thai Translation Map
                            THAI_LABELS = {
                                "cur_current": "กระแสไฟฟ้า (mA)",
                                "cur_power": "กำลังไฟฟ้า (W)",
                                "cur_voltage": "แรงดันไฟฟ้า (V)",
                                "add_ele": "พลังงานสะสม (kWh)", # Unit updated to kWh
                                "switch": "สถานะสวิตช์",
                                "switch_1": "สวิตช์ 1",
                                "switch_2": "สวิตช์ 2",
                                "countdown_1": "นับถอยหลัง 1",
                                "countdown_2": "นับถอยหลัง 2",
                                "relay_status": "สถานะ Relay",
                                "test_bit": "โหมดทดสอบ",
                                "voltage_coe": "ค่าแก้แรงดัน",
                                "electric_coe": "ค่าแก้พลังงาน",
                                "power_coe": "ค่าแก้กำลังไฟ",
                                "electricity_coe": "ค่าแก้หน่วยไฟฟ้า",
                                "fault": "ความผิดปกติ",
                                "switch_backlight": "ไฟพื้นหลัง",
                                "switch_inching": "Inch Mode"
                            }
                            
                            label = THAI_LABELS.get(code, code)
                            # Indented output for readability
                            print(f"   🔹 {label} ({code}) : {payload}")
                    
                    # Publish full device data
                    full_topic = f"{MQTT_TOPIC_PREFIX}/{device_id}/telemetry"
                    full_payload = json.dumps({
                        "name": device_name,
                        "id": device_id,
                        "data": device_data,
                        "timestamp": int(time.time()),
                        "api_t": data.get('t', 0) # Cloud Timestamp
                    })
                    mqtt_client.publish(full_topic, full_payload, retain=True)
                    
                    # Publish discovery message (for Device Manager)
                    discovery_topic = f"discovery/device/{device_id}/config"
                    discovery_payload = json.dumps({
                        "name": device_name,
                        "unique_id": device_id,
                        "state_topic": full_topic,
                        "command_topic": f"{MQTT_TOPIC_PREFIX}/{device_id}/set",  # Base command topic
                        "device": {
                            "identifiers": [device_id],
                            "name": device_name,
                            "manufacturer": "Tuya"
                        }
                    })
                    mqtt_client.publish(discovery_topic, discovery_payload, retain=True)

                    # ===== MongoDB Logging =====
                    if collection is not None:
                        should_log = True
                        
                        # Logic: Check Din Rail Status FIRST for global state
                        if device_name == "Din Rail Wi-Fi Switch with metering":
                            switch_status = device_data.get('switch')
                            if switch_status is not None:
                                din_rail_is_on = switch_status # Update Global State
                                if din_rail_is_on is False:
                                    print("Din Rail is OFF -> Logging Disabled for this cycle.")

                        # Condition 1: If IT IS the Din Rail and it's OFF -> Skip
                        if device_name == "Din Rail Wi-Fi Switch with metering":
                            if not din_rail_is_on:
                                should_log = False
                                print(f"DB Log Skipped (Main Power OFF)")
                        
                        # Condition 2: If IT IS the 2CH Switch -> Depend on Din Rail
                        elif device_name == "WiFi Smart 2CH Touch Switch":
                            if not din_rail_is_on:
                                should_log = False
                                print(f"DB Log Skipped (Dependent on Main Power)")

                        if should_log:
                            doc = {
                                "timestamp": datetime.now(),
                                "device_id": device_id,
                                "device_name": device_name,
                                "status": device_data, # Use the SCALED data
                                "source": "tuya_cloud_mqtt_bridge"
                            }
                            try:
                                result = collection.insert_one(doc)
                                print(f"   Saved to MongoDB: {result.inserted_id}")
                            except Exception as e:
                                print(f"    Failed to save to DB: {e}")
            
            print(f"\nPoll completed at {time.strftime('%H:%M:%S')} (Heartbeat)")
            print("-" * 60)
        
        except Exception as e:
            print(f"Error in polling loop: {e}")
        
        # Wait before next poll
        time.sleep(POLL_INTERVAL)

except KeyboardInterrupt:
    print("\n\nStopping...")
    mqtt_client.disconnect()
    print("Disconnected from MQTT")
    print("Goodbye!")
