import logging
from threading import Thread, current_thread

import requests
import pandas as pd

from volume_type_validation import AwsVolumeTypeValidation

logger = logging.getLogger()
MAX_RETRIES = 3


def _retryable(method: str, *args, **kwargs) -> requests.Response:
    """Retryable HTTP request.

    Invoke a "method" on "requests.session" with retry logic.
    :param method: "get", "post" etc.
    :param *args: Args for requests (first should be an URL, etc.)
    :param **kwargs: Kwargs for requests
    :return: Response object
    :raises: HTTPError when all requests fail
    """
    thread = current_thread()

    with requests.Session() as session:
        for attempt in range(MAX_RETRIES):
            try:
                resp = getattr(session, method)(*args, **kwargs)

                resp.raise_for_status()
            except (requests.HTTPError, requests.ConnectionError) as e:
                logger.warning(
                    '%s: Request failed (attempt #%d), retrying: %s',
                    thread.name, attempt, str(e)
                )
                continue
            else:
                return resp

    raise requests.HTTPError('All attempts failed')


# define the AI_Task_worker here as shown below -
# def volume_type_validation_worker(
#         job: dict,
#         next_service: str,
#         b64_identity: str = None
# )

def volume_type_validation_worker(
        job: dict,
        next_service: str,
        ai_service: str,
        b64_identity: str = None
) -> Thread:
    """Validate Volume Types."""

    def worker() -> None:
        thread = current_thread()
        logger.debug('%s: Worker started', thread.name)

        try:
            batch_id, batch_data = job['id'], job['data']
        except KeyError:
            logger.error("%s: Invalid Job data, terminated.", thread.name)
            return

        logger.info('%s: Job ID %s: Started...', thread.name, batch_id)

        # AI Processing of input data in `job` goes here
        # Store the AI Results in `output`

        entities = [
            "container_nodes",
            "container_nodes_tags",
            "volume_attachments",
            "volumes",
            "volume_types",
            "vms",
            "sources"
        ]

        all_dataframes = {}

        for entity in entities:
            json_data = batch_data.get(entity)
            all_dataframes[entity] = pd.DataFrame(json_data)

        logger.info(
            '%s: Job ID %s: Validating Volume Types in Clusters...',
            thread.name, batch_id
        )

        topology_data = AwsVolumeTypeValidation(all_dataframes)
        result = topology_data.validate()

        # Build response JSON
        output = {
            'id': batch_id,
            'ai_service': ai_service,
            'data': result.to_dict()
        }

        logger.info(
            '%s: Job ID %s: Validation done, publishing...',
            thread.name, batch_id
        )

        # Pass to the next service
        try:
            _retryable(
                'post',
                next_service,
                json=output,
                headers={"x-rh-identity": b64_identity}
            )
        except requests.HTTPError as exception:
            logger.error(
                '%s: Failed to pass data for "%s": %s',
                thread.name, batch_id, exception
            )

        logger.debug('%s: Done, exiting', thread.name)

    thread = Thread(target=worker)
    thread.start()

    return thread
