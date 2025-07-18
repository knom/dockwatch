import docker
import requests
import os
import logging
import sys
from datetime import datetime

# Set up logging, loglevel from environment variable or default to INFO
loglevel = os.getenv("LOGLEVEL", "INFO").upper()

if loglevel not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
    raise ValueError(f"Invalid log level: {loglevel}")

# make /app/log directory if it doesn't exist
if not os.path.exists("/app/log"):
    os.makedirs("/app/log")

# Configure loggingq

logging.basicConfig(
    level=loglevel if loglevel else logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/app/log/docker_watch.log")
    ]
)

logger = logging.getLogger(__name__)

logger.debug(f"Log level set to {loglevel}")

if "WEBHOOK_URL" not in os.environ:
    logger.error("WEBHOOK_URL environment variable is not set")
    raise ValueError("WEBHOOK_URL environment variable is not set")

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
if not WEBHOOK_URL.startswith("http"):
    logger.error("Invalid WEBHOOK_URL: must start with http or https")
    raise ValueError("Invalid WEBHOOK_URL: must start with http or https")

logger.info(f"WEBHOOK_URL is set to {WEBHOOK_URL}")

# Initialize Docker client
logger.debug("Initializing Docker client")
client = docker.APIClient(base_url='unix://var/run/docker.sock')

# check if Docker is running
try:
    client.ping()
    logger.debug("Docker is running")
except docker.errors.APIError as e:
    logger.error(f"Error connecting to Docker: {e}")
    raise
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    raise

# Listen for Docker events
logger.info("Listening for Docker events...")

for event in client.events(decode=True):
    
    logger.debug(f"Received event: {event}")
    
    if event.get("Type") == "container" and event.get("Action") in ["health_status:healthy", "health_status:unhealthy", "start", "stop"]:
        # Extract container name and ID
        container_name = event["Actor"]["Attributes"].get("name")
        container_id = event["Actor"]["ID"]
        
        logger.debug(f"Event: {event['Type']}, Action: {event['Action']} on container {container_name} ({container_id})")

        # Check if the container has the label "knom.dockWatch.watchHealth=true"
        logger.debug(f"Inspecting container {container_id} for labels")
        
        container = client.inspect_container(container_id)
        labels = container.get("Config", {}).get("Labels", {})
        
        logger.debug(f"Container labels: {labels}")
        
        if labels.get("knom.dockWatch.watchHealth") == "true":
            logger.info(f"Event: {event['Type']}, Action: {event['Action']} on LABELED container {container_name} ({container_id})")
            
            # make this more safe
            if event["Action"] == "health_status:healthy":
                status = "healthy"
            elif event["Action"] == "health_status:unhealthy":
                status = "unhealthy"
            else:
                status = event["Action"]
            
            container_info = container.get("State", {})
            
            # Extract required fields
            started_at = container_info.get("StartedAt")
            finished_at = container_info.get("FinishedAt")
            
            # requests.exceptions.HTTPError: 409 Client Error: Conflict for url: http+docker://localhost/v1.49/containers/1622f35718cc6d0d49e4b5153439b97de8e7d2c1a71b67100d6b990419151953/logs?stderr=1&stdout=1&timestamps=0&follow=0&tail=10
            try:
                logs = client.logs(container_id, tail=10).decode("utf-8")  # Fetch last 10 lines of logs
            except docker.errors.NotFound:
                logger.warning(f"Container {container_id} not found for logs")
                logs = None
                continue
            except docker.errors.APIError as e:
                logger.error(f"Error fetching logs for container {container_id}: {e}")
                logs = None
                continue
            except Exception as e:  
                logger.error(f"Unexpected error fetching logs for container {container_id}: {e}")
                logs = None
                continue

            # Format plain JSON payload
            payload = {
                "container_name": container_name,
                "status": status,
                "started_at": started_at,
                "finished_at": finished_at,
                "logs": logs if logs else "No logs available"
            }
            
            logger.debug(f"Payload for webhook: {payload}")
            
            # Send webhook notification
            try:
                response = requests.post(WEBHOOK_URL, json=payload)
                response.raise_for_status()  # Raise an error for bad responses
            except requests.exceptions.RequestException as e:
                logger.error(f"Error sending webhook: {e}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error sending webhook: {e}")
                continue
            
            if response.status_code == 200:
                logger.info(f"Webhook sent successfully for {container_name}: {response.status_code} {response.text}")
            else:
                logger.error(f"Failed to send webhook for {container_name}: {response.status_code} (HTTP {response.status_code})")
            