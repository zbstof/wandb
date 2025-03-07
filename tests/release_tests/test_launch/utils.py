import signal
import subprocess
import sys
from time import sleep
from typing import Tuple

import wandb
from kubernetes import client, config, watch
from wandb.apis.public import Api


def run_cmd(command: str) -> None:
    subprocess.Popen(command.split(" ")).wait()


def run_cmd_async(command: str) -> subprocess.Popen:
    # Returns process. Terminate with process.kill()
    return subprocess.Popen(command.split(" "))


def cleanup_deployment(namespace: str):
    """Delete a k8s deployment and all pods in the same namespace."""
    config.load_kube_config()
    apps_api = client.AppsV1Api()
    core_api = client.CoreV1Api()

    apps_api.delete_namespaced_deployment(
        name="launch-agent-release-testing", namespace=namespace
    )
    pods = core_api.list_namespaced_pod(namespace=namespace).items
    for pod in pods:
        core_api.delete_namespaced_pod(name=pod.metadata.name, namespace=namespace)


def wait_for_image_job_completion(
    namespace: str, entity: str, project: str, queued_run
) -> Tuple[str, str]:
    """W&B's wait_until_finished() doesn't work for image based jobs, so poll the k8s output for job completion."""
    config.load_kube_config()
    v1 = client.CoreV1Api()
    w = watch.Watch()
    status = None
    for event in w.stream(
        v1.list_namespaced_pod, namespace=namespace, timeout_seconds=300
    ):
        if event["object"].metadata.name.startswith(f"launch-{entity}-{project}-"):
            status = event["object"].status.phase
            if status == "Succeeded":
                w.stop()

    item = queued_run._get_item()
    tries = 0
    while not item["associatedRunId"] and tries < 5:
        sleep(2**tries)
        tries += 1
        item = queued_run._get_item()
    run_id = item["associatedRunId"]
    api = Api()
    tries = 0
    run = None
    while not (run and run.state == "finished") and tries < 5:
        # Sometimes takes a bit for the run's completion to populate in W&B
        try:
            run = api.run(path=f"{entity}/{project}/{run_id}")
            run.load(force=True)
        except wandb.errors.CommError:
            pass
        sleep(2**tries)
        tries += 1
    return status, run


def setup_cleanup_on_exit(namespace: str):
    # Capture sigint so cleanup occurs even on ctrl-C
    sigint = signal.getsignal(signal.SIGINT)

    def cleanup(signum, frame):
        signal.signal(signal.SIGINT, sigint)
        cleanup_deployment(namespace)
        sys.exit(1)

    signal.signal(signal.SIGINT, cleanup)


def update_dict(original, updated):
    """Recursively apply a patch dict to an original.

    Any item that's not a dict (list, str, etc) is copied over entirely and overwrites contents of original.
    """
    for key, value in updated.items():
        if isinstance(value, dict) and key in original:
            update_dict(original[key], value)
        else:
            original[key] = value
