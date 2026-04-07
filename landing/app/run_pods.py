"""Run pod lifecycle manager — create, monitor, and tear down run pods."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

from kubernetes import client, config
from kubernetes.client.rest import ApiException


class RunPodManager:
    """Wraps the Kubernetes Python client to manage run pods.

    Run pods serve published applications in read-only mode — no Claude
    session, no editing.  They are lighter-weight than build pods.
    """

    def __init__(self) -> None:
        # Load cluster config (in-cluster first, fallback to kubeconfig for local dev)
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        self._core = client.CoreV1Api()
        self._namespace = os.environ.get("SUS_WORKLOADS_NAMESPACE", "sus-workloads")

        # Resource defaults — lighter than build pods
        self._cpu_request = os.environ.get("SUS_RUN_CPU_REQUEST", "100m")
        self._cpu_limit = os.environ.get("SUS_RUN_CPU_LIMIT", "500m")
        self._mem_request = os.environ.get("SUS_RUN_MEM_REQUEST", "128Mi")
        self._mem_limit = os.environ.get("SUS_RUN_MEM_LIMIT", "256Mi")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _short_hash(team: str, app_slug: str) -> str:
        """Return an 8-char hex hash for pod-name uniqueness."""
        digest = hashlib.sha256(
            f"{team}:{app_slug}:{datetime.now(timezone.utc).isoformat()}".encode()
        )
        return digest.hexdigest()[:8]

    def _pod_manifest(
        self,
        name: str,
        team: str,
        app_slug: str,
        image: str,
    ) -> client.V1Pod:
        # Get the repo URL from ConfigMap or env var.
        repo_url = ""
        try:
            from .repo_config import RepoConfigManager
            repo_url = RepoConfigManager().get_url()
        except Exception:
            pass
        if not repo_url:
            repo_url = os.environ.get("SUS_GIT_REPO_URL", "")

        return client.V1Pod(
            metadata=client.V1ObjectMeta(
                name=name,
                namespace=self._namespace,
                labels={
                    "app.kubernetes.io/component": "run",
                    "sus.dev/team": team,
                    "sus.dev/app": app_slug,
                },
            ),
            spec=client.V1PodSpec(
                restart_policy="Always",
                containers=[
                    client.V1Container(
                        name="app",
                        image=image,
                        image_pull_policy="IfNotPresent",
                        command=["/run-entrypoint.sh"],
                        ports=[
                            client.V1ContainerPort(container_port=3000, name="http"),
                        ],
                        env=[
                            client.V1EnvVar(name="APP_TEAM", value=team),
                            client.V1EnvVar(name="APP_SLUG", value=app_slug),
                            client.V1EnvVar(name="GIT_REPO_URL", value=repo_url),
                            client.V1EnvVar(
                                name="GIT_TOKEN",
                                value_from=client.V1EnvVarSource(
                                    secret_key_ref=client.V1SecretKeySelector(
                                        name="sus-git-token",
                                        key="GIT_TOKEN",
                                        optional=True,
                                    ),
                                ),
                            ),
                        ],
                        resources=client.V1ResourceRequirements(
                            requests={
                                "cpu": self._cpu_request,
                                "memory": self._mem_request,
                            },
                            limits={
                                "cpu": self._cpu_limit,
                                "memory": self._mem_limit,
                            },
                        ),
                    )
                ],
            ),
        )

    @staticmethod
    def _pod_to_dict(pod: client.V1Pod) -> dict:
        """Extract useful status info from a V1Pod object."""
        return {
            "name": pod.metadata.name,
            "phase": pod.status.phase if pod.status else None,
            "pod_ip": pod.status.pod_ip if pod.status else None,
            "ports": {"http": 3000},
            "labels": pod.metadata.labels or {},
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_run_pod(self, team: str, app_slug: str, image: str) -> dict:
        """Create a run pod and return its status info."""
        short = self._short_hash(team, app_slug)
        name = f"run-{team}-{app_slug}-{short}"
        manifest = self._pod_manifest(name, team, app_slug, image)
        pod = self._core.create_namespaced_pod(
            namespace=self._namespace, body=manifest
        )
        return self._pod_to_dict(pod)

    def get_run_pod(self, pod_name: str) -> dict | None:
        """Return pod status info or None if not found."""
        try:
            pod = self._core.read_namespaced_pod(
                name=pod_name, namespace=self._namespace
            )
            return self._pod_to_dict(pod)
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise

    def find_run_pod(self, team: str, app_slug: str) -> dict | None:
        """Find an existing run pod for this app by label selector."""
        label_selector = (
            f"app.kubernetes.io/component=run,"
            f"sus.dev/team={team},"
            f"sus.dev/app={app_slug}"
        )
        pods = self._core.list_namespaced_pod(
            namespace=self._namespace,
            label_selector=label_selector,
        )
        if not pods.items:
            return None
        # Return the first match (there should be at most one).
        return self._pod_to_dict(pods.items[0])

    def delete_run_pod(self, pod_name: str) -> None:
        """Delete a run pod by name."""
        try:
            self._core.delete_namespaced_pod(
                name=pod_name,
                namespace=self._namespace,
                body=client.V1DeleteOptions(grace_period_seconds=5),
            )
        except ApiException as exc:
            if exc.status != 404:
                raise

    def list_run_pods(self) -> list[dict]:
        """List all run pods."""
        label_selector = "app.kubernetes.io/component=run"
        pods = self._core.list_namespaced_pod(
            namespace=self._namespace,
            label_selector=label_selector,
        )
        return [self._pod_to_dict(p) for p in pods.items]
