import os, json
import logging
from logging.handlers import RotatingFileHandler
import pprint
from datetime import datetime, timedelta
from typing import Optional
from typing import Any
from dataclasses import dataclass, fields
from mijiaAPI import mijiaDevice, mijiaAPI
from bambulab import BambuClient, MQTTClient, PrinterStatus

device_id = None

BAMBU_TOKEN_FILE = ".bambu_token"
MIHOME_AUTH_FILE = ".mijia-api-auth.json"

MAX_STATUS_INTERVAL = 5 # in minutes

MAX_IDLE_TIME = int(os.getenv("MAX_IDLE_TIME", 15)) # in minutes

MI_HOME_DEVICE_NAME = os.getenv("MI_HOME_DEVICE_NAME", "3D打印机")

MAILER_ACCOUNT = os.getenv("MAILER_ACCOUNT", "16889373@qq.com")
MAILER_PASSWORD = os.getenv("MAILER_PASSWORD", "")
MAILER_HOST_SERVER = os.getenv("MAILER_HOST_SERVER", "smtp.qq.com")

LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()
LOG_FILE = "./monitor.log"

LOG_FORMAT = '%(levelname)-6s %(asctime)-8s %(module)s - %(funcName)s: %(message)s'
log_formatter = logging.Formatter(LOG_FORMAT, datefmt='%Y-%m-%d %H:%M:%S')
log_handler = RotatingFileHandler(LOG_FILE, mode='a', maxBytes=50 * 1024 * 1024, backupCount=2, encoding=None, delay=0)
log_handler.setFormatter(log_formatter)
log_level = getattr(logging, LOG_LEVEL, logging.INFO)
logging.basicConfig(level=log_level, handlers=[log_handler])

logger = logging.getLogger(__name__)

def shutdown_printer(reason: str = ""):
    """Shut down the p1sc printer"""
    logger.info("#" * 60)
    logger.info("Shutdown conditions met. Shutting down printer...")
    StatusTracker.reset_tracking()

    try:
        api = mijiaAPI(MIHOME_AUTH_FILE)
        device = mijiaDevice(api, dev_name=MI_HOME_DEVICE_NAME)
        device.set("on", "false")
    except Exception as e:
        logger.error("Exec shutdown error", exc_info=True)
        send_email(
            title="mijiaAPI error when shutdown printer",
            content=str(e)
            )
    # os.system(f"python3 -m mijiaAPI set -p {MIHOME_AUTH_FILE} --dev_name {MI_HOME_DEVICE_NAME} --prop_name on --value false  > /dev/null")
    send_email(
        title="Bambu Printer Shutdown",
        content="The Bambu printer has been shut down automatically due to inactivity{}.".format(reason)
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

def deep_update_dict(target_dict, source_dict):
    """
    Recursively updates target_dict with values from source_dict,
    ignoring None values in source_dict.
    """
    for key, value in source_dict.items():
        if value is None:
            # Ignore None values in the source_dict
            continue
        elif isinstance(value, dict) and key in target_dict and isinstance(target_dict[key], dict):
            # If both target and source have a dictionary for the same key,
            # recurse into the nested dictionaries
            deep_update_dict(target_dict[key], value)
        else:
            # Otherwise, update the value directly
            target_dict[key] = value
    return target_dict

def deep_update_dataclass(target: Any, source: Any) -> None:
    """
    Deep updates a target dataclass object with values from a source dataclass object,
    ignoring None values in the source.
    """
    if not isinstance(target, type(source)):
        raise TypeError("Target and source objects must be of the same dataclass type.")

    for field in fields(target):
        source_value = getattr(source, field.name)
        target_value = getattr(target, field.name)
        if target_value is None and source_value is not None:
            setattr(target, field.name, source_value)
            continue
        if target_value is not None and source_value is None:
            continue
        # print(field.name, target_value, source_value)
        if source_value is not None:
            if isinstance(target_value, (list, tuple)) and isinstance(source_value, (list, tuple)):
                # Handle lists/tuples: append or replace based on desired behavior
                # For simplicity here, we'll replace the list/tuple if source is not None
                setattr(target, field.name, source_value)
            elif isinstance(target_value, dict) and isinstance(source_value, dict):
                # Handle dictionaries: deep update
                # target_value.update(source_value)
                deep_update_dict(target_value, source_value)

            elif isinstance(target_value, object) and hasattr(target_value, '__dataclass_fields__') and \
                isinstance(source_value, object) and hasattr(source_value, '__dataclass_fields__'):
                # Recursively update nested dataclasses
                deep_update_dataclass(target_value, source_value)
            else:
                # Update simple fields
                setattr(target, field.name, source_value)

class StatusTracker:
    global device_id
    last_statustime = datetime.now()
    last_active_time = datetime.now()
    status = PrinterStatus(device_id=device_id)

    @classmethod
    def reset_tracking(cls):
        cls.last_active_time = datetime.now()
        cls.status = PrinterStatus(device_id=device_id)

    @classmethod
    def watch(cls, status: PrinterStatus):
        # Check for status timeout
        if datetime.now() - cls.last_statustime > timedelta(minutes=MAX_STATUS_INTERVAL):
            logger.warning("Status interval exceeded maximum({} minutes). Resetting tracking.".format(MAX_STATUS_INTERVAL))
            cls.reset_tracking()
        logger.debug("idle time: {}".format(datetime.now() - cls.last_active_time))
        logger.debug("receive status: \n" + pprint.pformat(status) + "\n")
        cls.last_statustime = datetime.now()
        # Deep update status
        deep_update_dataclass(cls.status, status)
        logger.debug("current status: \n" + pprint.pformat(cls.status) + "\n")
        # Check for activity
        if cls.status.print_stage is not None and cls.status.print_stage not in ("IDLE", "FINISH", "FAILED") \
            or cls.status.bed_target_temp is not None and cls.status.bed_target_temp != 0 \
            or cls.status.nozzle_temp is not None and cls.status.nozzle_temp > 85.0 \
            or cls.status.nozzle_target_temp is not None and cls.status.nozzle_target_temp > 0:
            # Update last active time
            cls.last_active_time = datetime.now()

        # Check for idle timeout and run shutdown if needed
        if datetime.now() - cls.last_active_time > timedelta(minutes=MAX_IDLE_TIME):
            logger.info(pprint.pformat(cls.status))
            shutdown_printer()
            # shutdown_printer(" (print_stage={}, bed_temp={}, bed_target_temp={}, nozzle_temp={}, nozzle_target_temp={})".format(
            #     cls.status.print_stage,
            #     cls.status.bed_temp, cls.status.bed_target_temp,
            #     cls.status.nozzle_temp, cls.status.nozzle_target_temp
            # ))

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
            StatusTracker.watch(status)
        except Exception as e:
            logger.error(f"Error processing status update: {e}")

        # Display update
        # self.display_status(status)

    def start(self):
        """Start monitoring"""
        print()
        print("Bambu Printer Monitor")
        print(f"Device ID: {self.device_id}")
        print("Watching ...")
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

    global device_id
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