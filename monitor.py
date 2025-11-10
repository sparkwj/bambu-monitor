import os, json
import logging
from logging.handlers import RotatingFileHandler
import pprint
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path
from bambulab import BambuClient, MQTTClient, PrinterStatus

BAMBU_TOKEN_FILE = ".bambu_token"
MIHOME_AUTH_FILE = ".mijia-api-auth.json"

MI_HOME_DEVICE_NAME = os.getenv("MI_HOME_DEVICE_NAME", "3D打印机")

MAILER_ACCOUNT = os.getenv("MAILER_ACCOUNT", "16889373@qq.com")
MAILER_PASSWORD = os.getenv("MAILER_PASSWORD", "")
MAILER_HOST_SERVER = os.getenv("MAILER_HOST_SERVER", "smtp.qq.com")

LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()
LOG_FILE = "./monitor.log"

LGO_FORMAT = '%(levelname)s: %(asctime)-15s: %(module)s: %(funcName)s: %(message)s'
log_handler = RotatingFileHandler(LOG_FILE, mode='a', maxBytes=5 * 1024 * 1024, backupCount=2, encoding=None, delay=0)
log_level = getattr(logging, LOG_LEVEL, logging.INFO)
logging.basicConfig(level=log_level, format=LGO_FORMAT, handlers=[log_handler])

logger = logging.getLogger(__name__)

def shutdown_printer(reason: str = ""):
    """Shut down the p1sc printer"""
    if StatusTracker.nozzle_temp > 180.0:
        logger.info("Nozzle temperature is still high ({}C). Waiting for nozzle to cool down...".format(StatusTracker.nozzle_temp))
        return
    logger.info("Shutdown conditions met({}). Shutting down printer...".format(reason))
    StatusTracker.reset_tracking()
    os.system(f"python3 -m mijiaAPI set -p {MIHOME_AUTH_FILE} --dev_name {MI_HOME_DEVICE_NAME} --prop_name on --value false")
    send_email(
        title="Bambu Printer Shutdown",
        content="The Bambu printer has been shut down automatically due to inactivity ({}).".format(reason)
        )

def send_email(title, content):
    if not (MAILER_ACCOUNT and MAILER_PASSWORD):
        logger.info("Mailer account or password not set. Skipping email sending.")
        return
    import smtplib
    from email.message import EmailMessage
    from email.utils import formataddr
    message = EmailMessage()
    message['Subject'] = title
    message['From'] = formataddr(("Bambu Monitor", MAILER_ACCOUNT))  # Crucial: Set the 'From' header
    message['To'] = MAILER_ACCOUNT
    message.set_content(content)
    smtp = smtplib.SMTP_SSL(MAILER_HOST_SERVER, 465)
    smtp.login(MAILER_ACCOUNT, MAILER_PASSWORD)
    smtp.sendmail( MAILER_ACCOUNT, MAILER_ACCOUNT, message.as_string())
    smtp.quit()

class MetaStatusTracker(type):
    @property
    def time_since_threshold_bed(cls):
        return (datetime.now() - cls.threshold_start_bed).total_seconds()
    @property
    def time_since_threshold_bed_target(cls):
        return (datetime.now() - cls.threshold_start_bed_target).total_seconds()
    @property
    def time_since_threshold_nozzle_target(cls):
        return (datetime.now() - cls.threshold_start_nozzle_target).total_seconds()
    @property
    def time_since_idle(cls):
        return (datetime.now() - cls.threshold_since_idle).total_seconds()

