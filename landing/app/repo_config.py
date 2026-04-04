"""Manage the app repo URL as a Kubernetes ConfigMap."""

from __future__ import annotations

import logging
import os

from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

CONFIGMAP_NAME = "sus-repo-config"
KEY = "REPO_URL"


class RepoConfigManager:
    """Read and write the app repo URL stored in a K8s ConfigMap."""

    def __init__(self) -> None:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        self._core = client.CoreV1Api()
        self._namespace = os.environ.get("SUS_WORKLOADS_NAMESPACE", "sus-workloads")

    def get_url(self) -> str:
        """Get the configured repo URL. Falls back to env var."""
        try:
            cm = self._core.read_namespaced_config_map(CONFIGMAP_NAME, self._namespace)
            if cm.data and KEY in cm.data:
                return cm.data[KEY]
        except ApiException as exc:
            if exc.status != 404:
                raise
        return os.environ.get("SUS_GIT_REPO_URL", "")

    def set_url(self, url: str) -> None:
        """Create or update the repo URL ConfigMap."""
        cm = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(name=CONFIGMAP_NAME, namespace=self._namespace),
            data={KEY: url},
        )
        try:
            self._core.read_namespaced_config_map(CONFIGMAP_NAME, self._namespace)
            self._core.replace_namespaced_config_map(CONFIGMAP_NAME, self._namespace, cm)
        except ApiException as exc:
            if exc.status == 404:
                self._core.create_namespaced_config_map(self._namespace, cm)
            else:
                raise

    def is_configured(self) -> bool:
        return bool(self.get_url())
