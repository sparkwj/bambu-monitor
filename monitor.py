import os, json
from pprint import pprint
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path
from bambulab import BambuClient, MQTTClient, PrinterStatus
from bambulab.utils import format_temperature, format_percentage, format_time_remaining

BAMBU_TOKEN_FILE = ".bambu_token"
MIHOME_AUTH_FILE = ".mijia-api-auth.json"
MI_HOME_DEVICE_NAME = "3D打印机"

def shutdown_printer(reason: str = ""):
    """Shut down the p1sc printer"""
    if StatusTracker.nozzle_temp > 200.0:
        print("Nozzle temperature is still high ({}C). Waiting for nozzle to cool down...".format(StatusTracker.nozzle_temp))
        return
    print("Shutdown conditions met({}). Shutting down printer...".format(reason))
    StatusTracker.reset_tracking()
    os.system(f"python3 -m mijiaAPI -p {MIHOME_AUTH_FILE} set --dev_name {MI_HOME_DEVICE_NAME} --prop_name on --value false")

class StatusTracker:
    """Track printer status over time"""
    
    BED_THRESHOLD_TEMP = 40.0  # Degrees Celsius
    SHUTDOWN_DELAY_SECONDS = 4 * 60  # 30 minutes
    MAX_STATUS_INTERVAL = 10  # 30 minutes

    bed_temp = 0.0
    nozzle_temp = 0.0
    bed_target_temp = None
    nozzle_target_temp = None
    threshold_start_bed = datetime.now()
    threshold_start_bed_target = datetime.now()
    threshold_start_nozzle_target = datetime.now()

    status_time = datetime.now()

    @classmethod
    def reset_tracking(cls):
        """Reset tracking variables"""
        cls.bed_temp = 0.0
        cls.nozzle_temp = 0.0
        cls.bed_target_temp = None
        cls.nozzle_target_temp = None
        cls.threshold_start_bed = datetime.now()
        cls.threshold_start_bed_target = datetime.now()
        cls.threshold_start_nozzle_target = datetime.now()
        cls.status_time = datetime.now()

    @classmethod
    def update_status_tracker(cls, status: PrinterStatus):
        pprint(status)
        if datetime.now() - StatusTracker.status_time > timedelta(minutes=StatusTracker.MAX_STATUS_INTERVAL):
            StatusTracker.reset_tracking()
        StatusTracker.status_time = datetime.now()
        
        if status.bed_temp is not None:
            StatusTracker.bed_temp = status.bed_temp
        if StatusTracker.bed_temp > StatusTracker.BED_THRESHOLD_TEMP:
            StatusTracker.threshold_start_bed = datetime.now()
        
        if status.bed_target_temp is not None:
            StatusTracker.bed_target_temp = status.bed_target_temp
        if not StatusTracker.bed_target_temp == 0:
            StatusTracker.threshold_start_bed_target = datetime.now()
        
        if status.nozzle_target_temp is not None:
            StatusTracker.nozzle_target_temp = status.nozzle_target_temp
        if not StatusTracker.nozzle_target_temp == 0:
            StatusTracker.threshold_start_nozzle_target = datetime.now()
        
        if status.nozzle_temp is not None:
            StatusTracker.nozzle_temp = status.nozzle_temp
    
    @classmethod
    def run_shutdown_strategy(cls):
        """Determine if printer should be shut down based on status"""
        time_since_threshold_bed = (datetime.now() - StatusTracker.threshold_start_bed).total_seconds()
        time_since_threshold_bed_target = (datetime.now() - StatusTracker.threshold_start_bed_target).total_seconds()
        time_since_threshold_nozzle_target = (datetime.now() - StatusTracker.threshold_start_nozzle_target).total_seconds()

        pprint({name: value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else value for name, value in StatusTracker.__dict__.items() if not (name.startswith('__') or callable(value) or isinstance(value, classmethod))})
        print("time_since_threshold_bed: ", time_since_threshold_bed)
        print("time_since_threshold_bed_target: ", time_since_threshold_bed_target)
        print("time_since_threshold_nozzle_target: ", time_since_threshold_nozzle_target)
        print()

        if StatusTracker.bed_temp < StatusTracker.BED_THRESHOLD_TEMP and time_since_threshold_bed >= StatusTracker.SHUTDOWN_DELAY_SECONDS:
            shutdown_printer(f"bed_temp<{StatusTracker.BED_THRESHOLD_TEMP}")
            return
        if StatusTracker.bed_target_temp == 0 and time_since_threshold_bed_target >= StatusTracker.SHUTDOWN_DELAY_SECONDS:
            shutdown_printer("bed_target_temp=0")
            return
        if StatusTracker.nozzle_target_temp == 0 and time_since_threshold_nozzle_target >= StatusTracker.SHUTDOWN_DELAY_SECONDS:
            shutdown_printer("nozzle_target_temp=0")
            return

class PrinterMonitor:
    """Monitor printer status with formatted output"""
    
    def __init__(self, username: str, access_token: str, device_id: str, region: Optional[str] = "global"):
        self.device_id = device_id
        self.message_count = 0
        self.last_update = None
        
        # Create MQTT client with callback
        self.client = MQTTClient(
            username=username,
            access_token=access_token,
            device_id=device_id,
            on_message=self.on_message,
            region=region
        )
    
    def on_message(self, device_id: str, data: dict):
        """Handle incoming MQTT messages"""
        self.message_count += 1
        self.last_update = datetime.now()
        
        # Parse status
        status = PrinterStatus.from_mqtt(device_id, data)
        StatusTracker.update_status_tracker(status)
        StatusTracker.run_shutdown_strategy()
        
        # Display update
        # self.display_status(status)
    
    def start(self):
        """Start monitoring"""
        print("=" * 26)
        print("Bambu Lab Printer Monitor")
        print("=" * 26)
        print(f"Device ID: {self.device_id}")
        print()
        
        try:
            # Connect and start monitoring
            self.client.connect(blocking=True)
        except KeyboardInterrupt:
            print("\n\nStopping monitor...")
            self.client.disconnect()
            print(f"Total messages received: {self.message_count}")


def main():
    region = "china"
    token = None
    
    if not os.path.exists(BAMBU_TOKEN_FILE):
        os.system('python3 Bambu-Lab-Cloud-API/cli_tools/login.py --region china --token-file {}'.format(BAMBU_TOKEN_FILE))
    if not os.path.exists(BAMBU_TOKEN_FILE):
        print("Error: Bambulabs token file not found. Please run this script again and login first.")
        return
    
    if not os.path.exists(MIHOME_AUTH_FILE):
        os.system("python3 -m mijiaAPI -l -p {}".format(MIHOME_AUTH_FILE))
    if not os.path.exists(MIHOME_AUTH_FILE):
        print("Error: MiHome token file not found. Please run this script again and login first.")
        return

    with open(BAMBU_TOKEN_FILE, 'r') as f:
        token = json.load(f).get("token")
    client = BambuClient(token=token, region=region)

    profile = client.get_user_profile()
    uid = "u_" + str(profile.get("uid"))

    devices = client.get_devices()
    device_id = devices[0].get("dev_id")
    
    StatusTracker.reset_tracking
    monitor = PrinterMonitor(
        username=uid,
        access_token=token,
        device_id=device_id,
        region=region
    )
    monitor.start()

if __name__ == "__main__":
    main()