class StatusTracker(metaclass=MetaStatusTracker):
    """Track printer status over time"""
    
    BED_THRESHOLD_TEMP = 40.0  # Degrees Celsius
    SHUTDOWN_DELAY_SECONDS = 15 * 60  # 15 minutes
    MAX_STATUS_INTERVAL = 5  # 10 minutes

    print_stage = None
    bed_temp = 0.0
    nozzle_temp = 0.0
    bed_target_temp = None
    nozzle_target_temp = None
    threshold_since_idle = datetime.now()
    threshold_start_bed = datetime.now()
    threshold_start_bed_target = datetime.now()
    threshold_start_nozzle_target = datetime.now()
    status_time = datetime.now()

    @classmethod
    def reset_tracking(cls):
        """Reset tracking variables"""
        cls.print_stage = None
        cls.bed_temp = 0.0
        cls.nozzle_temp = 0.0
        cls.bed_target_temp = None
        cls.nozzle_target_temp = None
        cls.threshold_since_idle = datetime.now()
        cls.threshold_start_bed = datetime.now()
        cls.threshold_start_bed_target = datetime.now()
        cls.threshold_start_nozzle_target = datetime.now()
        cls.status_time = datetime.now()

    @classmethod
    def update(cls, status: PrinterStatus):
        # clean_dict = {key: value for key, value in status.to_dict().items() if value is not None}
        clean_dict = cls._remove_none_recursively(status.to_dict())
        logger.debug("\n" + pprint.pformat(clean_dict))
        if datetime.now() - StatusTracker.status_time > timedelta(minutes=StatusTracker.MAX_STATUS_INTERVAL):
            StatusTracker.reset_tracking()
        StatusTracker.status_time = datetime.now()
        
        if status.print_stage is not None:
            StatusTracker.print_stage = status.print_stage
        if not StatusTracker.print_stage == "IDLE":
            StatusTracker.threshold_since_idle = datetime.now()
        
        if status.bed_temp is not None:
            StatusTracker.bed_temp = status.bed_temp
        if StatusTracker.bed_temp > StatusTracker.BED_THRESHOLD_TEMP:
            StatusTracker.threshold_start_bed = datetime.now()
        
        if status.nozzle_temp is not None:
            StatusTracker.nozzle_temp = status.nozzle_temp
        
        if status.bed_target_temp is not None:
            StatusTracker.bed_target_temp = status.bed_target_temp
        if not StatusTracker.bed_target_temp == 0:
            StatusTracker.threshold_start_bed_target = datetime.now()
        
        if status.nozzle_target_temp is not None:
            StatusTracker.nozzle_target_temp = status.nozzle_target_temp
        if not StatusTracker.nozzle_target_temp == 0:
            StatusTracker.threshold_start_nozzle_target = datetime.now()
    
    @classmethod
    def run_shutdown_strategy(cls):
        """Determine if printer should be shut down based on status"""
        logger.debug("\n" + pprint.pformat(StatusTracker.to_dict()))

        if StatusTracker.bed_temp < StatusTracker.BED_THRESHOLD_TEMP and StatusTracker.time_since_threshold_bed >= StatusTracker.SHUTDOWN_DELAY_SECONDS:
            shutdown_printer(f"bed_temp<{StatusTracker.BED_THRESHOLD_TEMP}")
            return
        if StatusTracker.bed_target_temp == 0 and StatusTracker.time_since_threshold_bed_target >= StatusTracker.SHUTDOWN_DELAY_SECONDS:
            shutdown_printer("bed_target_temp=0")
            return
        if StatusTracker.nozzle_target_temp == 0 and StatusTracker.time_since_threshold_nozzle_target >= StatusTracker.SHUTDOWN_DELAY_SECONDS:
            shutdown_printer("nozzle_target_temp=0")
            return
        if StatusTracker.print_stage == "IDLE" and StatusTracker.time_since_idle >= StatusTracker.SHUTDOWN_DELAY_SECONDS:
            shutdown_printer("IDLE state")
            return
    
    @classmethod
    def to_dict(cls):
        return {
            "print_stage": cls.print_stage,
            "bed_temp": cls.bed_temp,
            "nozzle_temp": cls.nozzle_temp,
            "bed_target_temp": cls.bed_target_temp,
            "nozzle_target_temp": cls.nozzle_target_temp,
            "threshold_start_bed": cls.threshold_start_bed.strftime("%Y-%m-%d %H:%M:%S"),
            "threshold_start_bed_target": cls.threshold_start_bed_target.strftime("%Y-%m-%d %H:%M:%S"),
            "threshold_start_nozzle_target": cls.threshold_start_nozzle_target.strftime("%Y-%m-%d %H:%M:%S"),
            "time_since_idle": cls.time_since_idle,
            "time_since_threshold_bed": cls.time_since_threshold_bed,
            "time_since_threshold_bed_target": cls.time_since_threshold_bed_target,
            "time_since_threshold_nozzle_target": cls.time_since_threshold_nozzle_target,
            "status_time": cls.status_time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    @classmethod
    def _remove_none_recursively(cls, obj):
        if isinstance(obj, dict):
            # Create a new dictionary to store non-None key-value pairs
            new_dict = {}
            for k, v in obj.items():
                # Recursively process values
                processed_v = cls._remove_none_recursively(v)
                # Add to new_dict only if the value is not None
                if processed_v is not None:
                    new_dict[k] = processed_v
            # Return None if the dictionary becomes empty after removing None values
            return new_dict if new_dict else None
        elif isinstance(obj, list):
            # Create a new list to store non-None items
            new_list = []
            for item in obj:
                # Recursively process items
                processed_item = cls._remove_none_recursively(item)
                # Add to new_list only if the item is not None
                if processed_item is not None:
                    new_list.append(processed_item)
            # Return None if the list becomes empty after removing None values
            return new_list if new_list else None
        else:
            # For non-dict/non-list types, return the value itself if not None
            return obj if obj is not None else None

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
        if self.message_count % 60  == 0:
            self.client.request_full_status()  # Request full status update
        
        self.message_count += 1
        self.message_count = self.message_count % 1000000  # Prevent overflow
        self.last_update = datetime.now()
        
        # Parse status
        status = PrinterStatus.from_mqtt(device_id, data)

        try:
            StatusTracker.update(status)
            StatusTracker.run_shutdown_strategy()
        except Exception as e:
            logger.error(f"Error processing status update: {e}")
        
        # Display update
        # self.display_status(status)
    
    def start(self):
        """Start monitoring"""
        print("*" * 29)
        print("* Bambu Lab Printer Monitor *")
        print(f"* Device ID {self.device_id} *")
        print("*" * 29)
        print()
        
        try:
            # Connect and start monitoring
            self.client.connect(blocking=True)
        except KeyboardInterrupt:
            print("\n\nStopping monitor...")
            self.client.disconnect()


def main():
    # send_email()
    # exit()
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
    
    StatusTracker.reset_tracking()
    monitor = PrinterMonitor(
        username=uid,
        access_token=token,
        device_id=device_id,
        region=region
    )
    monitor.start()

if __name__ == "__main__":
    main()