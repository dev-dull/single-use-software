"""Manage the Git access token as a Kubernetes Secret."""

from __future__ import annotations

import logging
import os

from kubernetes import client, config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

SECRET_NAME = "sus-git-token"
SECRET_KEY = "GIT_TOKEN"


class GitTokenManager:
    """Check, set, and read the Git access token stored as a K8s Secret."""

    def __init__(self) -> None:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        self._core = client.CoreV1Api()
        self._namespace = os.environ.get("SUS_WORKLOADS_NAMESPACE", "sus-workloads")

    def is_configured(self) -> bool:
        try:
            self._core.read_namespaced_secret(SECRET_NAME, self._namespace)
            return True
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise

    def get_token(self) -> str | None:
        try:
            secret = self._core.read_namespaced_secret(SECRET_NAME, self._namespace)
            if secret.data and SECRET_KEY in secret.data:
                import base64
                return base64.b64decode(secret.data[SECRET_KEY]).decode()
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise
        return None

    def set_token(self, token: str) -> None:
        secret = client.V1Secret(
            metadata=client.V1ObjectMeta(name=SECRET_NAME, namespace=self._namespace),
            string_data={SECRET_KEY: token},
            type="Opaque",
        )
        try:
            self._core.read_namespaced_secret(SECRET_NAME, self._namespace)
            self._core.replace_namespaced_secret(SECRET_NAME, self._namespace, secret)
            logger.info("Updated Git token secret in %s", self._namespace)
        except ApiException as exc:
            if exc.status == 404:
                self._core.create_namespaced_secret(self._namespace, secret)
                logger.info("Created Git token secret in %s", self._namespace)
            else:
                raise

    def delete_token(self) -> None:
        try:
            self._core.delete_namespaced_secret(SECRET_NAME, self._namespace)
        except ApiException as exc:
            if exc.status != 404:
                raise
